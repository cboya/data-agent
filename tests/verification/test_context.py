"""M12 result fingerprint and evidence-chain integrity regressions."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from data_agent.contracts.catalog import CatalogColumn
from data_agent.contracts.execution import ExecutionResult
from data_agent.contracts.query import QueryPlan
from data_agent.planning.context import PlannerContext
from data_agent.query_runtime.evidence import execution_result_fingerprint
from data_agent.verification import (
    VerificationContext,
    VerificationIntegrityError,
    build_verification_context,
)
from tests.verification.factories import EvidenceBundle, evidence_bundle


def _build(bundle: EvidenceBundle) -> VerificationContext:
    return build_verification_context(
        planning_trace=bundle.planning_trace,
        guarded_query=bundle.guarded_query,
        execution_metadata=bundle.execution_metadata,
        execution_result=bundle.execution_result,
    )


def test_result_fingerprint_is_typed_ordered_and_excludes_duration() -> None:
    result = ExecutionResult(
        version="v0.1",
        columns=["value", "day"],
        rows=[[Decimal("1.00"), date(2026, 8, 26)]],
        returned_row_count=1,
        duration_ms=1,
        truncated=False,
    )
    different_duration = result.model_copy(update={"duration_ms": 999})
    reordered = ExecutionResult(
        version="v0.1",
        columns=["day", "value"],
        rows=[[date(2026, 8, 26), Decimal("1.00")]],
        returned_row_count=1,
        duration_ms=1,
        truncated=False,
    )

    assert execution_result_fingerprint(result) == execution_result_fingerprint(different_duration)
    assert execution_result_fingerprint(result) != execution_result_fingerprint(reordered)

    integer = ExecutionResult(
        version="v0.1",
        columns=["value"],
        rows=[[1]],
        returned_row_count=1,
        duration_ms=1,
        truncated=False,
    )
    decimal = ExecutionResult(
        version="v0.1",
        columns=["value"],
        rows=[[Decimal("1")]],
        returned_row_count=1,
        duration_ms=1,
        truncated=False,
    )
    assert execution_result_fingerprint(integer) != execution_result_fingerprint(decimal)


def test_coherent_context_builds_and_revalidates() -> None:
    context = _build(evidence_bundle())
    context.verify_integrity()


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("query_plan_fingerprint", "0" * 64, "plan identity"),
        ("planner_context_fingerprint", "0" * 64, "PlannerContext identity"),
        ("guarded_query_fingerprint", "0" * 64, "capability identity"),
        ("execution_namespace", "other", "namespace"),
        ("guard_policy_version", "stale", "guard policy"),
    ],
)
def test_capability_metadata_identity_mismatch_fails_closed(
    field: str,
    value: str,
    match: str,
) -> None:
    bundle = evidence_bundle(metadata_overrides={field: value})

    with pytest.raises(VerificationIntegrityError, match=match):
        _build(bundle)


def test_result_fingerprint_mismatch_fails_before_checks() -> None:
    bundle = evidence_bundle()
    different_result = ExecutionResult(
        version="v0.1",
        columns=list(bundle.execution_result.columns),
        rows=[[date(2026, 8, 1), "广东", Decimal("999.00")]],
        returned_row_count=1,
        duration_ms=bundle.execution_result.duration_ms,
        truncated=False,
    )

    with pytest.raises(VerificationIntegrityError, match="fingerprint"):
        build_verification_context(
            planning_trace=bundle.planning_trace,
            guarded_query=bundle.guarded_query,
            execution_metadata=bundle.execution_metadata,
            execution_result=different_result,
        )


def test_planning_trace_plan_mismatch_fails_closed() -> None:
    bundle = evidence_bundle()
    altered_plan = bundle.planning_trace.plan.model_copy(update={"intent": "different"})
    altered_trace = replace(bundle.planning_trace, plan=altered_plan)

    with pytest.raises(VerificationIntegrityError, match="PlanningTrace"):
        build_verification_context(
            planning_trace=altered_trace,
            guarded_query=bundle.guarded_query,
            execution_metadata=bundle.execution_metadata,
            execution_result=bundle.execution_result,
        )


def test_swapped_relationship_context_fails_before_semantic_checks() -> None:
    bundle = evidence_bundle()
    original = bundle.planning_trace.context
    changed_relationship = original.relationships[0].model_copy(update={"from_column": "id"})
    changed_context = PlannerContext.model_validate(
        {
            **original.model_dump(mode="json"),
            "relationships": [
                changed_relationship.model_dump(mode="json"),
                *[
                    relationship.model_dump(mode="json")
                    for relationship in original.relationships[1:]
                ],
            ],
        }
    )
    changed_trace = replace(bundle.planning_trace, context=changed_context)

    with pytest.raises(VerificationIntegrityError, match="PlannerContext fingerprint"):
        build_verification_context(
            planning_trace=changed_trace,
            guarded_query=bundle.guarded_query,
            execution_metadata=bundle.execution_metadata,
            execution_result=bundle.execution_result,
        )


def test_swapped_catalog_document_context_fails_before_semantic_checks() -> None:
    bundle = evidence_bundle()
    original = bundle.planning_trace.context
    order_document = original.documents[0]
    changed_columns = [
        CatalogColumn.model_validate(
            {
                **column.model_dump(mode="json"),
                "aliases": [*column.aliases, "tampered-semantic-alias"],
            }
        )
        if str(column.name) == "paid_amount"
        else column
        for column in order_document.columns
    ]
    changed_document = order_document.model_copy(update={"columns": changed_columns})
    changed_context = PlannerContext.model_validate(
        {
            **original.model_dump(mode="json"),
            "documents": [
                changed_document.model_dump(mode="json"),
                *[document.model_dump(mode="json") for document in original.documents[1:]],
            ],
        }
    )
    changed_trace = replace(bundle.planning_trace, context=changed_context)

    with pytest.raises(VerificationIntegrityError, match="PlannerContext fingerprint"):
        build_verification_context(
            planning_trace=changed_trace,
            guarded_query=bundle.guarded_query,
            execution_metadata=bundle.execution_metadata,
            execution_result=bundle.execution_result,
        )


def test_planning_trace_plan_cannot_escape_bounded_context() -> None:
    base = evidence_bundle()
    plan = QueryPlan(
        version="v0.1",
        intent="Declared scope escape",
        tables=["fact_order", "dim_region"],
        sql="SELECT paid_amount FROM fact_order",
        expected_columns=[],
    )
    bundle = evidence_bundle(
        plan=plan,
        result=ExecutionResult(
            version="v0.1",
            columns=["paid_amount"],
            rows=[[Decimal("100.00")]],
            returned_row_count=1,
            duration_ms=1,
            truncated=False,
        ),
        documents=(base.planning_trace.context.documents[0],),
        relationships=(),
    )

    with pytest.raises(VerificationIntegrityError, match="escapes"):
        _build(bundle)
