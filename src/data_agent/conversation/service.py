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
from data_agent.persistence.ports import ConversationUnitOfWork, RunRepository
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
        self._runs.transition(str(run.id), RunStatus.UNDERSTANDING, transitioned_at=self._clock())
        try:
            prepared = await self._dialogue.prepare_turn(
                session_id=session_id, user_content=content
            )
            if prepared.outcome.decision.action is DialogueAction.ASK_CLARIFICATION:
                committed = self._uow.commit_dialogue_with_run(
                    session=prepared.session,
                    expected_revision=prepared.expected_revision,
                    user_message=prepared.user_message,
                    assistant_message=prepared.assistant_message,
                    run_id=str(run.id),
                    target=RunStatus.CLARIFYING,
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
                committed = self._uow.commit_dialogue_with_run(
                    session=prepared.session,
                    expected_revision=prepared.expected_revision,
                    user_message=prepared.user_message,
                    assistant_message=None,
                    run_id=str(run.id),
                    target=RunStatus.FAILED,
                )
                return self._failure(committed.run)

            committed = self._uow.commit_dialogue_with_run(
                session=prepared.session,
                expected_revision=prepared.expected_revision,
                user_message=prepared.user_message,
                assistant_message=None,
                run_id=str(run.id),
                target=RunStatus.RETRIEVING,
            )
            return await self._run_query(
                run=committed.run,
                requirement=prepared.outcome.requirement,
            )
        except Exception:
            return self._failure(self._terminalize(str(run.id), code="PIPELINE_FAILED"))

    async def _run_query(self, *, run: Run, requirement: RequirementState) -> ConversationResponse:
        try:
            retrieval = await self._retriever.retrieve(requirement_retrieval_query(requirement))
            run = self._runs.transition(
                str(run.id), RunStatus.PLANNING, transitioned_at=self._clock()
            )
            planning = await self._planner.plan(
                requirement=requirement,
                retrieval=retrieval.result,
                catalog=self._catalog,
                expected_retrieval_index_fingerprint=self._retrieval_index_fingerprint,
            )
            run = self._runs.transition(
                str(run.id), RunStatus.VALIDATING, transitioned_at=self._clock()
            )
            admission = self._admission.admit(
                planning.plan,
                planner_context_fingerprint=planning.planner_context_fingerprint,
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
                return await self._repair_or_finish(
                    run=run,
                    original=planning,
                    failure=failure_from_runtime(
                        planning, guarded, error, source_run_id=str(run.id)
                    ),
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
                return await self._repair_or_finish(
                    run=run,
                    original=planning,
                    failure=failure_from_verification_integrity(
                        planning, source_run_id=str(run.id)
                    ),
                )
            if verification.result.status != "PASSED":
                return await self._repair_or_finish(
                    run=run,
                    original=planning,
                    failure=failure_from_verification(
                        planning,
                        guarded,
                        verification,
                        source_run_id=str(run.id),
                    ),
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
        except (RetrievalError, PlannerError, AnswerError, ValueError):
            return self._failure(self._terminalize(str(run.id), code="PIPELINE_FAILED"))

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
        if outcome.trace.outcome is not RepairOutcomeKind.SUCCEEDED:
            terminal = outcome.run
            if terminal.status not in TERMINAL_RUN_STATUSES:
                terminal = self._terminalize(str(terminal.id), code=str(failure.code))
            return self._failure(terminal)
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
            completed = self._uow.complete_run_with_message(
                run_id=str(run.id),
                assistant_message=Message(
                    id=self._id_factory("message"),
                    session_id=str(run.session_id),
                    role=MessageRole.ASSISTANT,
                    content=synthesis.answer,
                    created_at=completed_at,
                ),
                completed_at=completed_at,
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
        except Exception:
            return self._failure(self._terminalize(str(run.id), code="SYNTHESIS_FAILED"))

    def _terminalize(self, run_id: str, *, code: str) -> Run:
        current = self._runs.get(run_id)
        if current.status in TERMINAL_RUN_STATUSES:
            return current
        return self._runs.transition(
            run_id,
            RunStatus.FAILED,
            transitioned_at=self._clock(),
            error_code=code,
        )

    @staticmethod
    def _failure(run: Run) -> FailureResponse:
        return FailureResponse(
            session_id=str(run.session_id),
            run_id=str(run.id),
            code=str(run.error_code or run.status.value),
            message=_SAFE_FAILURE_MESSAGES.get(run.status, "本次请求未能安全完成。"),
            status=run.status,
        )
