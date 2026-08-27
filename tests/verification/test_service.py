"""Invariant-focused M12 structural, semantic, and empirical checks."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from data_agent.contracts.execution import ExecutionResult
from data_agent.contracts.query import ExpectedColumn, QueryPlan
from data_agent.contracts.requirement import (
    DimensionRequirement,
    MetricRequirement,
    RequirementState,
    RequirementStatus,
    ResolutionStatus,
)
from data_agent.query_runtime.evidence import execution_result_fingerprint
from data_agent.verification import (
    CoverageDisposition,
    DeterministicVerifier,
    build_verification_context,
)
from data_agent.verification.evidence import VerificationTrace
from tests.verification.factories import VALID_SQL, EvidenceBundle, evidence_bundle, valid_plan


def _verify(bundle: EvidenceBundle) -> VerificationTrace:
    context = build_verification_context(
        planning_trace=bundle.planning_trace,
        guarded_query=bundle.guarded_query,
        execution_metadata=bundle.execution_metadata,
        execution_result=bundle.execution_result,
    )
    return DeterministicVerifier().verify(context)


def _failed(trace: VerificationTrace, name: str) -> bool:
    return any(check.name == name and not check.passed for check in trace.result.checks)


def test_valid_evidence_passes_with_honest_coverage_gaps() -> None:
    trace = _verify(evidence_bundle())

    assert trace.result.status == "PASSED"
    assert all(check.passed for check in trace.result.checks)
    gaps = {gap.name: gap.disposition for gap in trace.coverage_gaps}
    assert gaps["time_range_semantics"] is CoverageDisposition.UNSUPPORTED
    assert gaps["metric_formula_semantics"] is CoverageDisposition.UNSUPPORTED
    assert not any(check.name in gaps for check in trace.result.checks)


def test_empty_coherent_result_is_not_rejected() -> None:
    result = ExecutionResult(
        version="v0.1",
        columns=["period", "province", "paid_amount"],
        rows=[],
        returned_row_count=0,
        duration_ms=1,
        truncated=False,
    )

    assert _verify(evidence_bundle(result=result)).result.status == "PASSED"


def test_truncation_and_exact_column_order_fail_structural_verification() -> None:
    truncated = ExecutionResult(
        version="v0.1",
        columns=["period", "province", "paid_amount"],
        rows=[[date(2026, 8, 1), "广东", Decimal("100.00")]],
        returned_row_count=1,
        duration_ms=1,
        truncated=True,
    )
    truncated_trace = _verify(evidence_bundle(result=truncated))
    assert _failed(truncated_trace, "result_not_truncated")

    wrong_order = ExecutionResult(
        version="v0.1",
        columns=["province", "period", "paid_amount"],
        rows=[["广东", date(2026, 8, 1), Decimal("100.00")]],
        returned_row_count=1,
        duration_ms=1,
        truncated=False,
    )
    wrong_order_trace = _verify(evidence_bundle(result=wrong_order))
    assert _failed(wrong_order_trace, "actual_columns_match_expected")


def test_metadata_count_fact_mismatch_is_structural_not_integrity() -> None:
    bundle = evidence_bundle(metadata_overrides={"returned_row_count": 999})

    trace = _verify(bundle)

    assert _failed(trace, "metadata_row_count_consistent")


def test_missing_metric_dimension_and_period_fail_semantic_verification() -> None:
    plan = valid_plan().model_copy(
        update={
            "expected_columns": [ExpectedColumn(name="other")],
        }
    )
    result = ExecutionResult(
        version="v0.1",
        columns=["other"],
        rows=[[1]],
        returned_row_count=1,
        duration_ms=1,
        truncated=False,
    )

    trace = _verify(evidence_bundle(plan=plan, result=result))

    assert _failed(trace, "required_metrics_present")
    assert _failed(trace, "required_dimensions_present")
    assert _failed(trace, "grain_period_present")


def test_requirement_state_rejects_plan_self_authorized_extra_public_grain() -> None:
    requirement = RequirementState(
        version="v0.1",
        metrics=[
            MetricRequirement(
                term="paid amount",
                resolved_name="paid_amount",
                status=ResolutionStatus.CONFIRMED,
            )
        ],
        status=RequirementStatus.READY,
    )
    plan = QueryPlan(
        version="v0.1",
        intent="Wrong daily paid amount",
        tables=["fact_order"],
        sql=(
            "SELECT DATE(paid_at) AS period, SUM(paid_amount) AS paid_amount "
            "FROM fact_order GROUP BY DATE(paid_at)"
        ),
        expected_columns=[ExpectedColumn(name="period"), ExpectedColumn(name="paid_amount")],
    )
    result = ExecutionResult(
        version="v0.1",
        columns=["period", "paid_amount"],
        rows=[[date(2026, 8, 1), Decimal("100.00")]],
        returned_row_count=1,
        duration_ms=1,
        truncated=False,
    )

    trace = _verify(
        evidence_bundle(
            requirement=requirement,
            plan=plan,
            result=result,
            documents=(evidence_bundle().planning_trace.context.documents[0],),
            relationships=(),
        )
    )

    assert _failed(trace, "governed_public_output_shape")
    assert _failed(trace, "unrequested_analytical_grain")


def test_unprovable_requested_dimension_fails_nonrepairable_source_authority() -> None:
    requirement = RequirementState(
        version="v0.1",
        metrics=[
            MetricRequirement(
                term="paid amount",
                resolved_name="paid_amount",
                status=ResolutionStatus.CONFIRMED,
            )
        ],
        dimensions=[
            DimensionRequirement(
                term="region",
                resolved_name="region",
                status=ResolutionStatus.CONFIRMED,
            )
        ],
        status=RequirementStatus.READY,
    )
    plan = QueryPlan(
        version="v0.1",
        intent="Paid amount by generic region",
        tables=["fact_order", "dim_user", "dim_region"],
        sql=(
            "SELECT r.province AS region, SUM(o.paid_amount) AS paid_amount "
            "FROM fact_order AS o JOIN dim_user AS u ON o.user_id = u.id "
            "JOIN dim_region AS r ON u.region_id = r.id GROUP BY r.province"
        ),
        expected_columns=[ExpectedColumn(name="region"), ExpectedColumn(name="paid_amount")],
    )
    result = ExecutionResult(
        version="v0.1",
        columns=["region", "paid_amount"],
        rows=[["广东", Decimal("180.00")]],
        returned_row_count=1,
        duration_ms=1,
        truncated=False,
    )

    trace = _verify(evidence_bundle(requirement=requirement, plan=plan, result=result))

    assert not _failed(trace, "governed_public_output_shape")
    assert _failed(trace, "requested_dimension_source_unique")
    assert not any(
        check.name == "requested_dimension_projection_lineage" for check in trace.result.checks
    )
    assert not _failed(trace, "unrequested_analytical_grain")


def test_hidden_grouping_key_refines_requested_public_grain_and_fails() -> None:
    sql = VALID_SQL.replace(
        "GROUP BY DATE(o.paid_at), r.province",
        "GROUP BY DATE(o.paid_at), r.province, o.user_id",
    )

    trace = _verify(evidence_bundle(plan=valid_plan(sql=sql)))

    assert trace.result.status == "FAILED"
    assert _failed(trace, "unrequested_analytical_grain")


@pytest.mark.parametrize(
    "group_by",
    ["period, r.province", "1, 2"],
)
def test_safe_grouping_alias_and_ordinals_remain_valid(group_by: str) -> None:
    sql = VALID_SQL.replace(
        "GROUP BY DATE(o.paid_at), r.province",
        f"GROUP BY {group_by}",
    )

    trace = _verify(evidence_bundle(plan=valid_plan(sql=sql)))

    assert trace.result.status == "PASSED"
    assert not _failed(trace, "unrequested_analytical_grain")


def test_grouping_alias_colliding_with_source_column_fails_closed() -> None:
    requirement = RequirementState(
        version="v0.1",
        metrics=[
            MetricRequirement(
                term="paid amount",
                resolved_name="paid_amount",
                status=ResolutionStatus.CONFIRMED,
            )
        ],
        dimensions=[
            DimensionRequirement(
                term="paid timestamp date",
                resolved_name="paid_at",
                status=ResolutionStatus.CONFIRMED,
            )
        ],
        status=RequirementStatus.READY,
    )
    plan = QueryPlan(
        version="v0.1",
        intent="Paid amount by paid timestamp date",
        tables=["fact_order"],
        sql=(
            "SELECT DATE(o.paid_at) AS paid_at, SUM(o.paid_amount) AS paid_amount "
            "FROM fact_order AS o GROUP BY paid_at"
        ),
        expected_columns=[
            ExpectedColumn(name="paid_at"),
            ExpectedColumn(name="paid_amount"),
        ],
    )
    result = ExecutionResult(
        version="v0.1",
        columns=["paid_at", "paid_amount"],
        rows=[[date(2026, 8, 1), Decimal("100.00")]],
        returned_row_count=1,
        duration_ms=1,
        truncated=False,
    )

    trace = _verify(
        evidence_bundle(
            requirement=requirement,
            plan=plan,
            result=result,
            documents=(evidence_bundle().planning_trace.context.documents[0],),
            relationships=(),
        )
    )

    assert not _failed(trace, "governed_public_output_shape")
    assert not _failed(trace, "requested_dimension_source_unique")
    assert not _failed(trace, "requested_dimension_projection_lineage")
    assert _failed(trace, "unrequested_analytical_grain")
    assert trace.result.status == "FAILED"


def test_unaliased_public_dimension_grouping_remains_valid() -> None:
    sql = VALID_SQL.replace("r.province AS province", "r.province")

    trace = _verify(evidence_bundle(plan=valid_plan(sql=sql)))

    assert trace.result.status == "PASSED"
    assert not _failed(trace, "unrequested_analytical_grain")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT SUM(paid_amount) AS paid_amount FROM fact_order GROUP BY user_id",
        (
            "WITH bounded AS (SELECT user_id, paid_amount FROM fact_order) "
            "SELECT SUM(paid_amount) AS paid_amount FROM bounded GROUP BY user_id"
        ),
    ],
)
def test_hidden_grouping_key_rejects_metric_only_false_global_aggregate(sql: str) -> None:
    requirement = RequirementState(
        version="v0.1",
        metrics=[
            MetricRequirement(
                term="paid amount",
                resolved_name="paid_amount",
                status=ResolutionStatus.CONFIRMED,
            )
        ],
        status=RequirementStatus.READY,
    )
    plan = QueryPlan(
        version="v0.1",
        intent="Paid amount incorrectly partitioned by channel",
        tables=["fact_order"],
        sql=sql,
        expected_columns=[ExpectedColumn(name="paid_amount")],
    )
    result = ExecutionResult(
        version="v0.1",
        columns=["paid_amount"],
        rows=[[Decimal("100.00")], [Decimal("200.00")]],
        returned_row_count=2,
        duration_ms=1,
        truncated=False,
    )

    trace = _verify(
        evidence_bundle(
            requirement=requirement,
            plan=plan,
            result=result,
            documents=(evidence_bundle().planning_trace.context.documents[0],),
            relationships=(),
        )
    )

    assert not _failed(trace, "governed_public_output_shape")
    assert _failed(trace, "unrequested_analytical_grain")
    assert trace.result.status == "FAILED"


def test_wrong_unique_metric_source_fails_semantic_verification() -> None:
    wrong_source_sql = VALID_SQL.replace("SUM(o.paid_amount)", "SUM(o.total_amount)")

    trace = _verify(evidence_bundle(plan=valid_plan(sql=wrong_source_sql)))

    assert _failed(trace, "metric_source:0:paid_amount")


def test_decoy_projection_cannot_authorize_wrong_metric_output_lineage() -> None:
    requirement = RequirementState(
        version="v0.1",
        goal="Paid amount",
        metrics=[
            MetricRequirement(
                term="paid amount",
                resolved_name="paid_amount",
                status=ResolutionStatus.CONFIRMED,
            )
        ],
        status=RequirementStatus.READY,
    )
    plan = QueryPlan(
        version="v0.1",
        intent="Decoy source",
        tables=["fact_order"],
        sql=(
            "SELECT paid_amount AS decoy, total_amount AS paid_amount FROM fact_order WHERE id = 1"
        ),
        expected_columns=[ExpectedColumn(name="decoy"), ExpectedColumn(name="paid_amount")],
    )
    result = ExecutionResult(
        version="v0.1",
        columns=["decoy", "paid_amount"],
        rows=[[Decimal("100.00"), Decimal("120.00")]],
        returned_row_count=1,
        duration_ms=1,
        truncated=False,
    )
    documents = (evidence_bundle().planning_trace.context.documents[0],)

    trace = _verify(
        evidence_bundle(
            requirement=requirement,
            plan=plan,
            result=result,
            documents=documents,
            relationships=(),
        )
    )

    assert _failed(trace, "metric_source:0:paid_amount")


def test_wrong_direct_join_edge_fails_semantic_verification() -> None:
    wrong_join_sql = VALID_SQL.replace("o.user_id = u.id", "o.id = u.id")

    trace = _verify(evidence_bundle(plan=valid_plan(sql=wrong_join_sql)))

    assert _failed(trace, "governed_relationship_joins")


def test_reversed_governed_join_equality_is_accepted() -> None:
    reversed_join_sql = VALID_SQL.replace("o.user_id = u.id", "u.id = o.user_id")

    trace = _verify(evidence_bundle(plan=valid_plan(sql=reversed_join_sql)))

    assert trace.result.status == "PASSED"


def test_transformed_join_columns_fail_as_unsupported_semantic_join() -> None:
    transformed_join_sql = VALID_SQL.replace(
        "o.user_id = u.id",
        "CAST(o.user_id AS CHAR) = u.id",
    )

    trace = _verify(evidence_bundle(plan=valid_plan(sql=transformed_join_sql)))

    assert _failed(trace, "governed_relationship_joins")


def test_complex_projection_lineage_is_a_gap_not_a_passed_check() -> None:
    requirement = RequirementState(
        version="v0.1",
        goal="Paid amount",
        metrics=[
            MetricRequirement(
                term="paid amount",
                resolved_name="paid_amount",
                status=ResolutionStatus.CONFIRMED,
            )
        ],
        status=RequirementStatus.READY,
    )
    plan = QueryPlan(
        version="v0.1",
        intent="Paid amount through a CTE",
        tables=["fact_order"],
        sql=(
            "WITH bounded AS (SELECT paid_amount FROM fact_order) SELECT paid_amount FROM bounded"
        ),
        expected_columns=[ExpectedColumn(name="paid_amount")],
    )
    result = ExecutionResult(
        version="v0.1",
        columns=["paid_amount"],
        rows=[[Decimal("100.00")]],
        returned_row_count=1,
        duration_ms=1,
        truncated=False,
    )
    documents = (evidence_bundle().planning_trace.context.documents[0],)

    trace = _verify(
        evidence_bundle(
            requirement=requirement,
            plan=plan,
            result=result,
            documents=documents,
            relationships=(),
        )
    )

    assert trace.result.status == "PASSED"
    assert any(
        gap.name == "metric_source:0:paid_amount"
        and gap.disposition is CoverageDisposition.UNSUPPORTED
        for gap in trace.coverage_gaps
    )
    assert not any(check.name == "metric_source:0:paid_amount" for check in trace.result.checks)


def test_negative_count_fails_empirical_verification() -> None:
    requirement = RequirementState(
        version="v0.1",
        goal="Count orders",
        metrics=[
            MetricRequirement(
                term="order count",
                resolved_name="order_count",
                status=ResolutionStatus.CONFIRMED,
            )
        ],
        status=RequirementStatus.READY,
    )
    plan = QueryPlan(
        version="v0.1",
        intent="Count orders",
        tables=["fact_order"],
        sql="SELECT COUNT(*) AS order_count FROM fact_order",
        expected_columns=[ExpectedColumn(name="order_count", semantic_role="metric")],
    )
    result = ExecutionResult(
        version="v0.1",
        columns=["order_count"],
        rows=[[-1]],
        returned_row_count=1,
        duration_ms=1,
        truncated=False,
    )
    documents = (evidence_bundle().planning_trace.context.documents[0],)

    trace = _verify(
        evidence_bundle(
            requirement=requirement,
            plan=plan,
            result=result,
            documents=documents,
            relationships=(),
        )
    )

    assert _failed(trace, "count_outputs_integral_nonnegative")


def test_duplicate_grouping_keys_fail_empirical_verification() -> None:
    result = ExecutionResult(
        version="v0.1",
        columns=["period", "province", "paid_amount"],
        rows=[
            [date(2026, 8, 1), "广东", Decimal("100.00")],
            [date(2026, 8, 1), "广东", Decimal("80.00")],
        ],
        returned_row_count=2,
        duration_ms=1,
        truncated=False,
    )

    trace = _verify(evidence_bundle(result=result))

    assert _failed(trace, "grouping_keys_unique")


def test_trace_binds_result_and_does_not_contain_raw_rows() -> None:
    bundle = evidence_bundle()
    trace = _verify(bundle)

    assert trace.evidence.result_fingerprint == execution_result_fingerprint(
        bundle.execution_result
    )
    assert "rows" not in trace.model_dump(mode="json")["evidence"]
