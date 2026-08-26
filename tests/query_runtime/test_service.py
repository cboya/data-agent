"""M11 execution invariants over deterministic DB-API doubles."""

from __future__ import annotations

from decimal import Decimal
from typing import cast

import pymysql
import pytest

from data_agent.query_runtime import (
    CapabilityIntegrityError,
    DatabaseExecutionError,
    DatabaseUnavailableError,
    QueryTimeoutError,
    UnsupportedResultTypeError,
)
from data_agent.query_runtime.evidence import (
    EXECUTION_METADATA_VERSION,
    RESULT_FINGERPRINT_VERSION,
    ExecutionOutcome,
    execution_result_fingerprint,
)
from data_agent.sql_guard.capability import GuardedQuery
from tests.query_runtime.factories import (
    FakeCursor,
    FakeFactory,
    RecordingSink,
    guarded_query,
    runtime,
)


def test_raw_sql_has_no_runtime_route() -> None:
    factory = FakeFactory(FakeCursor(rows=[(1,)], columns=["one"]))

    with pytest.raises(CapabilityIntegrityError, match="GuardedQuery only"):
        runtime(factory).execute(cast(GuardedQuery, "SELECT 1"))

    assert factory.connect_count == 0


def test_tampered_or_stale_capability_fails_before_connect() -> None:
    factory = FakeFactory(FakeCursor(rows=[(1,)], columns=["one"]))
    tampered = guarded_query("SELECT id FROM fact_order")
    object.__setattr__(tampered, "sql", "SELECT user_id FROM fact_order")

    with pytest.raises(CapabilityIntegrityError):
        runtime(factory).execute(tampered)

    stale = guarded_query("SELECT id FROM fact_order")
    object.__setattr__(stale, "guard_policy_version", "sql-guard-stale")
    with pytest.raises(CapabilityIntegrityError):
        runtime(factory).execute(stale)

    wrong_plan_identity = guarded_query("SELECT id FROM fact_order")
    object.__setattr__(wrong_plan_identity, "query_plan_fingerprint", "0" * 64)
    with pytest.raises(CapabilityIntegrityError):
        runtime(factory).execute(wrong_plan_identity)
    assert factory.connect_count == 0


def test_capability_namespace_must_match_runtime_before_connect() -> None:
    factory = FakeFactory(
        FakeCursor(rows=[(1,)], columns=["id"]),
        database_schema="analytics_b",
    )
    capability = guarded_query(
        "SELECT id FROM fact_order",
        analytics_schema="analytics_a",
    )

    with pytest.raises(CapabilityIntegrityError, match="namespace"):
        runtime(factory).execute(capability)

    assert factory.connect_count == 0


def test_tampered_namespace_is_part_of_capability_fingerprint() -> None:
    factory = FakeFactory(FakeCursor(rows=[(1,)], columns=["id"]))
    capability = guarded_query("SELECT id FROM fact_order")
    object.__setattr__(capability, "execution_namespace", "other_analytics")

    with pytest.raises(CapabilityIntegrityError, match="integrity"):
        runtime(factory).execute(capability)

    assert factory.connect_count == 0


def test_exact_sql_session_policy_shape_and_numeric_fidelity() -> None:
    sql = " SELECT paid_amount AS id, id FROM fact_order ORDER BY id "
    cursor = FakeCursor(rows=[(Decimal("100.00"), 1)], columns=["id", "id"])
    factory = FakeFactory(cursor)
    sink = RecordingSink()

    result = runtime(factory, sink=sink).execute(guarded_query(sql))

    assert cursor.executed == [(sql, None)]
    assert result.columns == ["id", "id"]
    assert result.rows == [[Decimal("100.00"), 1]]
    assert isinstance(result.rows[0][0], Decimal)
    assert factory.connection.rollback_count == 1
    setup_statements = [statement for statement, _ in factory.connection.setup_cursor.executed]
    assert setup_statements == [
        "SET SESSION TRANSACTION READ ONLY",
        "SET SESSION max_execution_time = %s",
        "SELECT DATABASE(), CURRENT_USER(), "
        "@@SESSION.transaction_read_only, @@SESSION.max_execution_time",
    ]
    metadata = sink.records[0]
    assert metadata.version == EXECUTION_METADATA_VERSION == "execution-metadata-v0.2"
    assert metadata.outcome is ExecutionOutcome.SUCCEEDED
    assert metadata.sql_digest == guarded_query(sql).sql_digest
    assert metadata.execution_namespace == "data_agent"
    assert metadata.result_fingerprint_version == RESULT_FINGERPRINT_VERSION
    assert metadata.result_fingerprint == execution_result_fingerprint(result)
    assert metadata.returned_row_count == 1
    assert not hasattr(metadata, "rows")


