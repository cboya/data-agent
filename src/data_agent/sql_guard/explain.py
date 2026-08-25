"""Harness-owned MySQL EXPLAIN provider and deterministic admission policy."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from typing import Any, Protocol

import pymysql

from data_agent.config import Settings
from data_agent.contracts.execution import ExplainResult, ExplainTableAccess
from data_agent.infrastructure.mysql_world import readonly_connection
from data_agent.sql_guard.capability import GuardedSQL
from data_agent.sql_guard.errors import ExplainProviderError


class ExplainPlanProvider(Protocol):
    """A provider that accepts only a post-guard capability, never raw SQL."""

    def explain(self, candidate: GuardedSQL) -> str: ...


class MySQLExplainProvider:
    """Run EXPLAIN FORMAT=JSON with the analytics read-only principal."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def explain(self, candidate: GuardedSQL) -> str:
        statement = f"EXPLAIN FORMAT=JSON\n{candidate.sql}"
        connection = None
        try:
            connection = readonly_connection(self._settings)
            with connection.cursor() as cursor:
                cursor.execute(statement)
                row = cursor.fetchone()
        except pymysql.MySQLError as error:
            raise ExplainProviderError("MySQL EXPLAIN failed") from error
        finally:
            if connection is not None:
                connection.close()
        if row is None or len(row) != 1 or not isinstance(row[0], str):
            raise ExplainProviderError("MySQL EXPLAIN returned an invalid result shape")
        return row[0]


class _ExplainTraversalLimit(RuntimeError):
    pass


def _table_nodes(value: Any, *, max_nodes: int) -> Iterator[Mapping[str, Any]]:
    pending = [value]
    visited = 0
    while pending:
        current = pending.pop()
        visited += 1
        if visited > max_nodes:
            raise _ExplainTraversalLimit
        if isinstance(current, Mapping):
            children: list[Any] = []
            for key, child in current.items():
                if key == "table" and isinstance(child, Mapping):
                    yield child
                children.append(child)
            pending.extend(reversed(children))
        elif isinstance(current, list):
            pending.extend(reversed(current))


class ExplainPolicy:
    """Fail-closed MVP policy over MySQL's JSON access estimates."""

    def __init__(
        self,
        *,
        max_estimated_rows_per_access: int,
        max_explain_characters: int = 1_000_000,
        max_explain_nodes: int = 10_000,
    ) -> None:
        if max_estimated_rows_per_access < 1:
            raise ValueError("EXPLAIN row-estimate threshold must be positive")
        if max_explain_characters < 1 or max_explain_nodes < 1:
            raise ValueError("EXPLAIN structural bounds must be positive")
        self._max_estimated_rows_per_access = max_estimated_rows_per_access
        self._max_explain_characters = max_explain_characters
        self._max_explain_nodes = max_explain_nodes

    def evaluate(self, candidate: GuardedSQL, raw_explain: str) -> ExplainResult:
        if len(raw_explain) > self._max_explain_characters:
            return self._rejected("EXPLAIN_SIZE_LIMIT_EXCEEDED")
        try:
            document = json.loads(raw_explain)
        except (json.JSONDecodeError, RecursionError, TypeError, ValueError):
            return self._rejected("INVALID_EXPLAIN_JSON")
        if not isinstance(document, dict) or "query_block" not in document:
            return self._rejected("INVALID_EXPLAIN_SHAPE")

        accesses: list[ExplainTableAccess] = []
        try:
            for table in _table_nodes(document, max_nodes=self._max_explain_nodes):
                table_name = table.get("table_name")
                estimated_rows = table.get("rows_examined_per_scan")
                if not isinstance(table_name, str) or not table_name.strip():
                    return self._rejected("INVALID_TABLE_ACCESS", accesses)
                if not isinstance(estimated_rows, int) or isinstance(estimated_rows, bool):
                    return self._rejected("MISSING_ROW_ESTIMATE", accesses)
                if estimated_rows < 0:
                    return self._rejected("INVALID_ROW_ESTIMATE", accesses)
                access_type = table.get("access_type")
                key = table.get("key")
                if access_type is not None and not isinstance(access_type, str):
                    return self._rejected("INVALID_ACCESS_TYPE", accesses)
                if key is not None and not isinstance(key, str):
                    return self._rejected("INVALID_ACCESS_KEY", accesses)
                accesses.append(
                    ExplainTableAccess(
                        table=table_name,
                        access_type=access_type,
                        key=key,
                        estimated_rows=estimated_rows,
                    )
                )
                if estimated_rows > self._max_estimated_rows_per_access:
                    return self._rejected("ROW_ESTIMATE_LIMIT_EXCEEDED", accesses)
        except _ExplainTraversalLimit:
            return self._rejected("EXPLAIN_NODE_LIMIT_EXCEEDED", accesses)

        if candidate.physical_tables and not accesses:
            return self._rejected("MISSING_TABLE_ACCESSES")
        return ExplainResult(accepted=True, accesses=accesses)

    @staticmethod
    def _rejected(
        reason: str,
        accesses: list[ExplainTableAccess] | None = None,
    ) -> ExplainResult:
        return ExplainResult(
            accepted=False,
            accesses=[] if accesses is None else accesses,
            rejection_reason=reason,
        )
