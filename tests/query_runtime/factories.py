"""Focused M11 capabilities and DB-API doubles."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, cast

from pymysql.cursors import SSCursor

from data_agent.contracts.query import QueryPlan
from data_agent.query_runtime.evidence import ExecutionMetadata
from data_agent.query_runtime.mysql import (
    ANALYTICS_READONLY_PRINCIPAL,
    QueryConnectionFactory,
)
from data_agent.query_runtime.service import ReadOnlyQueryRuntime, RuntimeLimits
from data_agent.sql_guard.capability import GuardedQuery, GuardedSQL
from data_agent.sql_guard.explain import ExplainPolicy
from data_agent.sql_guard.guard import SQLGuard
from data_agent.sql_guard.service import SQLAdmissionService


class StaticExplainProvider:
    def explain(self, candidate: GuardedSQL) -> str:
        table_name = candidate.physical_tables[0].name if candidate.physical_tables else None
        query_block: dict[str, Any] = {"select_id": 1}
        if table_name is not None:
            query_block["table"] = {
                "table_name": table_name,
                "access_type": "ALL",
                "rows_examined_per_scan": 10,
            }
        return json.dumps({"query_block": query_block})


def guarded_query(
    sql: str = "SELECT paid_amount FROM fact_order ORDER BY id",
    *,
    tables: list[str] | None = None,
) -> GuardedQuery:
    plan = QueryPlan(
        version="v0.1",
        intent="M11 runtime fixture",
        tables=tables or ["fact_order"],
        assumptions=[],
        sql=sql,
        expected_columns=[],
        explanation="M11 fixture",
    )
    outcome = SQLAdmissionService(
        guard=SQLGuard(analytics_schema="data_agent"),
        explain_provider=StaticExplainProvider(),
        explain_policy=ExplainPolicy(max_estimated_rows_per_access=100),
    ).admit(plan)
    assert outcome.guarded_query is not None
    return outcome.guarded_query


class FakeCursor:
    def __init__(
        self,
        *,
        rows: Sequence[tuple[object, ...]] = (),
        columns: Sequence[str] = (),
        execute_error: BaseException | None = None,
    ) -> None:
        self._rows = list(rows)
        self.description = tuple((name, None, None, None, None, None, None) for name in columns)
        self.execute_error = execute_error
        self.executed: list[tuple[str, object | None]] = []
        self.fetch_count = 0
        self.close_called = False

    def execute(self, statement: str, args: object | None = None) -> int:
        self.executed.append((statement, args))
        if self.execute_error is not None:
            raise self.execute_error
        return 0

    def fetchone(self) -> tuple[object, ...] | None:
        self.fetch_count += 1
        if not self._rows:
            return None
        return self._rows.pop(0)

    def close(self) -> None:
        self.close_called = True


class SessionCursor(FakeCursor):
    def __init__(self, *, schema: str, principal: str, timeout_ms: int) -> None:
        super().__init__()
        self._verification_row = (schema, f"{principal}@%", 1, timeout_ms)
        self._verification_pending = False

    def execute(self, statement: str, args: object | None = None) -> int:
        result = super().execute(statement, args)
        if statement.startswith("SELECT DATABASE()"):
            self._verification_pending = True
        return result

    def fetchone(self) -> tuple[object, ...] | None:
        self.fetch_count += 1
        if self._verification_pending:
            self._verification_pending = False
            return self._verification_row
        return None


class FakeConnection:
    def __init__(self, *, setup_cursor: SessionCursor, query_cursor: FakeCursor) -> None:
        self.setup_cursor = setup_cursor
        self.query_cursor = query_cursor
        self.rollback_count = 0
        self.close_called = False

    def cursor(self, cursor_type: object | None = None) -> FakeCursor:
        return self.query_cursor if cursor_type is SSCursor else self.setup_cursor

    def rollback(self) -> None:
        self.rollback_count += 1

    def close(self) -> None:
        self.close_called = True


class FakeFactory:
    database_schema = "data_agent"
    principal_name = "data_agent_reader"
    principal_class = ANALYTICS_READONLY_PRINCIPAL
    read_timeout_seconds = 10
    redaction_values = ("reader-secret",)

    def __init__(
        self,
        query_cursor: FakeCursor,
        *,
        max_execution_time_ms: int = 5_000,
        connect_error: BaseException | None = None,
    ) -> None:
        self.connection = FakeConnection(
            setup_cursor=SessionCursor(
                schema=self.database_schema,
                principal=self.principal_name,
                timeout_ms=max_execution_time_ms,
            ),
            query_cursor=query_cursor,
        )
        self.connect_error = connect_error
        self.connect_count = 0

    def connect(self) -> FakeConnection:
        self.connect_count += 1
        if self.connect_error is not None:
            raise self.connect_error
        return self.connection


class RecordingSink:
    def __init__(self) -> None:
        self.records: list[ExecutionMetadata] = []

    def record(self, metadata: ExecutionMetadata) -> None:
        self.records.append(metadata)


def runtime(
    factory: FakeFactory,
    *,
    max_rows: int = 1_000,
    max_bytes: int = 8_388_608,
    sink: RecordingSink | None = None,
) -> ReadOnlyQueryRuntime:
    return ReadOnlyQueryRuntime(
        connection_factory=cast(QueryConnectionFactory, factory),
        limits=RuntimeLimits(
            max_execution_time_ms=5_000,
            max_result_rows=max_rows,
            max_result_bytes=max_bytes,
        ),
        metadata_sink=sink,
    )
