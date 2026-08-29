"""Thin M8-M14 sequencing over existing independently testable services."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from data_agent.answer.context import build_answer_synthesis_context
from data_agent.answer.errors import AnswerError
from data_agent.answer.service import AnswerSynthesizer
from data_agent.catalog.semantic import AssembledSemanticCatalog
from data_agent.contracts.dialogue import DialogueAction
from data_agent.contracts.message import Message, MessageRole
from data_agent.contracts.requirement import RequirementState
from data_agent.contracts.retrieval import RetrievalResult
from data_agent.contracts.run import Run, RunStatus
from data_agent.conversation.models import (
    ClarificationResponse,
    ConversationResponse,
    FailureResponse,
    build_result_response,
)
from data_agent.dialogue.service import DialogueService
from data_agent.persistence.ports import ConversationUnitOfWork, RunRepository, TraceRepository
from data_agent.planning.errors import PlannerError
from data_agent.planning.service import PlanningTrace
from data_agent.query_runtime.errors import RuntimeExecutionError
from data_agent.query_runtime.service import RuntimeExecutionEvidence
from data_agent.repair.evidence import RepairFailure, RepairOutcomeKind
from data_agent.repair.failures import (
    failure_from_admission,
    failure_from_runtime,
    failure_from_verification,
    failure_from_verification_integrity,
)
from data_agent.repair.service import BoundedRepairService, RepairPipelineOutcome
from data_agent.retrieval.errors import RetrievalError
from data_agent.retrieval.service import RetrievalTrace
from data_agent.run_state import TERMINAL_RUN_STATUSES
from data_agent.sql_guard.capability import GuardedQuery
from data_agent.sql_guard.service import SQLAdmissionService
from data_agent.trace.errors import TraceError
from data_agent.trace.model import TraceEventDraft, TraceEventType, TraceStage
from data_agent.trace.policy import TraceCompletenessPolicy
from data_agent.trace.projection import (
    admission_payload,
    admitted_query_payload,
    dialogue_payload,
    execution_payload,
    planning_payload,
    repair_payload,
    retrieval_payload,
    synthesis_payload,
    verification_payload,
)
from data_agent.verification.context import build_verification_context
from data_agent.verification.errors import VerificationIntegrityError
from data_agent.verification.evidence import VerificationTrace
from data_agent.verification.service import DeterministicVerifier


class ConversationQueryRuntime(Protocol):
    def execute_with_evidence(self, query: GuardedQuery) -> RuntimeExecutionEvidence: ...


class ConversationRetriever(Protocol):
    async def retrieve(self, query: str) -> RetrievalTrace: ...


class ConversationPlanner(Protocol):
    async def plan(
        self,
        *,
        requirement: RequirementState,
        retrieval: RetrievalResult,
        catalog: AssembledSemanticCatalog,
        expected_retrieval_index_fingerprint: str,
    ) -> PlanningTrace: ...


def requirement_retrieval_query(requirement: RequirementState) -> str:
    """Project only current authoritative requirement state into retrieval text."""

    values: list[str] = []
    if requirement.goal is not None:
        values.append(str(requirement.goal))
    for metric in requirement.metrics:
        values.extend(str(value) for value in (metric.term, metric.resolved_name) if value)
    for dimension in requirement.dimensions:
        values.extend(str(value) for value in (dimension.term, dimension.resolved_name) if value)
    for value in (requirement.grain, requirement.comparison):
        if value is not None:
            values.append(str(value))
    if requirement.time_range is not None:
        values.append(str(requirement.time_range.value))
    query = " | ".join(dict.fromkeys(values))
    if not query:
        raise ValueError("READY requirement produced no retrieval query")
    return query


_SAFE_FAILURE_MESSAGES = {
    RunStatus.POLICY_DENIED: "请求未通过只读查询安全策略。",
    RunStatus.QUERY_TOO_EXPENSIVE: "查询成本超过当前允许范围。",
    RunStatus.REPAIR_EXHAUSTED: "查询修复次数已用尽, 无法安全返回结果。",
    RunStatus.FAILED: "本次请求未能安全完成。",
}

_FAILURE_EVENT_BY_STATUS: dict[RunStatus, tuple[TraceEventType, TraceStage]] = {
    RunStatus.RECEIVED: (TraceEventType.DIALOGUE_COMPLETED, TraceStage.DIALOGUE),
    RunStatus.UNDERSTANDING: (TraceEventType.DIALOGUE_COMPLETED, TraceStage.DIALOGUE),
    RunStatus.RETRIEVING: (TraceEventType.RETRIEVAL_COMPLETED, TraceStage.RETRIEVAL),
    RunStatus.PLANNING: (TraceEventType.PLANNING_COMPLETED, TraceStage.PLANNING),
    RunStatus.VALIDATING: (TraceEventType.SQL_ADMISSION_COMPLETED, TraceStage.SQL_ADMISSION),
    RunStatus.EXECUTING: (TraceEventType.EXECUTION_COMPLETED, TraceStage.EXECUTION),
    RunStatus.VERIFYING: (TraceEventType.VERIFICATION_COMPLETED, TraceStage.VERIFICATION),
    RunStatus.SYNTHESIZING: (TraceEventType.SYNTHESIS_COMPLETED, TraceStage.SYNTHESIS),
}


class ConversationOrchestrator:
    """Own lifecycle sequencing; every stage retains its existing policy authority."""

    def __init__(
        self,
        *,
        dialogue: DialogueService,
        unit_of_work: ConversationUnitOfWork,
        runs: RunRepository,
        retriever: ConversationRetriever,
        planner: ConversationPlanner,
        catalog: AssembledSemanticCatalog,
        retrieval_index_fingerprint: str,
        admission: SQLAdmissionService,
        query_runtime: ConversationQueryRuntime,
        verifier: DeterministicVerifier,
        repair: BoundedRepairService,
        synthesizer: AnswerSynthesizer,
        clock: Callable[[], datetime],
        id_factory: Callable[[str], str],
        traces: TraceRepository,
    ) -> None:
        self._dialogue = dialogue
        self._uow = unit_of_work
        self._runs = runs
        self._retriever = retriever
        self._planner = planner
        self._catalog = catalog
        self._retrieval_index_fingerprint = retrieval_index_fingerprint
        self._admission = admission
        self._query_runtime = query_runtime
        self._verifier = verifier
        self._repair = repair
        self._synthesizer = synthesizer
        self._clock = clock
        self._id_factory = id_factory
        self._traces = traces

    async def process_message(self, *, session_id: str, content: str) -> ConversationResponse:
        started_at = self._clock()
        run = self._runs.create(
            Run(
                id=self._id_factory("run"),
                session_id=session_id,
                status=RunStatus.RECEIVED,
                started_at=started_at,
            )
        )
        self._append(
            self._event(
                run,
                event_type=TraceEventType.RUN_RECEIVED,
                stage=TraceStage.RUN,
                payload={"outcome": "RECEIVED", "initial_status": RunStatus.RECEIVED.value},
            )
        )
        self._runs.transition(str(run.id), RunStatus.UNDERSTANDING, transitioned_at=self._clock())
        try:
            prepared = await self._dialogue.prepare_turn(
                session_id=session_id, user_content=content
            )
            if prepared.outcome.decision.action is DialogueAction.ASK_CLARIFICATION:
                dialogue_event = self._event(
                    run,
                    event_type=TraceEventType.DIALOGUE_COMPLETED,
                    stage=TraceStage.DIALOGUE,
                    payload=dialogue_payload(prepared),
                )
                committed = self._uow.commit_dialogue_with_run(
                    session=prepared.session,
                    expected_revision=prepared.expected_revision,
                    user_message=prepared.user_message,
                    assistant_message=prepared.assistant_message,
                    run_id=str(run.id),
                    target=RunStatus.CLARIFYING,
                    trace_events=(
                        dialogue_event,
                        self._terminal_event(
                            run,
                            status=RunStatus.CLARIFYING,
                            error_code=None,
                        ),
                    ),
                )
                question = prepared.outcome.decision.question
                if question is None:
                    raise ValueError("clarification outcome has no question")
                return ClarificationResponse(
                    session_id=session_id,
                    run_id=str(committed.run.id),
                    question=str(question),
                    requirement=prepared.outcome.requirement.model_dump(mode="json"),
                )
            if prepared.outcome.decision.action is DialogueAction.CANNOT_RESOLVE:
                dialogue_event = self._event(
                    run,
                    event_type=TraceEventType.DIALOGUE_COMPLETED,
                    stage=TraceStage.DIALOGUE,
                    payload=dialogue_payload(prepared),
                )
                committed = self._uow.commit_dialogue_with_run(
                    session=prepared.session,
                    expected_revision=prepared.expected_revision,
                    user_message=prepared.user_message,
                    assistant_message=None,
                    run_id=str(run.id),
                    target=RunStatus.FAILED,
                    trace_events=(
                        dialogue_event,
                        self._terminal_event(
                            run,
                            status=RunStatus.FAILED,
                            error_code="DIALOGUE_CANNOT_RESOLVE",
                        ),
                    ),
                )
                return self._failure(committed.run)

            committed = self._uow.commit_dialogue_with_run(
                session=prepared.session,
                expected_revision=prepared.expected_revision,
                user_message=prepared.user_message,
                assistant_message=None,
                run_id=str(run.id),
                target=RunStatus.RETRIEVING,
                trace_events=(
                    self._event(
                        run,
                        event_type=TraceEventType.DIALOGUE_COMPLETED,
                        stage=TraceStage.DIALOGUE,
                        payload=dialogue_payload(prepared),
                    ),
                ),
            )
            return await self._run_query(
                run=committed.run,
                requirement=prepared.outcome.requirement,
            )
        except TraceError:
            raise
        except Exception:
            return self._failure(self._terminalize_pipeline_failure(str(run.id)))

    async def _run_query(self, *, run: Run, requirement: RequirementState) -> ConversationResponse:
        try:
            retrieval = await self._retriever.retrieve(requirement_retrieval_query(requirement))
            self._append(
                self._event(
                    run,
                    event_type=TraceEventType.RETRIEVAL_COMPLETED,
                    stage=TraceStage.RETRIEVAL,
                    payload=retrieval_payload(retrieval),
                )
            )
            run = self._runs.transition(
                str(run.id), RunStatus.PLANNING, transitioned_at=self._clock()
            )
            planning = await self._planner.plan(
                requirement=requirement,
                retrieval=retrieval.result,
                catalog=self._catalog,
                expected_retrieval_index_fingerprint=self._retrieval_index_fingerprint,
            )
            self._append(
                self._event(
                    run,
                    event_type=TraceEventType.PLANNING_COMPLETED,
                    stage=TraceStage.PLANNING,
                    payload=planning_payload(planning),
                )
            )
            run = self._runs.transition(
                str(run.id), RunStatus.VALIDATING, transitioned_at=self._clock()
            )
            admission = self._admission.admit(
                planning.plan,
                planner_context_fingerprint=planning.planner_context_fingerprint,
            )
            self._append(
                self._event(
                    run,
                    event_type=TraceEventType.SQL_ADMISSION_COMPLETED,
                    stage=TraceStage.SQL_ADMISSION,
                    payload=admission_payload(admission),
                )
            )
            if admission.guarded_query is None:
                return await self._repair_or_finish(
                    run=run,
                    original=planning,
                    failure=failure_from_admission(planning, admission, source_run_id=str(run.id)),
                )
            guarded = admission.guarded_query
            run = self._runs.transition(
                str(run.id), RunStatus.EXECUTING, transitioned_at=self._clock()
            )
            try:
                execution = self._query_runtime.execute_with_evidence(guarded)
            except RuntimeExecutionError as error:
                failure = failure_from_runtime(planning, guarded, error, source_run_id=str(run.id))
                self._append(
                    self._event(
                        run,
                        event_type=TraceEventType.EXECUTION_COMPLETED,
                        stage=TraceStage.EXECUTION,
                        payload=execution_payload(None, guarded=guarded, failure=failure),
                    )
                )
                return await self._repair_or_finish(
                    run=run,
                    original=planning,
                    failure=failure,
                )
            self._append(
                self._event(
                    run,
                    event_type=TraceEventType.EXECUTION_COMPLETED,
                    stage=TraceStage.EXECUTION,
                    payload=execution_payload(execution.metadata, result=execution.result),
                )
            )
            run = self._runs.transition(
                str(run.id), RunStatus.VERIFYING, transitioned_at=self._clock()
            )
            try:
                verification = self._verifier.verify(
                    build_verification_context(
                        planning_trace=planning,
                        guarded_query=guarded,
                        execution_metadata=execution.metadata,
                        execution_result=execution.result,
                    )
                )
            except VerificationIntegrityError:
                failure = failure_from_verification_integrity(planning, source_run_id=str(run.id))
                self._append(
                    self._event(
                        run,
                        event_type=TraceEventType.VERIFICATION_COMPLETED,
                        stage=TraceStage.VERIFICATION,
                        payload=verification_payload(None, failure=failure),
                    )
                )
                return await self._repair_or_finish(
                    run=run,
                    original=planning,
                    failure=failure,
                )
            if verification.result.status != "PASSED":
                failure = failure_from_verification(
                    planning,
                    guarded,
                    verification,
                    source_run_id=str(run.id),
                )
                self._append(
                    self._event(
                        run,
                        event_type=TraceEventType.VERIFICATION_COMPLETED,
                        stage=TraceStage.VERIFICATION,
                        payload=verification_payload(verification, failure=failure),
                    )
                )
                return await self._repair_or_finish(
                    run=run,
                    original=planning,
                    failure=failure,
                )
            self._append(
                self._event(
                    run,
                    event_type=TraceEventType.VERIFICATION_COMPLETED,
                    stage=TraceStage.VERIFICATION,
                    payload=verification_payload(verification),
                )
            )
            run = self._runs.transition(
                str(run.id), RunStatus.SYNTHESIZING, transitioned_at=self._clock()
            )
            return await self._synthesize_and_complete(
                run=run,
                planning=planning,
                guarded=guarded,
                execution=execution,
                verification=verification,
                repair_outcome=None,
            )
        except TraceError:
            raise
        except (RetrievalError, PlannerError, AnswerError, ValueError):
            return self._failure(self._terminalize_pipeline_failure(str(run.id)))

    async def _repair_or_finish(
        self,
        *,
        run: Run,
        original: PlanningTrace,
        failure: RepairFailure,
    ) -> ConversationResponse:
        outcome = await self._repair.repair(
            run_id=str(run.id),
            original=original,
            failure=failure,
            occurred_at=self._clock(),
        )
        attempt = outcome.trace.attempt
        repair_events = [
            self._event(
                run,
                event_type=TraceEventType.REPAIR_COMPLETED,
                stage=TraceStage.REPAIR,
                payload=repair_payload(outcome.trace),
                attempt=attempt,
            )
        ]
        if outcome.replacement_planning_trace is not None:
            repair_events.append(
                self._event(
                    run,
                    event_type=TraceEventType.PLANNING_COMPLETED,
                    stage=TraceStage.PLANNING,
                    payload=planning_payload(outcome.replacement_planning_trace),
                    attempt=1,
                )
            )
            repair_events.append(
                self._event(
                    run,
                    event_type=TraceEventType.SQL_ADMISSION_COMPLETED,
                    stage=TraceStage.SQL_ADMISSION,
                    payload=(
                        admitted_query_payload(outcome.guarded_query)
                        if outcome.guarded_query is not None
                        else {
                            "outcome": "FAILED",
                            "failure_code": outcome.terminal_error_code,
                            "query_plan_fingerprint": (
                                outcome.trace.replacement_query_plan_fingerprint
                            ),
                            "planner_context_fingerprint": (
                                outcome.trace.planner_context_fingerprint
                            ),
                        }
                    ),
                    attempt=1,
                )
            )
        if outcome.guarded_query is not None:
            if outcome.execution_metadata is not None:
                repair_events.append(
                    self._event(
                        run,
                        event_type=TraceEventType.EXECUTION_COMPLETED,
                        stage=TraceStage.EXECUTION,
                        payload=execution_payload(
                            outcome.execution_metadata,
                            result=outcome.execution_result,
                        ),
                        attempt=1,
                    )
                )
            elif outcome.trace.outcome is RepairOutcomeKind.EXECUTION_FAILED:
                repair_events.append(
                    self._event(
                        run,
                        event_type=TraceEventType.EXECUTION_COMPLETED,
                        stage=TraceStage.EXECUTION,
                        payload={
                            "outcome": "FAILED",
                            "failure_code": outcome.terminal_error_code,
                            "guarded_query_fingerprint": (
                                outcome.guarded_query.capability_fingerprint
                            ),
                            "sql_digest": outcome.guarded_query.sql_digest,
                        },
                        attempt=1,
                    )
                )
        if outcome.verification_trace is not None:
            repair_events.append(
                self._event(
                    run,
                    event_type=TraceEventType.VERIFICATION_COMPLETED,
                    stage=TraceStage.VERIFICATION,
                    payload=verification_payload(outcome.verification_trace),
                    attempt=1,
                )
            )
        elif (
            outcome.execution_metadata is not None
            and outcome.trace.outcome is RepairOutcomeKind.VERIFICATION_FAILED
        ):
            repair_events.append(
                self._event(
                    run,
                    event_type=TraceEventType.VERIFICATION_COMPLETED,
                    stage=TraceStage.VERIFICATION,
                    payload={
                        "outcome": "FAILED",
                        "failure_code": outcome.terminal_error_code,
                        "execution_id": outcome.execution_metadata.execution_id,
                        "result_fingerprint": outcome.execution_metadata.result_fingerprint,
                    },
                    attempt=1,
                )
            )
        if outcome.trace.outcome is RepairOutcomeKind.SUCCEEDED and (
            outcome.replacement_planning_trace is None
            or outcome.guarded_query is None
            or outcome.execution_metadata is None
            or outcome.verification_trace is None
        ):
            return self._failure(
                self._terminalize(
                    str(run.id),
                    code="REPAIR_EVIDENCE_INCOMPLETE",
                    preceding_events=tuple(repair_events),
                )
            )
        if outcome.trace.outcome is not RepairOutcomeKind.SUCCEEDED:
            terminal = outcome.run
            if terminal.status not in TERMINAL_RUN_STATUSES:
                terminal = self._terminalize(
                    str(terminal.id),
                    code=outcome.terminal_error_code or str(failure.code),
                    target=outcome.terminal_status or RunStatus.FAILED,
                    preceding_events=tuple(repair_events),
                )
            else:
                self._append_many(tuple(repair_events))
                terminal_event = self._terminal_event(
                    terminal,
                    status=terminal.status,
                    error_code=terminal.error_code,
                    attempt=terminal.repair_count,
                )
                self._append(terminal_event)
                TraceCompletenessPolicy().validate(
                    terminal,
                    tuple(self._traces.list_for_run(str(terminal.id))),
                )
            return self._failure(terminal)
        self._append_many(tuple(repair_events))
        if (
            outcome.replacement_planning_trace is None
            or outcome.guarded_query is None
            or outcome.execution_metadata is None
            or outcome.execution_result is None
            or outcome.verification_trace is None
            or outcome.verification_trace.result.status != "PASSED"
        ):
            return self._failure(self._terminalize(str(run.id), code="REPAIR_EVIDENCE_INCOMPLETE"))
        execution = RuntimeExecutionEvidence(
            metadata=outcome.execution_metadata,
            result=outcome.execution_result,
        )
        return await self._synthesize_and_complete(
            run=outcome.run,
            planning=outcome.replacement_planning_trace,
            guarded=outcome.guarded_query,
            execution=execution,
            verification=outcome.verification_trace,
            repair_outcome=outcome,
        )

    async def _synthesize_and_complete(
        self,
        *,
        run: Run,
        planning: PlanningTrace,
        guarded: GuardedQuery,
        execution: RuntimeExecutionEvidence,
        verification: VerificationTrace,
        repair_outcome: RepairPipelineOutcome | None,
    ) -> ConversationResponse:
        try:
            context = build_answer_synthesis_context(
                session_id=str(run.session_id),
                run_id=str(run.id),
                planning_trace=planning,
                guarded_query=guarded,
                execution_metadata=execution.metadata,
                execution_result=execution.result,
                verification_trace=verification,
                repair_trace=None if repair_outcome is None else repair_outcome.trace,
            )
            synthesis = await self._synthesizer.synthesize(context)
            completed_at = self._clock()
            assistant_message = Message(
                id=self._id_factory("message"),
                session_id=str(run.session_id),
                role=MessageRole.ASSISTANT,
                content=synthesis.answer,
                created_at=completed_at,
            )
            attempt = run.repair_count
            completed = self._uow.complete_run_with_message(
                run_id=str(run.id),
                assistant_message=assistant_message,
                completed_at=completed_at,
                trace_events=(
                    self._event(
                        run,
                        event_type=TraceEventType.SYNTHESIS_COMPLETED,
                        stage=TraceStage.SYNTHESIS,
                        payload=synthesis_payload(
                            synthesis,
                            assistant_message_id=str(assistant_message.id),
                        ),
                        attempt=attempt,
                        occurred_at=completed_at,
                    ),
                    self._terminal_event(
                        run,
                        status=RunStatus.COMPLETED,
                        error_code=None,
                        attempt=attempt,
                        occurred_at=completed_at,
                    ),
                ),
            )
            return build_result_response(
                session_id=str(run.session_id),
                run=completed.run,
                planning_trace=planning,
                guarded_query=guarded,
                execution_result=execution.result,
                verification_trace=verification,
                synthesis=synthesis,
            )
        except TraceError:
            raise
        except Exception:
            self._append(
                self._event(
                    run,
                    event_type=TraceEventType.SYNTHESIS_COMPLETED,
                    stage=TraceStage.SYNTHESIS,
                    payload=synthesis_payload(None, error_code="SYNTHESIS_FAILED"),
                    attempt=run.repair_count,
                )
            )
            return self._failure(self._terminalize(str(run.id), code="SYNTHESIS_FAILED"))

    def _terminalize(
        self,
        run_id: str,
        *,
        code: str,
        target: RunStatus = RunStatus.FAILED,
        preceding_events: tuple[TraceEventDraft, ...] = (),
    ) -> Run:
        current = self._runs.get(run_id)
        if current.status in TERMINAL_RUN_STATUSES:
            return current
        completed_at = self._clock()
        return self._uow.terminate_run_with_trace(
            run_id=run_id,
            target=target,
            completed_at=completed_at,
            error_code=code,
            trace_events=(
                *preceding_events,
                self._terminal_event(
                    current,
                    status=target,
                    error_code=code,
                    attempt=current.repair_count,
                    occurred_at=completed_at,
                ),
            ),
        )

    def _terminalize_pipeline_failure(self, run_id: str) -> Run:
        current = self._runs.get(run_id)
        event_type, stage = _FAILURE_EVENT_BY_STATUS.get(
            current.status,
            (TraceEventType.DIALOGUE_COMPLETED, TraceStage.DIALOGUE),
        )
        payload: dict[str, object] = {
            "outcome": "FAILED",
            "error_code": "PIPELINE_FAILED",
        }
        attempt = current.repair_count
        return self._terminalize(
            run_id,
            code="PIPELINE_FAILED",
            preceding_events=(
                self._event(
                    current,
                    event_type=event_type,
                    stage=stage,
                    payload=payload,
                    attempt=attempt,
                ),
            ),
        )

    def _event(
        self,
        run: Run,
        *,
        event_type: TraceEventType,
        stage: TraceStage,
        payload: dict[str, object],
        attempt: int = 0,
        occurred_at: datetime | None = None,
    ) -> TraceEventDraft:
        return TraceEventDraft(
            id=self._id_factory("trace"),
            session_id=str(run.session_id),
            run_id=str(run.id),
            attempt=attempt,
            stage=stage,
            event_type=event_type,
            payload=payload,
            occurred_at=occurred_at or self._clock(),
        )

    def _terminal_event(
        self,
        run: Run,
        *,
        status: RunStatus,
        error_code: str | None,
        attempt: int = 0,
        occurred_at: datetime | None = None,
    ) -> TraceEventDraft:
        return self._event(
            run,
            event_type=TraceEventType.RUN_TERMINATED,
            stage=TraceStage.RUN,
            payload={
                "outcome": "TERMINATED",
                "terminal_status": status.value,
                "error_code": error_code,
            },
            attempt=attempt,
            occurred_at=occurred_at,
        )

    def _append(self, draft: TraceEventDraft) -> None:
        try:
            self._traces.append(draft)
        except TraceError:
            raise
        except Exception as error:
            raise TraceError("trace persistence failed closed") from error

    def _append_many(self, drafts: tuple[TraceEventDraft, ...]) -> None:
        try:
            self._traces.append_many(drafts)
        except TraceError:
            raise
        except Exception as error:
            raise TraceError("trace persistence failed closed") from error

    @staticmethod
    def _failure(run: Run) -> FailureResponse:
        return FailureResponse(
            session_id=str(run.session_id),
            run_id=str(run.id),
            code=str(run.error_code or run.status.value),
            message=_SAFE_FAILURE_MESSAGES.get(run.status, "本次请求未能安全完成。"),
            status=run.status,
        )
