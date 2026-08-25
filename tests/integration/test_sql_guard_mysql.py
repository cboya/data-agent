"""M10 integration proves EXPLAIN admission without running the query."""

import pytest

from data_agent.config import Settings
from data_agent.contracts.query import QueryPlan
from data_agent.sql_guard import ExplainPolicy, MySQLExplainProvider, SQLAdmissionService, SQLGuard


@pytest.mark.integration
def test_real_mysql_json_explain_issues_guarded_query(settings: Settings) -> None:
    sql = (
        "SELECT u.region_id, SUM(o.paid_amount) AS paid_amount "
        "FROM fact_order AS o JOIN dim_user AS u ON u.id = o.user_id "
        "GROUP BY u.region_id"
    )
    plan = QueryPlan(
        version="v0.1",
        intent="M10 integration admission",
        tables=["fact_order", "dim_user"],
        assumptions=[],
        sql=sql,
        expected_columns=[],
        explanation="EXPLAIN only",
    )
    admission = SQLAdmissionService(
        guard=SQLGuard(
            analytics_schema=settings.mysql_database,
            max_sql_characters=settings.max_sql_characters,
        ),
        explain_provider=MySQLExplainProvider(settings),
        explain_policy=ExplainPolicy(
            max_estimated_rows_per_access=settings.max_explain_estimated_rows
        ),
    )

    outcome = admission.admit(plan)

    assert outcome.guarded_query is not None
    assert outcome.guarded_query.sql == sql
    assert outcome.explain_result is not None
    assert outcome.explain_result.accepted is True
    assert {access.table for access in outcome.explain_result.accesses} == {"o", "u"}


@pytest.mark.integration
def test_rejected_sql_never_reaches_real_mysql_explain(settings: Settings) -> None:
    plan = QueryPlan(
        version="v0.1",
        intent="M10 integration rejection",
        tables=["fact_order"],
        assumptions=[],
        sql="DELETE FROM fact_order",
        expected_columns=[],
        explanation="Must stop before EXPLAIN",
    )
    admission = SQLAdmissionService(
        guard=SQLGuard(analytics_schema=settings.mysql_database),
        explain_provider=MySQLExplainProvider(settings),
        explain_policy=ExplainPolicy(max_estimated_rows_per_access=100_000),
    )

    outcome = admission.admit(plan)

    assert outcome.guarded_query is None
    assert outcome.explain_result is None
