"""M10-M12 typed failure adapters preserve authority without text classification."""

from typing import cast

from data_agent.query_runtime.errors import DatabaseExecutionError, QueryTimeoutError
from data_agent.repair.evidence import RepairCategory, RepairStage
from data_agent.repair.failures import (
    failure_from_admission,
    failure_from_coverage,
    failure_from_runtime,
)
from data_agent.sql_guard.capability import GuardedSQL
from data_agent.sql_guard.errors import ExplainProviderError
from data_agent.sql_guard.explain import ExplainPlanProvider, ExplainPolicy
from data_agent.sql_guard.guard import SQLGuard
from data_agent.sql_guard.service import SQLAdmissionService
from data_agent.verification.context import build_verification_context
from data_agent.verification.service import DeterministicVerifier
from tests.repair.factories import StaticExplainProvider, original_trace
from tests.verification.factories import evidence_bundle, valid_plan


class UnknownColumnProvider:
    def explain(self, candidate: GuardedSQL) -> str:
        del candidate
        raise ExplainProviderError(
            "provider failed",
            provider_errno=1054,
            provider_sqlstate="42S22",
            safe_detail="unknown column",
        )


def _admission(provider: object) -> SQLAdmissionService:
    return SQLAdmissionService(
        guard=SQLGuard(analytics_schema="data_agent"),
        explain_provider=cast(ExplainPlanProvider, provider),
        explain_policy=ExplainPolicy(max_estimated_rows_per_access=100),
    )


def test_guard_parse_and_explain_errno_are_distinct_typed_failures() -> None:
    syntax_trace = original_trace(valid_plan(sql="SELECT ( FROM fact_order"))
    syntax_outcome = _admission(StaticExplainProvider()).admit(
        syntax_trace.plan,
        planner_context_fingerprint=syntax_trace.planner_context_fingerprint,
    )
    syntax = failure_from_admission(syntax_trace, syntax_outcome)

    unknown_trace = original_trace()
    unknown_outcome = _admission(UnknownColumnProvider()).admit(
        unknown_trace.plan,
        planner_context_fingerprint=unknown_trace.planner_context_fingerprint,
    )
    unknown = failure_from_admission(unknown_trace, unknown_outcome)

    assert (syntax.stage, syntax.category, syntax.code) == (
        RepairStage.SQL_GUARD,
        RepairCategory.FORMULATION,
        "SQL_PARSE_ERROR",
    )
    assert (unknown.stage, unknown.category, unknown.provider_errno) == (
        RepairStage.EXPLAIN,
        RepairCategory.FORMULATION,
        1054,
    )
    assert unknown.provider_sqlstate == "42S22"


def test_runtime_eligibility_uses_errno_while_timeout_stays_terminal() -> None:
    bundle = evidence_bundle()
    unknown = failure_from_runtime(
        bundle.planning_trace,
        bundle.guarded_query,
        DatabaseExecutionError(
            "execution rejected",
            provider_errno=1052,
            safe_detail="ambiguous column",
        ),
    )
    timeout = failure_from_runtime(
        bundle.planning_trace,
        bundle.guarded_query,
        QueryTimeoutError("timed out", provider_errno=3024),
    )

    assert unknown.category is RepairCategory.FORMULATION
    assert unknown.provider_errno == 1052
    assert timeout.category is RepairCategory.TIMEOUT
    assert timeout.provider_errno == 3024


def test_verification_coverage_is_typed_non_trigger_evidence() -> None:
    bundle = evidence_bundle()
    verification = DeterministicVerifier().verify(
        build_verification_context(
            planning_trace=bundle.planning_trace,
            guarded_query=bundle.guarded_query,
            execution_metadata=bundle.execution_metadata,
            execution_result=bundle.execution_result,
        )
    )

    failure = failure_from_coverage(
        bundle.planning_trace,
        bundle.guarded_query,
        verification,
    )

    assert failure.category is RepairCategory.COVERAGE
    assert "time_range_semantics" in failure.coverage_gaps
