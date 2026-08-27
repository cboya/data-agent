"""Bounded M13 orchestration and full replacement evidence chain."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from data_agent.contracts.execution import ExecutionResult
from data_agent.contracts.run import RunStatus
from data_agent.repair.errors import RepairIntegrityError
from data_agent.repair.evidence import (
    RepairCategory,
    RepairFailure,
    RepairOutcomeKind,
    RepairStage,
)
from data_agent.repair.failures import failure_from_verification
from data_agent.repair.prompt import QUERY_REPAIR_PROMPT_VERSION
from data_agent.repair.service import BoundedRepairService, RepairPipelineOutcome
from data_agent.sql_guard.capability import query_plan_fingerprint
from data_agent.sql_guard.explain import ExplainPolicy
from data_agent.sql_guard.guard import SQLGuard
from data_agent.sql_guard.service import SQLAdmissionService
from data_agent.verification.context import build_verification_context
from data_agent.verification.service import DeterministicVerifier
from tests.repair.factories import (
    CoherentRuntime,
    FixedRepairModel,
    MemoryRunRepository,
    StaticExplainProvider,
    original_trace,
)
from tests.verification.factories import evidence_bundle, valid_plan

NOW = datetime(2026, 8, 26, 12, tzinfo=UTC)


def repair_failure(
    trace: object,
    *,
    source_run_id: str = "m13_run",
    stage: RepairStage = RepairStage.SQL_GUARD,
    category: RepairCategory = RepairCategory.FORMULATION,
    code: str = "SQL_PARSE_ERROR",
    provider_errno: int | None = None,
    failed_checks: tuple[str, ...] = (),
) -> RepairFailure:
    from data_agent.planning.service import PlanningTrace

    assert isinstance(trace, PlanningTrace)
    return RepairFailure(
        source_run_id=source_run_id,
        stage=stage,
        category=category,
        code=code,
        provider_errno=provider_errno,
        failed_checks=failed_checks,
        query_plan_fingerprint=query_plan_fingerprint(trace.plan),
        planner_context_fingerprint=trace.planner_context_fingerprint,
    )


def service(
    *,
    model: FixedRepairModel,
    runs: MemoryRunRepository,
    max_attempts: int = 1,
) -> BoundedRepairService:
    return BoundedRepairService(
        chat_model=model,
        run_repository=runs,
        admission=SQLAdmissionService(
            guard=SQLGuard(analytics_schema="data_agent"),
            explain_provider=StaticExplainProvider(),
            explain_policy=ExplainPolicy(max_estimated_rows_per_access=100),
        ),
        query_runtime=CoherentRuntime(),
        max_attempts=max_attempts,
        model_fingerprint="5" * 64,
        runtime_version="test-runtime",
    )


def run_repair(
    repairer: BoundedRepairService,
    *,
    runs: MemoryRunRepository,
    original: object,
    failure: RepairFailure,
    run_id: str | None = None,
) -> RepairPipelineOutcome:
    from data_agent.planning.service import PlanningTrace

    assert isinstance(original, PlanningTrace)
    return asyncio.run(
        repairer.repair(
            run_id=run_id or runs.run.id,
            original=original,
            failure=failure,
            occurred_at=NOW,
        )
    )


def test_syntax_repair_creates_a_new_full_m9_m12_branch() -> None:
    original = original_trace(valid_plan(sql="SELECT FROM"))
    failure = repair_failure(original)
    model = FixedRepairModel(valid_plan())
    runs = MemoryRunRepository()

    outcome = run_repair(
        service(model=model, runs=runs),
        runs=runs,
        original=original,
        failure=failure,
    )

    assert outcome.trace.outcome is RepairOutcomeKind.SUCCEEDED
    assert outcome.trace.source_run_id == runs.run.id
    assert outcome.trace.attempt == 1
    assert outcome.run.status is RunStatus.SYNTHESIZING
    assert outcome.run.repair_count == 1
    assert outcome.replacement_planning_trace is not None
    assert outcome.replacement_planning_trace.context is original.context
    assert outcome.replacement_planning_trace.prompt_version == QUERY_REPAIR_PROMPT_VERSION
    assert (
        outcome.replacement_planning_trace.planner_context_fingerprint
        == original.planner_context_fingerprint
    )
    assert (
        outcome.trace.original_query_plan_fingerprint
        != outcome.trace.replacement_query_plan_fingerprint
    )
    assert outcome.guarded_query is not None
    assert outcome.execution_metadata is not None
    assert outcome.verification_trace is not None
    assert outcome.verification_trace.result.status == "PASSED"
    assert outcome.trace.final_verification_evidence == outcome.verification_trace.evidence
    assert len(model.calls) == 1


def test_selected_m12_formulation_failure_can_repair_to_pass() -> None:
    wrong_result = ExecutionResult(
        version="v0.1",
        columns=["period", "province", "wrong_alias"],
        rows=[],
        returned_row_count=0,
        duration_ms=1,
        truncated=False,
    )
    bundle = evidence_bundle(result=wrong_result)
    verification = DeterministicVerifier().verify(
        build_verification_context(
            planning_trace=bundle.planning_trace,
            guarded_query=bundle.guarded_query,
            execution_metadata=bundle.execution_metadata,
            execution_result=bundle.execution_result,
        )
    )
    failure = failure_from_verification(
        bundle.planning_trace,
        bundle.guarded_query,
        verification,
        source_run_id="m13_run",
    )
    model = FixedRepairModel(valid_plan())
    runs = MemoryRunRepository(status=RunStatus.VERIFYING)

    outcome = run_repair(
        service(model=model, runs=runs),
        runs=runs,
        original=bundle.planning_trace,
        failure=failure,
    )

    assert failure.failed_checks
    assert outcome.trace.outcome is RepairOutcomeKind.SUCCEEDED
    assert outcome.verification_trace is not None
    assert outcome.verification_trace.result.status == "PASSED"


def test_policy_failure_is_terminal_with_zero_model_calls_and_zero_claims() -> None:
    original = original_trace()
    failure = repair_failure(
        original,
        category=RepairCategory.POLICY,
        code="UNAUTHORIZED_SCHEMA",
    )
    model = FixedRepairModel()
    runs = MemoryRunRepository()

    outcome = run_repair(
        service(model=model, runs=runs),
        runs=runs,
        original=original,
        failure=failure,
    )

    assert outcome.trace.outcome is RepairOutcomeKind.NOT_ELIGIBLE
    assert outcome.run.status is RunStatus.POLICY_DENIED
    assert outcome.run.repair_count == 0
    assert runs.claim_count == 0
    assert model.calls == []


def test_dimension_authority_ambiguity_consumes_no_repair_attempt() -> None:
    original = original_trace()
    failure = repair_failure(
        original,
        stage=RepairStage.VERIFICATION,
        category=RepairCategory.FORMULATION,
        code="VERIFICATION_CHECK_FAILED",
        failed_checks=("requested_dimension_source_unique",),
    )
    model = FixedRepairModel()
    runs = MemoryRunRepository(status=RunStatus.VERIFYING)

    outcome = run_repair(
        service(model=model, runs=runs),
        runs=runs,
        original=original,
        failure=failure,
    )

    assert outcome.trace.outcome is RepairOutcomeKind.NOT_ELIGIBLE
    assert outcome.run.status is RunStatus.FAILED
    assert outcome.run.repair_count == 0
    assert runs.claim_count == 0
    assert model.calls == []


def test_coverage_gap_is_not_a_trigger_and_does_not_terminalize_run() -> None:
    original = original_trace()
    failure = RepairFailure(
        source_run_id="m13_run",
        stage=RepairStage.VERIFICATION,
        category=RepairCategory.COVERAGE,
        code="VERIFICATION_COVERAGE_GAP",
        coverage_gaps=("time_range_semantics",),
        query_plan_fingerprint=query_plan_fingerprint(original.plan),
        planner_context_fingerprint=original.planner_context_fingerprint,
    )
    model = FixedRepairModel()
    runs = MemoryRunRepository(status=RunStatus.VERIFYING)

    outcome = run_repair(
        service(model=model, runs=runs),
        runs=runs,
        original=original,
        failure=failure,
    )

    assert outcome.trace.outcome is RepairOutcomeKind.NOT_ELIGIBLE
    assert outcome.run.status is RunStatus.VERIFYING
    assert outcome.run.repair_count == 0
    assert model.calls == []


def test_model_failure_consumes_attempt_and_terminates_repair_exhausted() -> None:
    original = original_trace()
    failure = repair_failure(original)
    model = FixedRepairModel(error=RuntimeError("provider failed"))
    runs = MemoryRunRepository()

    outcome = run_repair(
        service(model=model, runs=runs),
        runs=runs,
        original=original,
        failure=failure,
    )

    assert outcome.trace.outcome is RepairOutcomeKind.MODEL_FAILED
    assert outcome.run.status is RunStatus.REPAIR_EXHAUSTED
    assert outcome.run.repair_count == 1
    assert runs.claim_count == 1
    assert len(model.calls) == 1


def test_replacement_plan_cannot_expand_original_table_authority() -> None:
    original = original_trace()
    failure = repair_failure(original)
    escaped = valid_plan().model_copy(update={"tables": ["secret_table"]})
    model = FixedRepairModel(escaped)
    runs = MemoryRunRepository()

    outcome = run_repair(
        service(model=model, runs=runs),
        runs=runs,
        original=original,
        failure=failure,
    )

    assert outcome.trace.outcome is RepairOutcomeKind.POLICY_FAILED
    assert outcome.run.status is RunStatus.REPAIR_EXHAUSTED
    assert outcome.trace.replacement_query_plan_fingerprint == query_plan_fingerprint(escaped)


def test_concurrent_callers_share_one_model_call_and_cannot_exceed_bound() -> None:
    original = original_trace(valid_plan(sql="SELECT FROM"))
    failure = repair_failure(original)
    model = FixedRepairModel(valid_plan())
    runs = MemoryRunRepository()
    repairer = service(model=model, runs=runs)

    async def run_concurrently() -> tuple[RepairPipelineOutcome, RepairPipelineOutcome]:
        return await asyncio.gather(
            repairer.repair(
                run_id=runs.run.id,
                original=original,
                failure=failure,
                occurred_at=NOW,
            ),
            repairer.repair(
                run_id=runs.run.id,
                original=original,
                failure=failure,
                occurred_at=NOW,
            ),
        )

    first, second = asyncio.run(run_concurrently())

    assert {first.trace.outcome, second.trace.outcome} == {
        RepairOutcomeKind.SUCCEEDED,
        RepairOutcomeKind.EXHAUSTED,
    }
    assert runs.run.repair_count == 1
    assert runs.claim_count == 1
    assert len(model.calls) == 1


def test_concurrent_service_instances_cannot_terminalize_an_in_flight_claim() -> None:
    original = original_trace(valid_plan(sql="SELECT FROM"))
    failure = repair_failure(original)
    runs = MemoryRunRepository()

    async def run_concurrently() -> tuple[RepairPipelineOutcome, RepairPipelineOutcome]:
        started = asyncio.Event()
        release = asyncio.Event()
        owner_model = FixedRepairModel(valid_plan(), started=started, release=release)
        competing_model = FixedRepairModel(valid_plan())
        owner = service(model=owner_model, runs=runs)
        competitor = service(model=competing_model, runs=runs)
        owner_task = asyncio.create_task(
            owner.repair(
                run_id=runs.run.id,
                original=original,
                failure=failure,
                occurred_at=NOW,
            )
        )
        await started.wait()
        competing_outcome = await competitor.repair(
            run_id=runs.run.id,
            original=original,
            failure=failure,
            occurred_at=NOW,
        )
        assert competing_outcome.trace.outcome is RepairOutcomeKind.EXHAUSTED
        assert runs.run.status is RunStatus.VALIDATING
        assert competing_model.calls == []
        release.set()
        return await owner_task, competing_outcome

    owner_outcome, competing_outcome = asyncio.run(run_concurrently())

    assert owner_outcome.trace.outcome is RepairOutcomeKind.SUCCEEDED
    assert competing_outcome.trace.outcome is RepairOutcomeKind.EXHAUSTED
    assert runs.run.status is RunStatus.SYNTHESIZING
    assert runs.run.repair_count == 1


def test_exhausted_zero_budget_makes_no_model_call() -> None:
    original = original_trace()
    failure = repair_failure(original)
    model = FixedRepairModel()
    runs = MemoryRunRepository()

    outcome = run_repair(
        service(model=model, runs=runs, max_attempts=0),
        runs=runs,
        original=original,
        failure=failure,
    )

    assert outcome.trace.outcome is RepairOutcomeKind.EXHAUSTED
    assert outcome.run.status is RunStatus.REPAIR_EXHAUSTED
    assert outcome.run.repair_count == 0
    assert model.calls == []


def test_failure_identity_mismatch_is_rejected_before_repository_or_model() -> None:
    original = original_trace()
    failure = repair_failure(original).model_copy(update={"planner_context_fingerprint": "a" * 64})
    model = FixedRepairModel()
    runs = MemoryRunRepository()

    with pytest.raises(RepairIntegrityError):
        run_repair(
            service(model=model, runs=runs),
            runs=runs,
            original=original,
            failure=failure,
        )

    assert runs.claim_count == 0
    assert model.calls == []


def test_cross_run_replay_is_rejected_before_repository_or_model() -> None:
    original = original_trace()
    failure = repair_failure(original, source_run_id="run_a")
    model = FixedRepairModel()
    runs = MemoryRunRepository(run_id="run_b")

    with pytest.raises(RepairIntegrityError, match="source Run"):
        run_repair(
            service(model=model, runs=runs),
            runs=runs,
            run_id="run_b",
            original=original,
            failure=failure,
        )

    assert runs.run.repair_count == 0
    assert runs.claim_count == 0
    assert model.calls == []


@pytest.mark.parametrize(
    ("stage", "run_status", "code", "provider_errno", "failed_checks"),
    [
        (RepairStage.SQL_GUARD, RunStatus.VERIFYING, "SQL_PARSE_ERROR", None, ()),
        (RepairStage.EXPLAIN, RunStatus.EXECUTING, "EXPLAIN_PROVIDER_ERROR", 1054, ()),
        (RepairStage.RUNTIME, RunStatus.VALIDATING, "DATABASE_EXECUTION_ERROR", 1054, ()),
        (
            RepairStage.VERIFICATION,
            RunStatus.EXECUTING,
            "VERIFICATION_CHECK_FAILED",
            None,
            ("actual_columns_match_expected",),
        ),
    ],
)
def test_failure_stage_mismatch_is_rejected_by_atomic_claim(
    stage: RepairStage,
    run_status: RunStatus,
    code: str,
    provider_errno: int | None,
    failed_checks: tuple[str, ...],
) -> None:
    original = original_trace()
    failure = repair_failure(
        original,
        stage=stage,
        code=code,
        provider_errno=provider_errno,
        failed_checks=failed_checks,
    )
    model = FixedRepairModel()
    runs = MemoryRunRepository(status=run_status)

    with pytest.raises(RepairIntegrityError, match="lifecycle state"):
        run_repair(
            service(model=model, runs=runs),
            runs=runs,
            original=original,
            failure=failure,
        )

    assert runs.run.status is run_status
    assert runs.run.repair_count == 0
    assert runs.claim_count == 0
    assert model.calls == []
