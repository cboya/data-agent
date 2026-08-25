import asyncio

import pytest

from data_agent.contracts.query import ExpectedColumn
from data_agent.planning.context import PlannerContext, PlannerContextBuilder
from data_agent.planning.errors import PlannerPolicyError
from data_agent.planning.policy import PlannerPolicy
from data_agent.planning.prompt import PLANNER_PROMPT_VERSION
from data_agent.planning.service import QueryPlanner
from tests.planning.factories import (
    INDEX_FINGERPRINT,
    FixedPlanModel,
    paid_amount_plan,
    ready_requirement,
    retrieval_result,
)
from tests.retrieval.factories import catalog


def _context() -> PlannerContext:
    assembled = catalog()
    result = retrieval_result(("fact_order", "dim_user"), assembled=assembled)
    documents = tuple(
        document
        for document in assembled.documents
        if str(document.table) in {"fact_order", "dim_user"}
    )
    return PlannerContextBuilder().build(
        requirement=ready_requirement(),
        retrieval=result,
        catalog=assembled,
        documents=documents,
        expected_retrieval_index_fingerprint=INDEX_FINGERPRINT,
    )


def test_policy_rejects_duplicate_and_out_of_context_declared_tables() -> None:
    context = _context()
    policy = PlannerPolicy()

    with pytest.raises(PlannerPolicyError, match="unique"):
        policy.validate(
            paid_amount_plan(tables=["fact_order", "fact_order"]),
            context=context,
        )
    with pytest.raises(PlannerPolicyError, match="escape"):
        policy.validate(
            paid_amount_plan(tables=["fact_order", "secret_table"]),
            context=context,
        )


def test_policy_leaves_sql_table_truth_for_m10() -> None:
    context = _context()
    lying_sql = paid_amount_plan(sql="SELECT * FROM secret_table")

    accepted = PlannerPolicy().validate(lying_sql, context=context)

    assert accepted.sql == "SELECT * FROM secret_table"
    assert accepted.tables == ["fact_order"]


def test_policy_bounds_assumptions_and_expected_columns() -> None:
    context = _context()
    too_many_assumptions = paid_amount_plan().model_copy(
        update={"assumptions": [f"assumption {index}" for index in range(9)]}
    )
    duplicate_columns = paid_amount_plan().model_copy(
        update={
            "expected_columns": [
                ExpectedColumn(name="value"),
                ExpectedColumn(name="value"),
            ]
        }
    )

    with pytest.raises(PlannerPolicyError, match="assumptions"):
        PlannerPolicy().validate(too_many_assumptions, context=context)
    with pytest.raises(PlannerPolicyError, match="column names"):
        PlannerPolicy().validate(duplicate_columns, context=context)


def test_query_planner_uses_public_query_plan_and_returns_trace() -> None:
    assembled = catalog()
    result = retrieval_result(("fact_order", "dim_user"), assembled=assembled)
    model = FixedPlanModel(paid_amount_plan())
    planner = QueryPlanner(chat_model=model)

    trace = asyncio.run(
        planner.plan(
            requirement=ready_requirement(),
            retrieval=result,
            catalog=assembled,
            expected_retrieval_index_fingerprint=INDEX_FINGERPRINT,
        )
    )

    assert trace.plan.tables == ["fact_order"]
    assert trace.prompt_version == PLANNER_PROMPT_VERSION
    assert trace.retrieval_index_fingerprint == INDEX_FINGERPRINT
    assert trace.allowed_tables == ("fact_order", "dim_user")
    assert trace.model_fingerprint is None
    assert tuple(str(table) for table in trace.context.allowed_tables) == (
        "fact_order",
        "dim_user",
    )
    assert model.calls[0][1].__name__ == "QueryPlan"
    assert model.calls[0][2] == PLANNER_PROMPT_VERSION
