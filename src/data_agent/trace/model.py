"""Bounded trace records that expose evidence, never hidden reasoning."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from data_agent.contracts.base import AwareDateTime, NonEmptyString
from data_agent.trace.errors import TracePayloadError

TRACE_SCHEMA_VERSION = "trace-event-v0.1"
TRACE_PAYLOAD_MAX_BYTES = 65_536


class TraceStage(StrEnum):
    RUN = "RUN"
    DIALOGUE = "DIALOGUE"
    RETRIEVAL = "RETRIEVAL"
    PLANNING = "PLANNING"
    SQL_ADMISSION = "SQL_ADMISSION"
    EXECUTION = "EXECUTION"
    VERIFICATION = "VERIFICATION"
    REPAIR = "REPAIR"
    SYNTHESIS = "SYNTHESIS"


class TraceEventType(StrEnum):
    RUN_RECEIVED = "RUN_RECEIVED"
    DIALOGUE_COMPLETED = "DIALOGUE_COMPLETED"
    RETRIEVAL_COMPLETED = "RETRIEVAL_COMPLETED"
    PLANNING_COMPLETED = "PLANNING_COMPLETED"
    SQL_ADMISSION_COMPLETED = "SQL_ADMISSION_COMPLETED"
    EXECUTION_COMPLETED = "EXECUTION_COMPLETED"
    VERIFICATION_COMPLETED = "VERIFICATION_COMPLETED"
    REPAIR_COMPLETED = "REPAIR_COMPLETED"
    SYNTHESIS_COMPLETED = "SYNTHESIS_COMPLETED"
    RUN_TERMINATED = "RUN_TERMINATED"


EVENT_STAGE: dict[TraceEventType, TraceStage] = {
    TraceEventType.RUN_RECEIVED: TraceStage.RUN,
    TraceEventType.DIALOGUE_COMPLETED: TraceStage.DIALOGUE,
    TraceEventType.RETRIEVAL_COMPLETED: TraceStage.RETRIEVAL,
    TraceEventType.PLANNING_COMPLETED: TraceStage.PLANNING,
    TraceEventType.SQL_ADMISSION_COMPLETED: TraceStage.SQL_ADMISSION,
    TraceEventType.EXECUTION_COMPLETED: TraceStage.EXECUTION,
    TraceEventType.VERIFICATION_COMPLETED: TraceStage.VERIFICATION,
    TraceEventType.REPAIR_COMPLETED: TraceStage.REPAIR,
    TraceEventType.SYNTHESIS_COMPLETED: TraceStage.SYNTHESIS,
    TraceEventType.RUN_TERMINATED: TraceStage.RUN,
}

_ALLOWED_PAYLOAD_KEYS: dict[TraceEventType, frozenset[str]] = {
    TraceEventType.RUN_RECEIVED: frozenset({"outcome", "initial_status"}),
    TraceEventType.DIALOGUE_COMPLETED: frozenset(
        {
            "outcome",
            "action",
            "prompt_version",
            "requirement_status",
            "requirement_fingerprint",
            "requirement_version",
            "user_message_id",
            "assistant_message_id",
            "error_code",
        }
    ),
    TraceEventType.RETRIEVAL_COMPLETED: frozenset(
        {
            "outcome",
            "index_fingerprint",
            "result_fingerprint",
            "seed_tables",
            "selected_tables",
            "graph_expansion_count",
            "ranks",
            "error_code",
        }
    ),
    TraceEventType.PLANNING_COMPLETED: frozenset(
        {
            "outcome",
            "planner_context_fingerprint",
            "query_plan_fingerprint",
            "retrieval_index_fingerprint",
            "prompt_version",
            "model_fingerprint",
            "runtime_version",
            "allowed_tables",
            "planned_tables",
            "error_code",
        }
    ),
    TraceEventType.SQL_ADMISSION_COMPLETED: frozenset(
        {
            "outcome",
            "guard_status",
            "guard_violations",
            "parse_succeeded",
            "table_scope_compliant",
            "referenced_tables",
            "candidate_capability_fingerprint",
            "guarded_query_fingerprint",
            "sql_digest",
            "guard_policy_version",
            "explain_policy_version",
            "explain_accepted",
            "explain_rejection_reason",
            "failure_stage",
            "failure_category",
            "failure_code",
            "query_plan_fingerprint",
            "planner_context_fingerprint",
            "error_code",
        }
    ),
    TraceEventType.EXECUTION_COMPLETED: frozenset(
        {
            "outcome",
            "columns",
            "execution_metadata_version",
            "execution_id",
            "guarded_query_fingerprint",
            "query_plan_fingerprint",
            "planner_context_fingerprint",
            "sql_digest",
            "execution_namespace",
            "principal_class",
            "result_fingerprint_version",
            "result_fingerprint",
            "returned_row_count",
            "returned_result_bytes",
            "truncated",
            "execution_attempt_count",
            "error_code",
            "failure_code",
        }
    ),
    TraceEventType.VERIFICATION_COMPLETED: frozenset(
        {
            "outcome",
            "verification_policy_version",
            "evidence",
            "applied_checks",
            "failed_checks",
            "coverage_gaps",
            "failure_code",
            "failure_category",
            "execution_id",
            "result_fingerprint",
            "error_code",
        }
    ),
    TraceEventType.REPAIR_COMPLETED: frozenset(
        {
            "version",
            "repair_policy_version",
            "source_run_id",
            "prompt_version",
            "attempt",
            "max_attempts",
            "eligible",
            "failure_fingerprint",
            "original_query_plan_fingerprint",
            "replacement_query_plan_fingerprint",
            "planner_context_fingerprint",
            "model_fingerprint",
            "runtime_version",
            "outcome",
            "final_verification_evidence",
            "error_code",
        }
    ),
    TraceEventType.SYNTHESIS_COMPLETED: frozenset(
        {
            "outcome",
            "prompt_version",
            "mode",
            "limitation",
            "evidence_refs",
            "evidence_refs_fingerprint",
            "answer_proposal_fingerprint",
            "assistant_message_id",
            "error_code",
        }
    ),
    TraceEventType.RUN_TERMINATED: frozenset({"outcome", "terminal_status", "error_code"}),
}

_FORBIDDEN_KEYS = {
    "answer",
    "answer_text",
    "chain_of_thought",
    "credential",
    "credentials",
    "message_content",
    "password",
    "raw_rows",
    "reasoning",
    "result_rows",
    "rows",
    "scratchpad",
    "secret",
}


def _inspect_payload(value: object, *, path: str = "payload") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().lower()
            if normalized in _FORBIDDEN_KEYS or "password" in normalized or "secret" in normalized:
                raise TracePayloadError(f"trace payload contains forbidden field {path}.{key}")
            _inspect_payload(child, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _inspect_payload(child, path=f"{path}[{index}]")


def canonical_payload(payload: dict[str, Any]) -> bytes:
    _inspect_payload(payload)
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise TracePayloadError("trace payload is not canonical JSON") from error
    if len(encoded) > TRACE_PAYLOAD_MAX_BYTES:
        raise TracePayloadError("trace payload exceeds the bounded byte limit")
    return encoded


def trace_payload_fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_payload(payload)).hexdigest()


class _TraceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class TraceEventDraft(_TraceModel):
    id: NonEmptyString
    session_id: NonEmptyString
    run_id: NonEmptyString
    attempt: int = Field(ge=0, le=1)
    stage: TraceStage
    event_type: TraceEventType
    schema_version: Literal["trace-event-v0.1"] = "trace-event-v0.1"
    payload: dict[str, Any]
    payload_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    occurred_at: AwareDateTime

    @field_validator("payload")
    @classmethod
    def payload_is_bounded_evidence(cls, value: dict[str, Any]) -> dict[str, Any]:
        canonical_payload(value)
        return value

    @model_validator(mode="after")
    def identity_is_coherent(self) -> Self:
        if EVENT_STAGE[self.event_type] is not self.stage:
            raise ValueError("trace event type does not match its stage")
        unknown_keys = set(self.payload) - _ALLOWED_PAYLOAD_KEYS[self.event_type]
        if unknown_keys:
            raise TracePayloadError(
                f"trace payload keys are not allowed for {self.event_type.value}: "
                f"{sorted(unknown_keys)}"
            )
        actual = trace_payload_fingerprint(self.payload)
        if self.payload_fingerprint is not None and self.payload_fingerprint != actual:
            raise ValueError("trace payload fingerprint mismatch")
        object.__setattr__(self, "payload_fingerprint", actual)
        return self


class TraceEvent(TraceEventDraft):
    sequence: int = Field(ge=1)

    @property
    def timestamp(self) -> datetime:
        return self.occurred_at
