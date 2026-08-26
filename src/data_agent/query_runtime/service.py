"""Capability-only, bounded, read-only MySQL execution."""

from __future__ import annotations

import math
import re
import socket
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pymysql
from pymysql.connections import Connection
from pymysql.cursors import Cursor, SSCursor

from data_agent.contracts.execution import ExecutionResult
from data_agent.query_runtime.errors import (
    CapabilityIntegrityError,
    DatabaseExecutionError,
    DatabaseUnavailableError,
    QueryTimeoutError,
    ResultDecodingError,
    RuntimeExecutionError,
    UnsupportedResultTypeError,
)
from data_agent.query_runtime.evidence import (
    EXECUTION_METADATA_VERSION,
    RESULT_BYTE_ACCOUNTING_VERSION,
    RESULT_FINGERPRINT_VERSION,
    ExecutionMetadata,
    ExecutionMetadataSink,
    ExecutionOutcome,
    NullExecutionMetadataSink,
    execution_result_fingerprint,
)
from data_agent.query_runtime.mysql import (
    ANALYTICS_READONLY_PRINCIPAL,
    QueryConnectionFactory,
)
from data_agent.sql_guard.capability import GuardedQuery
from data_agent.sql_guard.explain import EXPLAIN_POLICY_VERSION
from data_agent.sql_guard.guard import SQL_GUARD_POLICY_VERSION

_MAX_SAFE_ERROR_CHARACTERS = 512
_UNAVAILABLE_MYSQL_CODES = frozenset({2002, 2003, 2005, 2006, 2013})
_QUERY_TIMEOUT_MYSQL_CODES = frozenset({3024})
QUERY_RUNTIME_POLICY_VERSION = "query-runtime-v0.2"


@dataclass(frozen=True)
class RuntimeLimits:
    max_execution_time_ms: int
    max_result_rows: int
    max_result_bytes: int

    def __post_init__(self) -> None:
        if min(self.max_execution_time_ms, self.max_result_rows, self.max_result_bytes) < 1:
            raise ValueError("runtime execution and result bounds must be positive")


def _canonical_cell_bytes(value: object) -> bytes:
    """Return versioned, deterministic accounting bytes without changing the value."""

    try:
        if value is None:
            return b"n:"
        if isinstance(value, bool):
            return b"b:1" if value else b"b:0"
        if isinstance(value, int):
            return f"i:{value}".encode("ascii")
        if isinstance(value, Decimal):
            if not value.is_finite():
                raise ResultDecodingError("MySQL returned a non-finite Decimal")
            return f"d:{value}".encode("ascii")
        if isinstance(value, float):
            if not math.isfinite(value):
                raise ResultDecodingError("MySQL returned a non-finite float")
            return f"f:{value!r}".encode("ascii")
        if isinstance(value, datetime):
            return f"dt:{value.isoformat(timespec='microseconds')}".encode("ascii")
        if isinstance(value, date):
            return f"da:{value.isoformat()}".encode("ascii")
        if isinstance(value, str):
            return b"s:" + value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise ResultDecodingError("MySQL text could not be encoded as UTF-8") from error
    raise UnsupportedResultTypeError(f"MySQL result type is unsupported: {type(value).__name__}")


def normalized_row_size(row: tuple[object, ...]) -> int:
    """Count a row using type-tagged cells plus one delimiter byte per cell/row."""

    return 1 + sum(1 + len(_canonical_cell_bytes(value)) for value in row)


def _safe_provider_detail(error: BaseException, redaction_values: tuple[str, ...]) -> str:
    detail = " ".join(str(error).split())
    for secret in redaction_values:
        if secret:
            detail = detail.replace(secret, "[REDACTED]")
    detail = re.sub(r"(?i)(password\s*[=:]\s*)[^\s,;]+", r"\1[REDACTED]", detail)
    return detail[:_MAX_SAFE_ERROR_CHARACTERS]


def _mysql_error_code(error: BaseException) -> int | None:
    if isinstance(error, pymysql.MySQLError) and error.args:
        code = error.args[0]
        if isinstance(code, int) and not isinstance(code, bool):
            return code
    return None


