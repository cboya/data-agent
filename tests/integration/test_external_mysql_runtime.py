"""Opt-in M17 conformance over the independently provisioned product-opinion source."""

from __future__ import annotations

import os
from decimal import Decimal

import pymysql
import pytest

from data_agent.catalog.introspection import preflight_external_mysql
from data_agent.catalog.semantic import assemble_semantic_catalog, load_curated_semantics
from data_agent.catalog.workspace import active_catalog_workspace
from data_agent.config import Settings
from data_agent.contracts.query import QueryPlan
from data_agent.query_runtime.mysql import MySQLQueryConnectionFactory
from data_agent.query_runtime.runtime import build_readonly_query_runtime
from data_agent.sql_guard.runtime import build_sql_admission_service

pytestmark = [pytest.mark.integration]

pytestmark.append(
    pytest.mark.skipif(
        os.getenv("RUN_EXTERNAL_MYSQL_INTEGRATION") != "1",
        reason="set RUN_EXTERNAL_MYSQL_INTEGRATION=1 for the bounded M17 external-MySQL smoke",
    )
)

_EXPECTED_TABLES = (
    "dim_opinion_product",
    "dim_opinion_source",
    "dim_opinion_topic",
    "fact_product_opinion",
)
_PLANNER_CONTEXT_FINGERPRINT = "0" * 64


def test_product_opinion_source_composes_through_guard_explain_and_runtime() -> None:
    settings = Settings()  # type: ignore[call-arg]
    assert settings.analytics_source_mode == "EXTERNAL"
    assert settings.analytics_allowed_tables == _EXPECTED_TABLES

    preflight = preflight_external_mysql(settings)
    assert preflight.report.allowed_table_count == 4
    assert preflight.report.column_count == 26
    assert preflight.report.foreign_key_count == 3
    assert preflight.report.table_comment_coverage == 1.0
    assert preflight.report.column_comment_coverage == 1.0

    workspace = active_catalog_workspace(settings)
    curated = load_curated_semantics(
        tables_path=workspace.tables_semantics_path,
        relationships_path=workspace.relationships_semantics_path,
    )
    catalog = assemble_semantic_catalog(preflight.generated_schema, curated)
    assert tuple(str(document.table) for document in catalog.documents) == _EXPECTED_TABLES
    assert len(catalog.relationships) == 3

    sql = (
        "SELECT p.product_category, COUNT(*) AS opinion_count, "
        "SUM(CASE WHEN o.sentiment_label = 'NEGATIVE' THEN 1 ELSE 0 END) "
        "AS negative_count, "
        "SUM(CASE WHEN o.risk_level = 'HIGH' THEN 1 ELSE 0 END) AS high_risk_count "
        "FROM fact_product_opinion AS o "
        "JOIN dim_opinion_product AS p ON p.id = o.product_id "
        "WHERE p.product_category IN ('SMARTWATCH', 'FITNESS_BAND') "
        "GROUP BY p.product_category ORDER BY p.product_category LIMIT 10"
    )
    plan = QueryPlan(
        version="v0.1",
        intent="Compare wearable product opinion risk",
        tables=["dim_opinion_product", "fact_product_opinion"],
        assumptions=[],
        sql=sql,
        expected_columns=[],
        explanation="M17 external MySQL conformance",
    )
    admission = build_sql_admission_service(settings).admit(
        plan,
        planner_context_fingerprint=_PLANNER_CONTEXT_FINGERPRINT,
    )
    assert admission.guarded_query is not None
    assert admission.explain_result is not None
    assert admission.explain_result.accepted is True
    assert {access.table for access in admission.explain_result.accesses} == {"o", "p"}

    evidence = build_readonly_query_runtime(settings).execute_with_evidence(admission.guarded_query)
    assert evidence.result.columns == [
        "product_category",
        "opinion_count",
        "negative_count",
        "high_risk_count",
    ]
    assert evidence.result.rows == [
        ["FITNESS_BAND", 5, Decimal("1"), Decimal("0")],
        ["SMARTWATCH", 5, Decimal("2"), Decimal("1")],
    ]
    assert evidence.result.truncated is False
    assert evidence.metadata.execution_attempt_count == 1

    connection = MySQLQueryConnectionFactory(settings).connect()
    try:
        with connection.cursor() as cursor, pytest.raises(pymysql.MySQLError) as captured:
            cursor.execute("SELECT COUNT(*) FROM fact_order")
    finally:
        connection.close()
    assert captured.value.args[0] in {1142, 1146}
