"""Metadata-only M11 evidence, deliberately separate from result rows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

EXECUTION_METADATA_VERSION = "execution-metadata-v0.1"
RESULT_BYTE_ACCOUNTING_VERSION = "result-byte-budget-v0.1"


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
