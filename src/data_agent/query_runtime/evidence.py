"""Metadata-only M11 evidence, deliberately separate from result rows."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from data_agent.contracts.execution import ExecutionResult

EXECUTION_METADATA_VERSION = "execution-metadata-v0.2"
RESULT_BYTE_ACCOUNTING_VERSION = "result-byte-budget-v0.1"
RESULT_FINGERPRINT_VERSION = "execution-result-fingerprint-v0.1"

type _CanonicalScalar = str | bool | None


def _canonical_result_cell(value: object) -> dict[str, _CanonicalScalar]:
    if value is None:
        return {"type": "null", "value": None}
    if isinstance(value, bool):
        return {"type": "bool", "value": value}
    if isinstance(value, int):
        return {"type": "int", "value": str(value)}
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("ExecutionResult contains a non-finite Decimal")
        return {"type": "decimal", "value": str(value)}
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("ExecutionResult contains a non-finite float")
        return {"type": "float", "value": value.hex()}
    if isinstance(value, datetime):
        return {"type": "datetime", "value": value.isoformat(timespec="microseconds")}
    if isinstance(value, date):
        return {"type": "date", "value": value.isoformat()}
    if isinstance(value, str):
        return {"type": "string", "value": value}
    raise ValueError(f"ExecutionResult contains an unsupported type: {type(value).__name__}")


def execution_result_fingerprint(result: ExecutionResult) -> str:
    """Bind exact bounded result evidence without including nondeterministic execution facts."""

    payload = {
        "fingerprint_version": RESULT_FINGERPRINT_VERSION,
        "execution_result_version": result.version,
        "columns": [str(column) for column in result.columns],
        "rows": [[_canonical_result_cell(value) for value in row] for row in result.rows],
        "returned_row_count": result.returned_row_count,
        "truncated": result.truncated,
    }
    canonical = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ExecutionOutcome(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class ExecutionMetadata:
    """Bounded execution facts suitable for a future metadata artifact."""

    version: str
    execution_id: str
    guarded_query_fingerprint: str
    sql_digest: str
    query_plan_fingerprint: str
    planner_context_fingerprint: str
    execution_namespace: str
    guard_policy_version: str
    explain_policy_version: str
    physical_tables: tuple[str, ...]
    database_schema: str
    database_principal_class: str
    max_execution_time_ms: int
    client_read_timeout_seconds: int
    max_result_rows: int
    max_result_bytes: int
    result_byte_accounting_version: str
    result_fingerprint_version: str
    result_fingerprint: str | None
    started_at: datetime
    completed_at: datetime
    duration_ms: int
    execution_attempt_count: int
    returned_row_count: int
    returned_result_bytes: int
    truncated: bool
    outcome: ExecutionOutcome
    error_code: str | None = None
    error_detail: str | None = None


class ExecutionMetadataSink(Protocol):
    """Receives metadata only; this boundary has no result-row parameter."""

    def record(self, metadata: ExecutionMetadata) -> None: ...


class NullExecutionMetadataSink:
    def record(self, metadata: ExecutionMetadata) -> None:
        del metadata
