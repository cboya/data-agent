"""Typed adapters from M10-M12 failure evidence into the M13 envelope."""

from __future__ import annotations

from data_agent.planning.service import PlanningTrace
from data_agent.query_runtime.errors import (
    CapabilityIntegrityError,
    DatabaseExecutionError,
    DatabaseUnavailableError,
    QueryTimeoutError,
    ResultDecodingError,
    RuntimeExecutionError,
)
from data_agent.repair.evidence import RepairCategory, RepairFailure, RepairStage
from data_agent.sql_guard.capability import GuardedQuery, query_plan_fingerprint
from data_agent.sql_guard.service import SQLAdmissionOutcome
from data_agent.verification.evidence import VerificationTrace


def _identities(trace: PlanningTrace) -> tuple[str, str]:
    return query_plan_fingerprint(trace.plan), trace.planner_context_fingerprint


def failure_from_admission(
    trace: PlanningTrace,
    outcome: SQLAdmissionOutcome,
    *,
    source_run_id: str,
) -> RepairFailure:
    plan_identity, context_identity = _identities(trace)
    if outcome.guard.candidate is None:
        code = str(outcome.guard.result.violations[0]).split(":", maxsplit=1)[0]
        category = (
            RepairCategory.FORMULATION if code == "SQL_PARSE_ERROR" else RepairCategory.POLICY
        )
        return RepairFailure(
            source_run_id=source_run_id,
            stage=RepairStage.SQL_GUARD,
            category=category,
            code=code,
            query_plan_fingerprint=plan_identity,
            planner_context_fingerprint=context_identity,
        )
    if outcome.explain_result is None or outcome.explain_result.accepted:
        raise ValueError("admission outcome is not a repair failure")
    error = outcome.provider_error
    if error is not None:
        category = (
            RepairCategory.FORMULATION
            if error.provider_errno in {1052, 1054}
            else RepairCategory.AVAILABILITY
        )
        return RepairFailure(
            source_run_id=source_run_id,
            stage=RepairStage.EXPLAIN,
            category=category,
            code="EXPLAIN_PROVIDER_ERROR",
            provider_errno=error.provider_errno,
            provider_sqlstate=error.provider_sqlstate,
            detail=error.safe_detail,
            query_plan_fingerprint=plan_identity,
            planner_context_fingerprint=context_identity,
        )
    reason = str(outcome.explain_result.rejection_reason)
    category = (
        RepairCategory.COST if reason == "ROW_ESTIMATE_LIMIT_EXCEEDED" else RepairCategory.POLICY
    )
    return RepairFailure(
        source_run_id=source_run_id,
        stage=RepairStage.EXPLAIN,
        category=category,
        code=reason,
        query_plan_fingerprint=plan_identity,
        planner_context_fingerprint=context_identity,
    )


def failure_from_runtime(
    trace: PlanningTrace,
    query: GuardedQuery,
    error: RuntimeExecutionError,
    *,
    source_run_id: str,
) -> RepairFailure:
    plan_identity, context_identity = _identities(trace)
    if isinstance(error, CapabilityIntegrityError):
        category = RepairCategory.CAPABILITY
    elif isinstance(error, QueryTimeoutError):
        category = RepairCategory.TIMEOUT
    elif isinstance(error, DatabaseUnavailableError):
        category = RepairCategory.AVAILABILITY
    elif isinstance(error, ResultDecodingError):
        category = RepairCategory.RESULT
    elif isinstance(error, DatabaseExecutionError) and error.provider_errno in {1052, 1054}:
        category = RepairCategory.FORMULATION
    else:
        category = RepairCategory.RESULT
    return RepairFailure(
        source_run_id=source_run_id,
        stage=RepairStage.RUNTIME,
        category=category,
        code=error.code,
        provider_errno=error.provider_errno,
        provider_sqlstate=error.provider_sqlstate,
        detail=error.safe_detail,
        guarded_query_fingerprint=query.capability_fingerprint,
        query_plan_fingerprint=plan_identity,
        planner_context_fingerprint=context_identity,
    )


def failure_from_verification(
    trace: PlanningTrace,
    query: GuardedQuery,
    verification: VerificationTrace,
    *,
    source_run_id: str,
) -> RepairFailure:
    plan_identity, context_identity = _identities(trace)
    failed = tuple(str(check.name) for check in verification.result.checks if not check.passed)
    if not failed:
        raise ValueError("passed verification is not a repair failure")
    if "result_not_truncated" in failed:
        category = RepairCategory.TRUNCATION
        code = "RESULT_TRUNCATED"
    else:
        category = RepairCategory.FORMULATION
        code = "VERIFICATION_CHECK_FAILED"
    return RepairFailure(
        source_run_id=source_run_id,
        stage=RepairStage.VERIFICATION,
        category=category,
        code=code,
        guarded_query_fingerprint=query.capability_fingerprint,
        execution_id=str(verification.evidence.execution_id),
        failed_checks=failed,
        query_plan_fingerprint=plan_identity,
        planner_context_fingerprint=context_identity,
    )


def failure_from_coverage(
    trace: PlanningTrace,
    query: GuardedQuery,
    verification: VerificationTrace,
    *,
    source_run_id: str,
) -> RepairFailure:
    plan_identity, context_identity = _identities(trace)
    gaps = tuple(str(gap.name) for gap in verification.coverage_gaps)
    if not gaps:
        raise ValueError("verification has no coverage gap")
    return RepairFailure(
        source_run_id=source_run_id,
        stage=RepairStage.VERIFICATION,
        category=RepairCategory.COVERAGE,
        code="VERIFICATION_COVERAGE_GAP",
        guarded_query_fingerprint=query.capability_fingerprint,
        execution_id=str(verification.evidence.execution_id),
        coverage_gaps=gaps,
        query_plan_fingerprint=plan_identity,
        planner_context_fingerprint=context_identity,
    )


def failure_from_verification_integrity(
    trace: PlanningTrace,
    *,
    source_run_id: str,
    code: str = "VERIFICATION_INTEGRITY_ERROR",
) -> RepairFailure:
    plan_identity, context_identity = _identities(trace)
    return RepairFailure(
        source_run_id=source_run_id,
        stage=RepairStage.VERIFICATION,
        category=RepairCategory.INTEGRITY,
        code=code,
        query_plan_fingerprint=plan_identity,
        planner_context_fingerprint=context_identity,
    )
