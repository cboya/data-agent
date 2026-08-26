from __future__ import annotations

import asyncio
from dataclasses import replace
from itertools import count

from data_agent.answer.proposal import AnswerProposal, CellReference
from data_agent.answer.service import AnswerSynthesizer
from data_agent.catalog.semantic import AssembledSemanticCatalog
from data_agent.contracts.dialogue import DialogueAction, DialogueDecision
from data_agent.contracts.requirement import Ambiguity, RequirementPatch
from data_agent.contracts.run import RunStatus
from data_agent.conversation.models import (
    ClarificationResponse,
    FailureResponse,
    ResultResponse,
)
from data_agent.conversation.service import ConversationOrchestrator
from data_agent.dialogue.service import DialogueEngine, DialogueService
from data_agent.planning.service import PlanningTrace
from data_agent.repair.service import BoundedRepairService
from data_agent.sql_guard.explain import ExplainPolicy
from data_agent.sql_guard.guard import SQLGuard
from data_agent.sql_guard.service import SQLAdmissionService
from data_agent.verification.service import DeterministicVerifier
from tests.answer.factories import FixedAnswerModel
from tests.conversation.factories import (
    NOW,
    MemoryConversationUnitOfWork,
    RecordingPlanner,
    RecordingRetriever,
    retrieval_trace,
)
from tests.dialogue.factories import FixedDialogueModel
from tests.repair.factories import (
    CoherentRuntime,
    FixedRepairModel,
    MemoryRunRepository,
    StaticExplainProvider,
)
from tests.verification.factories import DOCUMENTS, RELATIONSHIPS, evidence_bundle, valid_plan


def _decision(action: DialogueAction) -> DialogueDecision:
    unresolved = (
        [Ambiguity(field="metric", reason="metric changes the result")]
        if action is DialogueAction.ASK_CLARIFICATION
        else []
    )
    return DialogueDecision.model_validate(
        {
            "version": "v0.1",
            "patch": RequirementPatch(version="v0.2", unresolved_replace=unresolved).model_dump(
                mode="json"
            ),
            "action": action,
            "question": "你想使用哪个指标?" if action is DialogueAction.ASK_CLARIFICATION else None,
            "reason": "constructed M14 decision",
        }
    )


def _catalog() -> AssembledSemanticCatalog:
    return AssembledSemanticCatalog.build(
        generated_metadata_fingerprint="1" * 64,
        semantic_revision="2" * 64,
        documents=tuple(sorted(DOCUMENTS, key=lambda value: str(value.table))),
        relationships=tuple(
            sorted(
                RELATIONSHIPS,
                key=lambda value: (
                    str(value.from_table),
                    str(value.from_column),
                    str(value.to_table),
                    str(value.to_column),
                ),
            )
        ),
    )


def _orchestrator(
    *,
    action: DialogueAction = DialogueAction.READY,
    actions: tuple[DialogueAction, ...] | None = None,
    planning_trace: PlanningTrace | None = None,
    verifier: DeterministicVerifier | None = None,
    repair_error: Exception | None = None,
    answer_error: Exception | None = None,
) -> tuple[
    ConversationOrchestrator,
    RecordingRetriever,
    RecordingPlanner,
    FixedRepairModel,
    FixedAnswerModel,
    MemoryRunRepository,
    MemoryConversationUnitOfWork,
]:
    runs = MemoryRunRepository(run_id="unused", status=RunStatus.RECEIVED)
    uow = MemoryConversationUnitOfWork(runs=runs)
    ids = count(1)

    def id_factory(prefix: str) -> str:
        return f"{prefix}-m14-{next(ids)}"

    dialogue_model = FixedDialogueModel(*(_decision(value) for value in (actions or (action,))))
    dialogue = DialogueService(
        engine=DialogueEngine(chat_model=dialogue_model),
        store=uow,
        clock=lambda: NOW,
        id_factory=id_factory,
    )
    retriever = RecordingRetriever(retrieval_trace())
    planner = RecordingPlanner(planning_trace or evidence_bundle().planning_trace)
    admission = SQLAdmissionService(
        guard=SQLGuard(analytics_schema="data_agent"),
        explain_provider=StaticExplainProvider(),
        explain_policy=ExplainPolicy(max_estimated_rows_per_access=100),
    )
    runtime = CoherentRuntime()
    repair_model = FixedRepairModel(valid_plan(), error=repair_error)
    repair = BoundedRepairService(
        chat_model=repair_model,
        run_repository=runs,
        admission=admission,
        query_runtime=runtime,
    )
    answer_model = FixedAnswerModel(
        AnswerProposal(
            answer="首日广东实付金额为 100.00。",
            evidence_refs=[CellReference(row_index=0, column_index=2)],
        ),
        error=answer_error,
    )
    orchestrator = ConversationOrchestrator(
        dialogue=dialogue,
        unit_of_work=uow,
        runs=runs,
        retriever=retriever,
        planner=planner,
        catalog=_catalog(),
        retrieval_index_fingerprint="4" * 64,
        admission=admission,
        query_runtime=runtime,
        verifier=verifier or DeterministicVerifier(),
        repair=repair,
        synthesizer=AnswerSynthesizer(chat_model=answer_model),
        clock=lambda: NOW,
        id_factory=id_factory,
    )
    return orchestrator, retriever, planner, repair_model, answer_model, runs, uow


