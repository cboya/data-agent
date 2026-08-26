"""Focused M10 test factories."""

from data_agent.contracts.query import QueryPlan

TEST_PLANNER_CONTEXT_FINGERPRINT = "9" * 64


def query_plan(sql: str, *, tables: list[str] | None = None) -> QueryPlan:
    return QueryPlan(
        version="v0.1",
        intent="M10 admission test",
        tables=tables or ["fact_order"],
        assumptions=[],
        sql=sql,
        expected_columns=[],
        explanation="Guard fixture",
    )
