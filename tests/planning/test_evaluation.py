import asyncio
from pathlib import Path

from data_agent.catalog.semantic import load_assembled_catalog
from data_agent.contracts.query import ExpectedColumn, QueryPlan
from data_agent.model_runtime.ports import ModelFingerprint
from data_agent.planning.evaluation import (
    load_planner_eval_suite,
    run_planner_evaluation,
    write_planner_eval_report,
)
from data_agent.planning.service import QueryPlanner
from tests.planning.factories import INDEX_FINGERPRINT, FixedPlanModel


def _fingerprint() -> ModelFingerprint:
    return ModelFingerprint(
        provider="test",
        model="planner-double",
        digest="planner-digest",
        capabilities=("completion",),
    )


def test_frozen_planner_suite_covers_m9_business_and_boundary_cases() -> None:
    suite = load_planner_eval_suite()

    assert 20 <= len(suite.cases) <= 30
    assert {case.category for case in suite.cases} == {
        "catalog_injection",
        "dimension_join",
        "expected_shape",
        "fan_out",
        "irrelevant_context",
        "metric_semantics",
        "payment_attempt",
        "refund_net_revenue",
        "relationship_path",
        "single_table",
        "time_grain",
    }


def test_standalone_planner_eval_scores_policy_and_table_selection(tmp_path: Path) -> None:
    suite = load_planner_eval_suite()
    plans = tuple(
        QueryPlan(
            version="v0.1",
            intent=str(case.requirement.goal or case.id),
            tables=list(case.required_tables),
            assumptions=[],
            sql="SELECT " + ", ".join(f"1 AS {name}" for name in case.expected_columns),
            expected_columns=[ExpectedColumn(name=name) for name in case.expected_columns],
            explanation="deterministic planner evaluation double",
        )
        for case in suite.cases
    )
    report = asyncio.run(
        run_planner_evaluation(
            QueryPlanner(chat_model=FixedPlanModel(*plans)),
            suite=suite,
            catalog=load_assembled_catalog(),
            retrieval_index_fingerprint=INDEX_FINGERPRINT,
            chat_fingerprint=_fingerprint(),
            runtime_version="test-runtime",
        )
    )
    output = tmp_path / "planner.json"
    write_planner_eval_report(report, output_path=output)

    assert report.metrics.structured_plan_parse_rate == 1.0
    assert report.metrics.allowed_table_compliance == 1.0
    assert report.metrics.out_of_context_declared_table_rejection == 1.0
    assert report.metrics.required_table_recall == 1.0
    assert report.metrics.plan_table_precision == 1.0
    assert report.metrics.exact_required_table_set_accuracy == 1.0
    assert report.metrics.expected_column_accuracy == 1.0
    assert report.metrics.representative_sql_generation_rate < 0.10
    assert report.passed is True
    assert output.is_file()