def test_happy_path_composes_m8_m14_and_atomically_completes() -> None:
    orchestrator, retriever, planner, repair_model, answer_model, runs, uow = _orchestrator()

    response = asyncio.run(
        orchestrator.process_message(session_id="session-m14", content="最近支付金额")
    )

    assert isinstance(response, ResultResponse)
    assert response.data.rows[0][2] == "100.00"
    assert runs.run.status is RunStatus.COMPLETED
    assert uow.completion_count == 1
    assert [value.message.role.value for value in uow.messages] == ["user", "assistant"]
    assert retriever.calls == 1
    assert planner.calls == 1
    assert repair_model.calls == []
    assert len(answer_model.calls) == 1


def test_clarification_short_circuits_every_downstream_service() -> None:
    orchestrator, retriever, planner, repair_model, answer_model, runs, uow = _orchestrator(
        action=DialogueAction.ASK_CLARIFICATION
    )

    response = asyncio.run(
        orchestrator.process_message(session_id="session-m14", content="看看销售")
    )

    assert isinstance(response, ClarificationResponse)
    assert runs.run.status is RunStatus.CLARIFYING
    assert retriever.calls == 0
    assert planner.calls == 0
    assert repair_model.calls == []
    assert answer_model.calls == []
    assert [value.message.role.value for value in uow.messages] == ["user", "assistant"]


def test_multi_turn_clarification_uses_a_new_run_then_completes() -> None:
    orchestrator, retriever, planner, _, answer_model, runs, uow = _orchestrator(
        actions=(DialogueAction.ASK_CLARIFICATION, DialogueAction.READY)
    )

    first = asyncio.run(orchestrator.process_message(session_id="session-m14", content="看看销售"))
    second = asyncio.run(
        orchestrator.process_message(session_id="session-m14", content="使用实付金额")
    )

    assert isinstance(first, ClarificationResponse)
    assert isinstance(second, ResultResponse)
    assert first.run_id != second.run_id
    assert runs.run.status is RunStatus.COMPLETED
    assert retriever.calls == 1
    assert planner.calls == 1
    assert len(answer_model.calls) == 1
    assert [value.message.role.value for value in uow.messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]


def test_policy_denial_is_typed_and_never_calls_answer_model() -> None:
    original = evidence_bundle().planning_trace
    denied = replace(original, plan=valid_plan(sql="DELETE FROM fact_order"))
    orchestrator, _, _, repair_model, answer_model, runs, _ = _orchestrator(planning_trace=denied)

    response = asyncio.run(
        orchestrator.process_message(session_id="session-m14", content="删除订单")
    )

    assert isinstance(response, FailureResponse)
    assert response.status is RunStatus.POLICY_DENIED
    assert runs.run.status is RunStatus.POLICY_DENIED
    assert repair_model.calls == []
    assert answer_model.calls == []


class _AlwaysFailedVerifier(DeterministicVerifier):
    def verify(self, context: object):  # type: ignore[no-untyped-def]
        from data_agent.contracts.execution import ExecutionResult
        from data_agent.verification.context import (
            VerificationContext,
            build_verification_context,
        )
        from tests.verification.factories import evidence_bundle

        assert isinstance(context, VerificationContext)
        wrong = ExecutionResult(
            version="v0.1",
            columns=["wrong"],
            rows=[],
            returned_row_count=0,
            duration_ms=1,
            truncated=False,
        )
        bundle = evidence_bundle(result=wrong)
        return super().verify(
            build_verification_context(
                planning_trace=bundle.planning_trace,
                guarded_query=bundle.guarded_query,
                execution_metadata=bundle.execution_metadata,
                execution_result=bundle.execution_result,
            )
        )


def test_failed_verification_routes_to_new_repaired_branch_before_answer() -> None:
    orchestrator, _, _, repair_model, answer_model, runs, _ = _orchestrator(
        verifier=_AlwaysFailedVerifier()
    )

    response = asyncio.run(
        orchestrator.process_message(session_id="session-m14", content="最近支付金额")
    )

    assert isinstance(response, ResultResponse)
    assert runs.run.status is RunStatus.COMPLETED
    assert runs.run.repair_count == 1
    assert len(repair_model.calls) == 1
    assert len(answer_model.calls) == 1


def test_terminal_failed_repair_makes_zero_answer_calls() -> None:
    orchestrator, _, _, repair_model, answer_model, runs, _ = _orchestrator(
        verifier=_AlwaysFailedVerifier(), repair_error=RuntimeError("provider envelope")
    )

    response = asyncio.run(
        orchestrator.process_message(session_id="session-m14", content="最近支付金额")
    )

    assert isinstance(response, FailureResponse)
    assert response.status is RunStatus.REPAIR_EXHAUSTED
    assert runs.run.status is RunStatus.REPAIR_EXHAUSTED
    assert len(repair_model.calls) == 1
    assert answer_model.calls == []


def test_synthesis_failure_is_typed_and_does_not_persist_final_message() -> None:
    orchestrator, _, _, _, answer_model, runs, uow = _orchestrator(
        answer_error=RuntimeError("raw provider envelope")
    )

    response = asyncio.run(
        orchestrator.process_message(session_id="session-m14", content="最近支付金额")
    )

    assert isinstance(response, FailureResponse)
    assert response.code == "SYNTHESIS_FAILED"
    assert "provider" not in response.message
    assert runs.run.status is RunStatus.FAILED
    assert len(answer_model.calls) == 1
    assert [value.message.role.value for value in uow.messages] == ["user"]
