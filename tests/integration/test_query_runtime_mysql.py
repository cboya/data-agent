"""Real-MySQL M11 authority, streaming, timeout, and fidelity evidence."""

from __future__ import annotations

from decimal import Decimal

import pymysql
import pytest

from data_agent.config import Settings
from data_agent.contracts.query import QueryPlan
from data_agent.query_runtime import (
    QueryTimeoutError,
    ReadOnlyQueryRuntime,
    RuntimeLimits,
)
from data_agent.query_runtime.evidence import ExecutionMetadata, execution_result_fingerprint
from data_agent.query_runtime.mysql import MySQLQueryConnectionFactory
from data_agent.sql_guard import ExplainPolicy, MySQLExplainProvider, SQLAdmissionService, SQLGuard
from data_agent.sql_guard.capability import GuardedQuery
from tests.sql_guard.factories import TEST_PLANNER_CONTEXT_FINGERPRINT


class RecordingMetadataSink:
    def __init__(self) -> None:
        self.records: list[ExecutionMetadata] = []

    def record(self, metadata: ExecutionMetadata) -> None:
        self.records.append(metadata)


def _admit(settings: Settings, sql: str, tables: list[str]) -> GuardedQuery:
    outcome = SQLAdmissionService(
        guard=SQLGuard(
            analytics_schema=settings.mysql_database,
            max_sql_characters=settings.max_sql_characters,
        ),
        explain_provider=MySQLExplainProvider(settings),
        explain_policy=ExplainPolicy(
            max_estimated_rows_per_access=settings.max_explain_estimated_rows
        ),
    ).admit(
        QueryPlan(
            version="v0.1",
            intent="M11 real-MySQL execution fixture",
            tables=tables,
            assumptions=[],
            sql=sql,
            expected_columns=[],
            explanation="M10-admitted M11 integration query",
        ),
        planner_context_fingerprint=TEST_PLANNER_CONTEXT_FINGERPRINT,
    )
    assert outcome.guarded_query is not None
    return outcome.guarded_query


def _runtime(
    settings: Settings,
    *,
    max_time_ms: int | None = None,
    max_rows: int | None = None,
    max_bytes: int | None = None,
    sink: RecordingMetadataSink | None = None,
) -> ReadOnlyQueryRuntime:
    return ReadOnlyQueryRuntime(
        connection_factory=MySQLQueryConnectionFactory(settings),
        limits=RuntimeLimits(
            max_execution_time_ms=max_time_ms or settings.max_query_time_ms,
            max_result_rows=max_rows or settings.max_result_rows,
            max_result_bytes=max_bytes or settings.max_result_bytes,
        ),
        metadata_sink=sink,
    )


@pytest.mark.integration
def test_real_runtime_preserves_actual_duplicate_columns_and_decimal(settings: Settings) -> None:
    sql = "SELECT paid_amount AS value, id AS value FROM fact_order WHERE id = 1"
    sink = RecordingMetadataSink()

    result = _runtime(settings, sink=sink).execute(_admit(settings, sql, ["fact_order"]))

    assert result.columns == ["value", "value"]
    assert result.rows == [[Decimal("100.00"), 1]]
    assert isinstance(result.rows[0][0], Decimal)
    assert result.truncated is False
    assert sink.records[0].result_fingerprint == execution_result_fingerprint(result)
    assert not hasattr(sink.records[0], "rows")


@pytest.mark.integration
def test_real_runtime_row_and_byte_bounds_are_authoritative(settings: Settings) -> None:
    row_sql = (
        "SELECT a.id AS left_id, b.id AS right_id "
        "FROM fact_order AS a CROSS JOIN fact_order AS b ORDER BY a.id, b.id"
    )
    row_result = _runtime(settings, max_rows=3).execute(_admit(settings, row_sql, ["fact_order"]))
    assert row_result.returned_row_count == 3
    assert row_result.truncated is True

    byte_sql = "SELECT status FROM fact_order ORDER BY id"
    byte_result = _runtime(settings, max_bytes=5).execute(
        _admit(settings, byte_sql, ["fact_order"])
    )
    assert byte_result.rows == []
    assert byte_result.returned_row_count == 0
    assert byte_result.truncated is True


@pytest.mark.integration
def test_runtime_principal_remains_select_only_and_cannot_see_control_schema(
    settings: Settings,
) -> None:
    factory = MySQLQueryConnectionFactory(settings)
    statements = [
        "UPDATE dim_region SET province = province WHERE id = 1",
        "DELETE FROM dim_region WHERE id = -1",
        "CREATE TABLE runtime_write_probe (id INT)",
        f"SELECT COUNT(*) FROM `{settings.mysql_control_database}`.`agent_session`",
    ]
    for statement in statements:
        connection = factory.connect()
        try:
            with connection.cursor() as cursor, pytest.raises(pymysql.MySQLError) as captured:
                cursor.execute(statement)
        finally:
            connection.close()
        assert captured.value.args[0] in {1044, 1142}


@pytest.mark.integration
def test_real_server_timeout_is_typed_and_one_attempt_only(settings: Settings) -> None:
    aliases = [f"fact_order AS t{index}" for index in range(8)]
    summed_ids = " + ".join(f"t{index}.id" for index in range(8))
    sql = f"SELECT SUM({summed_ids}) AS workload FROM " + " CROSS JOIN ".join(aliases)
    capability = _admit(settings, sql, ["fact_order"])
    sink = RecordingMetadataSink()

    with pytest.raises(QueryTimeoutError):
        _runtime(settings, max_time_ms=1, sink=sink).execute(capability)

    assert len(sink.records) == 1
    assert sink.records[0].execution_attempt_count == 1
    assert sink.records[0].error_code == "QUERY_TIMEOUT"
