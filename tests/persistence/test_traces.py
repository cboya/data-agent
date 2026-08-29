from __future__ import annotations

import pymysql
import pytest

from data_agent.config import Settings
from data_agent.contracts.run import RunStatus
from data_agent.persistence.mysql.common import control_connection
from data_agent.persistence.mysql.dialogue_turns import MySQLDialogueTurnStore
from data_agent.persistence.mysql.runs import MySQLRunRepository
from data_agent.persistence.mysql.sessions import MySQLSessionRepository
from data_agent.persistence.mysql.traces import MySQLTraceRepository
from data_agent.trace.errors import TraceIntegrityError
from data_agent.trace.model import TraceEventDraft, TraceEventType, TraceStage
from tests.persistence.factories import run, session, timestamp, unique_id

pytestmark = pytest.mark.integration


def _context(settings: Settings) -> tuple[str, str, MySQLRunRepository]:
    session_id = str(MySQLSessionRepository(settings).create(session()).session.id)
    runs = MySQLRunRepository(settings)
    run_id = str(runs.create(run(session_id)).id)
    return session_id, run_id, runs


def _draft(
    session_id: str,
    run_id: str,
    event_type: TraceEventType,
    *,
    stage: TraceStage,
    payload: dict[str, object],
) -> TraceEventDraft:
    return TraceEventDraft(
        id=unique_id("trace"),
        session_id=session_id,
        run_id=run_id,
        attempt=0,
        stage=stage,
        event_type=event_type,
        payload=payload,
        occurred_at=timestamp(),
    )


def test_trace_is_append_only_ordered_and_revalidated(settings: Settings) -> None:
    session_id, run_id, _ = _context(settings)
    repository = MySQLTraceRepository(settings)
    received = _draft(
        session_id,
        run_id,
        TraceEventType.RUN_RECEIVED,
        stage=TraceStage.RUN,
        payload={"outcome": "RECEIVED"},
    )
    dialogue = _draft(
        session_id,
        run_id,
        TraceEventType.DIALOGUE_COMPLETED,
        stage=TraceStage.DIALOGUE,
        payload={"outcome": "SUCCEEDED"},
    )

    inserted = repository.append_many((received, dialogue))
    reloaded = repository.list_for_run(run_id)

    assert [event.sequence for event in inserted] == [1, 2]
    assert reloaded == list(inserted)
    assert not hasattr(repository, "update")
    assert not hasattr(repository, "delete")


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE agent_trace_event SET payload_json = payload_json WHERE id = %s",
        "DELETE FROM agent_trace_event WHERE id = %s",
    ],
)
def test_control_principal_cannot_mutate_trace(
    settings: Settings,
    statement: str,
) -> None:
    session_id, run_id, _ = _context(settings)
    event = MySQLTraceRepository(settings).append(
        _draft(
            session_id,
            run_id,
            TraceEventType.RUN_RECEIVED,
            stage=TraceStage.RUN,
            payload={"outcome": "RECEIVED"},
        )
    )
    connection = control_connection(settings)
    try:
        with connection.cursor() as cursor, pytest.raises(pymysql.MySQLError) as error:
            cursor.execute(statement, (event.id,))
    finally:
        connection.close()
    assert error.value.args[0] == 1142


def test_failed_terminal_trace_validation_rolls_back_run_and_event(settings: Settings) -> None:
    session_id, run_id, runs = _context(settings)
    traces = MySQLTraceRepository(settings)
    traces.append(
        _draft(
            session_id,
            run_id,
            TraceEventType.RUN_RECEIVED,
            stage=TraceStage.RUN,
            payload={"outcome": "RECEIVED"},
        )
    )
    runs.transition(run_id, RunStatus.UNDERSTANDING, transitioned_at=timestamp())
    mismatched_terminal = _draft(
        session_id,
        run_id,
        TraceEventType.RUN_TERMINATED,
        stage=TraceStage.RUN,
        payload={"terminal_status": RunStatus.COMPLETED.value},
    )

    with pytest.raises(TraceIntegrityError, match="does not match durable Run"):
        MySQLDialogueTurnStore(settings).terminate_run_with_trace(
            run_id=run_id,
            target=RunStatus.FAILED,
            completed_at=timestamp(),
            error_code="EXPECTED_FAILURE",
            trace_events=(mismatched_terminal,),
        )

    assert runs.get(run_id).status is RunStatus.UNDERSTANDING
    assert [event.event_type for event in traces.list_for_run(run_id)] == [
        TraceEventType.RUN_RECEIVED
    ]
