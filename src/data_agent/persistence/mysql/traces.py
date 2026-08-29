"""Append-only MySQL repository for bounded M15 trace evidence."""

from __future__ import annotations

import json
from itertools import pairwise
from typing import Any, cast

import pymysql
from pydantic import ValidationError

from data_agent.config import Settings
from data_agent.contracts.run import Run
from data_agent.persistence.errors import CorruptRecordError, RecordNotFoundError
from data_agent.persistence.mysql.common import (
    control_connection,
    corrupt_record,
    from_database_datetime,
    raise_write_error,
    require_int,
    require_string,
    to_database_datetime,
)
from data_agent.persistence.mysql.runs import _run_from_row
from data_agent.run_state import TERMINAL_RUN_STATUSES
from data_agent.trace.model import TraceEvent, TraceEventDraft, TraceEventType

_TRACE_COLUMNS = (
    "id, session_id, run_id, sequence, attempt, stage, event_type, schema_version, "
    "payload_json, payload_fingerprint, occurred_at"
)


def _decode_payload(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return cast(dict[str, Any], value)
    try:
        decoded = json.loads(require_string(value, field="agent_trace_event.payload_json"))
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise corrupt_record("agent_trace_event.payload_json", error) from error
    if not isinstance(decoded, dict):
        raise corrupt_record(
            "agent_trace_event.payload_json", ValueError("trace payload is not an object")
        )
    return cast(dict[str, Any], decoded)


def _trace_from_row(row: tuple[object, ...]) -> TraceEvent:
    try:
        return TraceEvent.model_validate(
            {
                "id": row[0],
                "session_id": row[1],
                "run_id": row[2],
                "sequence": require_int(row[3], field="agent_trace_event.sequence"),
                "attempt": require_int(row[4], field="agent_trace_event.attempt"),
                "stage": row[5],
                "event_type": row[6],
                "schema_version": row[7],
                "payload": _decode_payload(row[8]),
                "payload_fingerprint": row[9],
                "occurred_at": from_database_datetime(
                    row[10], field="agent_trace_event.occurred_at"
                ),
            }
        )
    except (ValidationError, ValueError) as error:
        if isinstance(error, CorruptRecordError):
            raise
        raise corrupt_record("agent_trace_event", error) from error


def _load_trace_rows(
    cursor: pymysql.cursors.Cursor,
    run_id: str,
) -> tuple[TraceEvent, ...]:
    cursor.execute(
        f"SELECT {_TRACE_COLUMNS} FROM agent_trace_event WHERE run_id = %s ORDER BY sequence",
        (run_id,),
    )
    return tuple(_trace_from_row(cast(tuple[object, ...], row)) for row in cursor.fetchall())


def _insert_trace_drafts(
    cursor: pymysql.cursors.Cursor,
    *,
    run: Run,
    drafts: tuple[TraceEventDraft, ...],
) -> tuple[TraceEvent, ...]:
    if not drafts:
        return ()
    if any(draft.run_id != run.id or draft.session_id != run.session_id for draft in drafts):
        raise ValueError("trace draft identity does not match locked Run")
    existing = _load_trace_rows(cursor, str(run.id))
    if tuple(event.sequence for event in existing) != tuple(range(1, len(existing) + 1)):
        raise ValueError("persisted trace sequence is not contiguous")
    if any(event.event_type is TraceEventType.RUN_TERMINATED for event in existing):
        raise ValueError("cannot append after terminal trace evidence")
    terminal_drafts = [
        draft for draft in drafts if draft.event_type is TraceEventType.RUN_TERMINATED
    ]
    if terminal_drafts:
        if (
            run.status not in TERMINAL_RUN_STATUSES
            or len(terminal_drafts) != 1
            or drafts[-1] is not terminal_drafts[0]
        ):
            raise ValueError("terminal trace evidence requires a terminal Run and final position")
    elif run.status in TERMINAL_RUN_STATUSES:
        raise ValueError("terminal Run trace append must include final terminal evidence")
    timestamps = tuple(event.occurred_at for event in existing) + tuple(
        draft.occurred_at for draft in drafts
    )
    if any(later < earlier for earlier, later in pairwise(timestamps)):
        raise ValueError("trace timestamps move backwards")
    next_sequence = len(existing) + 1
    inserted: list[TraceEvent] = []
    for offset, draft in enumerate(drafts):
        event = TraceEvent.model_validate(
            {**draft.model_dump(mode="python"), "sequence": next_sequence + offset}
        )
        cursor.execute(
            "INSERT INTO agent_trace_event "
            "(id, session_id, run_id, sequence, attempt, stage, event_type, schema_version, "
            "payload_json, payload_fingerprint, occurred_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                event.id,
                event.session_id,
                event.run_id,
                event.sequence,
                event.attempt,
                event.stage.value,
                event.event_type.value,
                event.schema_version,
                json.dumps(
                    event.payload,
                    ensure_ascii=True,
                    allow_nan=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                event.payload_fingerprint,
                to_database_datetime(event.occurred_at),
            ),
        )
        inserted.append(event)
    return tuple(inserted)


class MySQLTraceRepository:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def append(self, draft: TraceEventDraft) -> TraceEvent:
        return self.append_many((draft,))[0]

    def append_many(self, drafts: tuple[TraceEventDraft, ...]) -> tuple[TraceEvent, ...]:
        if not drafts:
            return ()
        run_id = str(drafts[0].run_id)
        connection = control_connection(self._settings, autocommit=False)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, session_id, status, repair_count, started_at, completed_at, "
                    "error_code FROM agent_run WHERE id = %s FOR UPDATE",
                    (run_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    raise RecordNotFoundError(f"Run {run_id} does not exist")
                run = _run_from_row(cast(tuple[object, ...], row))
                inserted = _insert_trace_drafts(cursor, run=run, drafts=drafts)
            connection.commit()
            return inserted
        except (RecordNotFoundError, ValidationError, ValueError):
            connection.rollback()
            raise
        except pymysql.MySQLError as error:
            connection.rollback()
            raise_write_error(error, record=f"Trace for Run {run_id}")
        finally:
            connection.close()

    def list_for_run(self, run_id: str) -> list[TraceEvent]:
        connection = control_connection(self._settings)
        try:
            with connection.cursor() as cursor:
                events = _load_trace_rows(cursor, run_id)
        finally:
            connection.close()
        return list(events)
