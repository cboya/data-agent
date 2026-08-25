"""The provider accepts an EXPLAIN-safe capability and owns exact construction."""

from typing import Any, cast

import pymysql
import pytest

from data_agent.config import Settings
from data_agent.sql_guard import ExplainProviderError, GuardedSQL, MySQLExplainProvider, SQLGuard
from tests.sql_guard.factories import query_plan


class FakeCursor:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, statement: str) -> None:
        self.statements.append(statement)

    def fetchone(self) -> tuple[str]:
        return ('{"query_block":{"select_id":1}}',)


class FakeConnection:
    def __init__(self) -> None:
        self.fake_cursor = FakeCursor()
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self.fake_cursor

    def close(self) -> None:
        self.closed = True


def test_provider_constructs_format_json_not_analyze(
    monkeypatch: Any,
    settings: Settings,
) -> None:
    connection = FakeConnection()
    monkeypatch.setattr(
        "data_agent.sql_guard.explain.readonly_connection",
        lambda _: connection,
    )
    sql = "SELECT id FROM fact_order"
    candidate = cast(
        GuardedSQL,
        SQLGuard(analytics_schema=settings.mysql_database).evaluate(query_plan(sql)).candidate,
    )

    result = MySQLExplainProvider(settings).explain(candidate)

    assert result == '{"query_block":{"select_id":1}}'
    assert connection.fake_cursor.statements == [f"EXPLAIN FORMAT=JSON\n{sql}"]
    assert "ANALYZE" not in connection.fake_cursor.statements[0]
    assert connection.closed is True


def test_connection_failure_is_redacted_and_fail_closed(
    monkeypatch: Any,
    settings: Settings,
) -> None:
    monkeypatch.setattr(
        "data_agent.sql_guard.explain.readonly_connection",
        lambda _: (_ for _ in ()).throw(pymysql.OperationalError(2003, "sensitive")),
    )
    candidate = cast(
        GuardedSQL,
        SQLGuard(analytics_schema=settings.mysql_database)
        .evaluate(query_plan("SELECT 1"))
        .candidate,
    )

    with pytest.raises(ExplainProviderError, match="MySQL EXPLAIN failed") as error:
        MySQLExplainProvider(settings).explain(candidate)

    assert "sensitive" not in str(error.value)