def test_row_cap_fetches_one_extra_and_abandons_connection_without_cursor_close() -> None:
    cursor = FakeCursor(rows=[(1,), (2,), (3,), (4,)], columns=["id"])
    factory = FakeFactory(cursor)

    result = runtime(factory, max_rows=2).execute(guarded_query("SELECT id FROM fact_order"))

    assert result.rows == [[1], [2]]
    assert result.returned_row_count == 2
    assert result.truncated is True
    assert cursor.fetch_count == 3
    assert cursor.close_called is False
    assert factory.connection.close_called is True


def test_result_byte_cap_is_authoritative_and_abandons_connection() -> None:
    cursor = FakeCursor(rows=[("a very large result cell",), ("unread",)], columns=["payload"])
    factory = FakeFactory(cursor)

    result = runtime(factory, max_bytes=5).execute(guarded_query("SELECT status FROM fact_order"))

    assert result.rows == []
    assert result.returned_row_count == 0
    assert result.truncated is True
    assert cursor.fetch_count == 1
    assert cursor.close_called is False


def test_unsupported_result_type_fails_closed_without_stringifying() -> None:
    cursor = FakeCursor(rows=[(b"blob",)], columns=["payload"])
    factory = FakeFactory(cursor)

    with pytest.raises(UnsupportedResultTypeError, match="bytes"):
        runtime(factory).execute(guarded_query("SELECT status FROM fact_order"))

    assert cursor.close_called is False
    assert factory.connection.close_called is True


def test_server_timeout_is_typed_recorded_and_never_retried() -> None:
    error = pymysql.OperationalError(3024, "timeout reader-secret password=reader-secret")
    cursor = FakeCursor(columns=["id"], execute_error=error)
    factory = FakeFactory(cursor)
    sink = RecordingSink()

    with pytest.raises(QueryTimeoutError) as captured:
        runtime(factory, sink=sink).execute(guarded_query("SELECT id FROM fact_order"))

    assert len(cursor.executed) == 1
    assert captured.value.safe_detail is not None
    assert "reader-secret" not in captured.value.safe_detail
    assert captured.value.provider_errno == 3024
    metadata = sink.records[0]
    assert metadata.execution_attempt_count == 1
    assert metadata.error_code == "QUERY_TIMEOUT"
    assert metadata.outcome is ExecutionOutcome.FAILED


def test_connection_and_database_errors_are_typed_without_retry() -> None:
    unavailable = FakeFactory(
        FakeCursor(), connect_error=pymysql.OperationalError(2003, "cannot connect")
    )
    sink = RecordingSink()
    with pytest.raises(DatabaseUnavailableError):
        runtime(unavailable, sink=sink).execute(guarded_query())
    assert unavailable.connect_count == 1
    assert sink.records[0].execution_attempt_count == 0

    cursor = FakeCursor(
        columns=["missing"],
        execute_error=pymysql.ProgrammingError(1054, "unknown column"),
    )
    database_error = FakeFactory(cursor)
    with pytest.raises(DatabaseExecutionError) as captured:
        runtime(database_error).execute(guarded_query("SELECT id FROM fact_order"))
    assert captured.value.provider_errno == 1054
    assert len(cursor.executed) == 1