class ReadOnlyQueryRuntime:
    """Execute exactly one M10 capability over one dedicated reader connection."""

    def __init__(
        self,
        *,
        connection_factory: QueryConnectionFactory,
        limits: RuntimeLimits,
        metadata_sink: ExecutionMetadataSink | None = None,
        expected_guard_policy_version: str = SQL_GUARD_POLICY_VERSION,
        expected_explain_policy_version: str = EXPLAIN_POLICY_VERSION,
    ) -> None:
        if connection_factory.principal_class != ANALYTICS_READONLY_PRINCIPAL:
            raise ValueError("query runtime requires an analytics read-only principal factory")
        if connection_factory.read_timeout_seconds * 1000 <= limits.max_execution_time_ms:
            raise ValueError("client read timeout must exceed the server execution bound")
        self._connection_factory = connection_factory
        self._limits = limits
        self._metadata_sink = metadata_sink or NullExecutionMetadataSink()
        self._expected_guard_policy_version = expected_guard_policy_version
        self._expected_explain_policy_version = expected_explain_policy_version

    def execute(self, query: GuardedQuery) -> ExecutionResult:
        """Consume a GuardedQuery only; the candidate SQL is never transformed."""

        if not isinstance(query, GuardedQuery):
            raise CapabilityIntegrityError("query runtime accepts GuardedQuery only")
        try:
            query.verify_integrity(
                expected_guard_policy_version=self._expected_guard_policy_version,
                expected_explain_policy_version=self._expected_explain_policy_version,
            )
        except (AttributeError, TypeError, ValueError) as error:
            raise CapabilityIntegrityError("GuardedQuery integrity validation failed") from error
        if query.execution_namespace != self._connection_factory.database_schema:
            raise CapabilityIntegrityError(
                "GuardedQuery execution namespace does not match the query runtime"
            )

        execution_id = str(uuid.uuid4())
        started_at = datetime.now(UTC)
        started_clock = time.monotonic()
        connection: Connection | None = None
        attempt_count = 0
        try:
            connection = self._connection_factory.connect()
            self._configure_and_verify_session(connection)
            attempt_count = 1
            result, result_bytes = self._execute_once(connection, query)
            result_fingerprint = execution_result_fingerprint(result)
        except RuntimeExecutionError as error:
            self._record_failure(
                query=query,
                execution_id=execution_id,
                started_at=started_at,
                started_clock=started_clock,
                attempt_count=attempt_count,
                error=error,
            )
            raise
        except (pymysql.MySQLError, OSError) as error:
            mapped = self._map_database_error(error)
            self._record_failure(
                query=query,
                execution_id=execution_id,
                started_at=started_at,
                started_clock=started_clock,
                attempt_count=attempt_count,
                error=mapped,
            )
            raise mapped from error
        finally:
            if connection is not None:
                with suppress(pymysql.MySQLError):
                    connection.close()

        completed_at = datetime.now(UTC)
        self._metadata_sink.record(
            self._metadata(
                query=query,
                execution_id=execution_id,
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=result.duration_ms,
                attempt_count=attempt_count,
                returned_row_count=result.returned_row_count,
                returned_result_bytes=result_bytes,
                truncated=result.truncated,
                result_fingerprint=result_fingerprint,
                outcome=ExecutionOutcome.SUCCEEDED,
            )
        )
        return result

    def _configure_and_verify_session(self, connection: Connection) -> None:
        cursor = connection.cursor()
        try:
            cursor.execute("SET SESSION TRANSACTION READ ONLY")
            cursor.execute(
                "SET SESSION max_execution_time = %s",
                (self._limits.max_execution_time_ms,),
            )
            cursor.execute(
                "SELECT DATABASE(), CURRENT_USER(), "
                "@@SESSION.transaction_read_only, @@SESSION.max_execution_time"
            )
            row = cursor.fetchone()
            trailing = cursor.fetchone()
        finally:
            cursor.close()
        if row is None or trailing is not None or len(row) != 4:
            raise DatabaseExecutionError("MySQL session verification returned an invalid shape")
        schema, principal, read_only, max_execution_time = row
        principal_name = str(principal).split("@", maxsplit=1)[0]
        if (
            schema != self._connection_factory.database_schema
            or principal_name != self._connection_factory.principal_name
            or read_only not in (True, 1)
            or max_execution_time != self._limits.max_execution_time_ms
        ):
            raise DatabaseExecutionError("MySQL query session policy verification failed")
        connection.rollback()

    def _execute_once(
        self,
        connection: Connection,
        query: GuardedQuery,
    ) -> tuple[ExecutionResult, int]:
        cursor: Cursor | None = None
        abandon_cursor = False
        started_clock = time.monotonic()
        try:
            cursor = connection.cursor(SSCursor)
            cursor.execute(query.sql)
            columns = self._actual_columns(cursor)
            rows: list[list[Any]] = []
            result_bytes = 0
            truncated = False
            for index in range(self._limits.max_result_rows + 1):
                raw_row = cursor.fetchone()
                if raw_row is None:
                    break
                if index == self._limits.max_result_rows:
                    truncated = True
                    abandon_cursor = True
                    break
                if not isinstance(raw_row, tuple) or len(raw_row) != len(columns):
                    raise ResultDecodingError("MySQL result row shape did not match metadata")
                row_size = normalized_row_size(raw_row)
                if result_bytes + row_size > self._limits.max_result_bytes:
                    truncated = True
                    abandon_cursor = True
                    break
                rows.append(list(raw_row))
                result_bytes += row_size
            duration_ms = max(0, int((time.monotonic() - started_clock) * 1000))
            return (
                ExecutionResult(
                    version="v0.1",
                    columns=columns,
                    rows=rows,
                    returned_row_count=len(rows),
                    duration_ms=duration_ms,
                    truncated=truncated,
                ),
                result_bytes,
            )
        except (RuntimeExecutionError, pymysql.MySQLError, OSError):
            abandon_cursor = True
            raise
        finally:
            if cursor is not None and not abandon_cursor:
                with suppress(pymysql.MySQLError):
                    cursor.close()

    @staticmethod
    def _actual_columns(cursor: Cursor) -> list[str]:
        description = cursor.description
        if description is None or not description:
            raise ResultDecodingError("MySQL query returned no column metadata")
        columns: list[str] = []
        for field in description:
            if not field or not isinstance(field[0], str) or not field[0].strip():
                raise ResultDecodingError("MySQL column metadata is invalid")
            columns.append(field[0])
        return columns

    def _map_database_error(self, error: BaseException) -> RuntimeExecutionError:
        code = _mysql_error_code(error)
        detail = _safe_provider_detail(error, self._connection_factory.redaction_values)
        if code in _QUERY_TIMEOUT_MYSQL_CODES or isinstance(error, (TimeoutError, socket.timeout)):
            return QueryTimeoutError("MySQL query exceeded its execution bound", safe_detail=detail)
        if code in _UNAVAILABLE_MYSQL_CODES:
            return DatabaseUnavailableError(
                "MySQL query runtime is unavailable", safe_detail=detail
            )
        return DatabaseExecutionError("MySQL rejected query execution", safe_detail=detail)

    def _record_failure(
        self,
        *,
        query: GuardedQuery,
        execution_id: str,
        started_at: datetime,
        started_clock: float,
        attempt_count: int,
        error: RuntimeExecutionError,
    ) -> None:
        completed_at = datetime.now(UTC)
        self._metadata_sink.record(
            self._metadata(
                query=query,
                execution_id=execution_id,
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=max(0, int((time.monotonic() - started_clock) * 1000)),
                attempt_count=attempt_count,
                returned_row_count=0,
                returned_result_bytes=0,
                truncated=False,
                result_fingerprint=None,
                outcome=ExecutionOutcome.FAILED,
                error_code=error.code,
                error_detail=error.safe_detail,
            )
        )

    def _metadata(
        self,
        *,
        query: GuardedQuery,
        execution_id: str,
        started_at: datetime,
        completed_at: datetime,
        duration_ms: int,
        attempt_count: int,
        returned_row_count: int,
        returned_result_bytes: int,
        truncated: bool,
        result_fingerprint: str | None,
        outcome: ExecutionOutcome,
        error_code: str | None = None,
        error_detail: str | None = None,
    ) -> ExecutionMetadata:
        return ExecutionMetadata(
            version=EXECUTION_METADATA_VERSION,
            execution_id=execution_id,
            guarded_query_fingerprint=query.capability_fingerprint,
            sql_digest=query.sql_digest,
            query_plan_fingerprint=query.query_plan_fingerprint,
            planner_context_fingerprint=query.planner_context_fingerprint,
            execution_namespace=query.execution_namespace,
            guard_policy_version=query.guard_policy_version,
            explain_policy_version=query.explain_policy_version,
            physical_tables=tuple(table.qualified_name for table in query.physical_tables),
            database_schema=self._connection_factory.database_schema,
            database_principal_class=self._connection_factory.principal_class,
            max_execution_time_ms=self._limits.max_execution_time_ms,
            client_read_timeout_seconds=self._connection_factory.read_timeout_seconds,
            max_result_rows=self._limits.max_result_rows,
            max_result_bytes=self._limits.max_result_bytes,
            result_byte_accounting_version=RESULT_BYTE_ACCOUNTING_VERSION,
            result_fingerprint_version=RESULT_FINGERPRINT_VERSION,
            result_fingerprint=result_fingerprint,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            execution_attempt_count=attempt_count,
            returned_row_count=returned_row_count,
            returned_result_bytes=returned_result_bytes,
            truncated=truncated,
            outcome=outcome,
            error_code=error_code,
            error_detail=error_detail,
        )
