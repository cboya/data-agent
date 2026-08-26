"""Atomic MySQL persistence boundary for one successful dialogue turn."""

from __future__ import annotations

from typing import cast

import pymysql

from data_agent.config import Settings
from data_agent.contracts.base import AwareDateTime
from data_agent.contracts.message import Message, MessageRole
from data_agent.contracts.requirement import RequirementStatus
from data_agent.contracts.run import Run, RunStatus
from data_agent.contracts.session import Session
from data_agent.persistence.errors import (
    OptimisticConcurrencyError,
    PersistenceInvariantError,
    RecordNotFoundError,
)
from data_agent.persistence.mysql.common import (
    control_connection,
    from_database_datetime,
    raise_write_error,
    require_int,
    to_database_datetime,
)
from data_agent.persistence.mysql.messages import _message_from_row
from data_agent.persistence.mysql.runs import _run_from_row
from data_agent.persistence.mysql.sessions import _session_from_row
from data_agent.persistence.mysql.traces import _insert_trace_drafts, _load_trace_rows
from data_agent.persistence.ports import (
    DialogueTurnSnapshot,
    StoredDialogueTurn,
    StoredMessage,
    StoredRunCompletion,
    StoredRunDialogueTurn,
    StoredSession,
)
from data_agent.run_state import TERMINAL_RUN_STATUSES, RunStateMachine
from data_agent.trace.model import TraceEventDraft
from data_agent.trace.policy import TraceCompletenessPolicy


def _validate_messages(
    session: Session,
    user_message: Message,
    assistant_message: Message | None,
) -> None:
    if user_message.session_id != session.id or user_message.role is not MessageRole.USER:
        raise PersistenceInvariantError("dialogue turn requires one matching USER message")
    if assistant_message is not None:
        if (
            assistant_message.session_id != session.id
            or assistant_message.role is not MessageRole.ASSISTANT
        ):
            raise PersistenceInvariantError(
                "dialogue turn clarification must be a matching ASSISTANT message"
            )
        if assistant_message.created_at < user_message.created_at:
            raise PersistenceInvariantError("assistant clarification cannot precede user message")


def _insert_message(
    cursor: pymysql.cursors.Cursor,
    message: Message,
    *,
    sequence: int,
) -> StoredMessage:
    cursor.execute(
        "INSERT INTO agent_message "
        "(id, session_id, sequence, role, content, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (
            message.id,
            message.session_id,
            sequence,
            message.role.value,
            message.content,
            to_database_datetime(message.created_at),
        ),
    )
    return StoredMessage(message=message, sequence=sequence)


class MySQLDialogueTurnStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def load(self, session_id: str) -> DialogueTurnSnapshot:
        connection = control_connection(self._settings, autocommit=False)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, status, requirement_json, revision, created_at, updated_at "
                    "FROM agent_session WHERE id = %s",
                    (session_id,),
                )
                session_row = cursor.fetchone()
                if session_row is None:
                    raise RecordNotFoundError(f"Session {session_id} does not exist")
                cursor.execute(
                    "SELECT id, session_id, sequence, role, content, created_at "
                    "FROM agent_message WHERE session_id = %s AND role = 'assistant' "
                    "ORDER BY sequence DESC LIMIT 1",
                    (session_id,),
                )
                assistant_row = cursor.fetchone()
            connection.rollback()
        finally:
            connection.close()
        return DialogueTurnSnapshot(
            session=_session_from_row(cast(tuple[object, ...], session_row)),
            last_assistant=(
                _message_from_row(cast(tuple[object, ...], assistant_row))
                if assistant_row is not None
                else None
            ),
        )

    def commit(
        self,
        *,
        session: Session,
        expected_revision: int,
        user_message: Message,
        assistant_message: Message | None,
    ) -> StoredDialogueTurn:
        turn, _ = self._commit(
            session=session,
            expected_revision=expected_revision,
            user_message=user_message,
            assistant_message=assistant_message,
            run_id=None,
            target=None,
        )
        return turn

    def commit_dialogue_with_run(
        self,
        *,
        session: Session,
        expected_revision: int,
        user_message: Message,
        assistant_message: Message | None,
        run_id: str,
        target: RunStatus,
        trace_events: tuple[TraceEventDraft, ...],
    ) -> StoredRunDialogueTurn:
        expected = {
            RunStatus.CLARIFYING: (RequirementStatus.CLARIFYING, True),
            RunStatus.RETRIEVING: (RequirementStatus.READY, False),
            RunStatus.FAILED: (RequirementStatus.FAILED, False),
        }.get(target)
        if expected is None:
            raise PersistenceInvariantError("dialogue may only enter a frozen post-M8 Run state")
        if target in TERMINAL_RUN_STATUSES and not trace_events:
            raise PersistenceInvariantError("terminal dialogue outcome requires trace evidence")
        requirement_status, requires_assistant = expected
        if session.requirement.status is not requirement_status:
            raise PersistenceInvariantError("dialogue RequirementState does not match Run target")
        if (assistant_message is not None) is not requires_assistant:
            raise PersistenceInvariantError("dialogue assistant message does not match Run target")
        turn, updated_run = self._commit(
            session=session,
            expected_revision=expected_revision,
            user_message=user_message,
            assistant_message=assistant_message,
            run_id=run_id,
            target=target,
            trace_events=trace_events,
        )
        if updated_run is None:
            raise AssertionError("atomic dialogue commit did not update the Run")
        return StoredRunDialogueTurn(turn=turn, run=updated_run)

    def _commit(
        self,
        *,
        session: Session,
        expected_revision: int,
        user_message: Message,
        assistant_message: Message | None,
        run_id: str | None,
        target: RunStatus | None,
        trace_events: tuple[TraceEventDraft, ...] = (),
    ) -> tuple[StoredDialogueTurn, Run | None]:
        if expected_revision < 0:
            raise ValueError("expected Session revision cannot be negative")
        _validate_messages(session, user_message, assistant_message)
        created_at = to_database_datetime(session.created_at)
        updated_at = to_database_datetime(session.updated_at)
        connection = control_connection(self._settings, autocommit=False)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT revision, created_at, updated_at FROM agent_session "
                    "WHERE id = %s FOR UPDATE",
                    (session.id,),
                )
                current = cursor.fetchone()
                if current is None:
                    raise RecordNotFoundError(f"Session {session.id} does not exist")
                current_row = cast(tuple[object, ...], current)
                current_revision = require_int(current_row[0], field="agent_session.revision")
                if current_revision != expected_revision:
                    raise OptimisticConcurrencyError(
                        f"Session {session.id} revision is {current_revision}, "
                        f"expected {expected_revision}"
                    )
                persisted_created_at = from_database_datetime(
                    current_row[1], field="agent_session.created_at"
                )
                persisted_updated_at = from_database_datetime(
                    current_row[2], field="agent_session.updated_at"
                )
                if to_database_datetime(persisted_created_at) != created_at:
                    raise PersistenceInvariantError("Session created_at is immutable")
                if updated_at < to_database_datetime(persisted_updated_at):
                    raise PersistenceInvariantError("Session updated_at cannot move backwards")

                updated_run: Run | None = None
                if run_id is not None and target is not None:
                    cursor.execute(
                        "SELECT id, session_id, status, repair_count, started_at, "
                        "completed_at, error_code FROM agent_run WHERE id = %s FOR UPDATE",
                        (run_id,),
                    )
                    run_row = cursor.fetchone()
                    if run_row is None:
                        raise RecordNotFoundError(f"Run {run_id} does not exist")
                    current_run = _run_from_row(cast(tuple[object, ...], run_row))
                    if current_run.session_id != session.id:
                        raise PersistenceInvariantError("dialogue Run belongs to another Session")
                    RunStateMachine.transition(current_run.status, target)
                    completed_at = session.updated_at if target in TERMINAL_RUN_STATUSES else None
                    updated_run = Run.model_validate(
                        {
                            **current_run.model_dump(mode="python"),
                            "status": target,
                            "completed_at": completed_at,
                            "error_code": "DIALOGUE_CANNOT_RESOLVE"
                            if target is RunStatus.FAILED
                            else None,
                        }
                    )
                    RunStateMachine.require_consistent(updated_run)

                cursor.execute(
                    "UPDATE agent_session SET status = %s, requirement_json = %s, "
                    "updated_at = %s, revision = revision + 1 "
                    "WHERE id = %s AND revision = %s",
                    (
                        session.status.value,
                        session.requirement.model_dump_json(),
                        updated_at,
                        session.id,
                        expected_revision,
                    ),
                )
                if cursor.rowcount != 1:
                    raise OptimisticConcurrencyError(
                        f"Session {session.id} changed during dialogue commit"
                    )
                cursor.execute(
                    "SELECT CAST(COALESCE(MAX(sequence), 0) AS UNSIGNED) "
                    "FROM agent_message WHERE session_id = %s",
                    (session.id,),
                )
                sequence_row = cursor.fetchone()
                if sequence_row is None:
                    raise RuntimeError("message sequence query returned no row")
                next_sequence = require_int(sequence_row[0], field="agent_message.sequence") + 1
                stored_user = _insert_message(cursor, user_message, sequence=next_sequence)
                stored_assistant = (
                    _insert_message(
                        cursor,
                        assistant_message,
                        sequence=next_sequence + 1,
                    )
                    if assistant_message is not None
                    else None
                )
                if updated_run is not None:
                    cursor.execute(
                        "UPDATE agent_run SET status = %s, completed_at = %s, "
                        "error_code = %s WHERE id = %s",
                        (
                            updated_run.status.value,
                            None
                            if updated_run.completed_at is None
                            else to_database_datetime(updated_run.completed_at),
                            updated_run.error_code,
                            updated_run.id,
                        ),
                    )
                    _insert_trace_drafts(cursor, run=updated_run, drafts=trace_events)
                    if trace_events and updated_run.status in TERMINAL_RUN_STATUSES:
                        TraceCompletenessPolicy().validate(
                            updated_run,
                            _load_trace_rows(cursor, str(updated_run.id)),
                        )
            connection.commit()
        except (OptimisticConcurrencyError, PersistenceInvariantError, RecordNotFoundError):
            connection.rollback()
            raise
        except pymysql.MySQLError as error:
            connection.rollback()
            raise_write_error(error, record=f"Dialogue turn for Session {session.id}")
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return (
            StoredDialogueTurn(
                session=StoredSession(session=session, revision=expected_revision + 1),
                user_message=stored_user,
                assistant_message=stored_assistant,
            ),
            updated_run,
        )

    def complete_run_with_message(
        self,
        *,
        run_id: str,
        assistant_message: Message,
        completed_at: AwareDateTime,
        trace_events: tuple[TraceEventDraft, ...],
    ) -> StoredRunCompletion:
        if assistant_message.role is not MessageRole.ASSISTANT:
            raise PersistenceInvariantError("Run completion requires one ASSISTANT message")
        if not trace_events:
            raise PersistenceInvariantError("Run completion requires terminal trace evidence")
        connection = control_connection(self._settings, autocommit=False)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT revision FROM agent_session WHERE id = %s FOR UPDATE",
                    (assistant_message.session_id,),
                )
                if cursor.fetchone() is None:
                    raise RecordNotFoundError(
                        f"Session {assistant_message.session_id} does not exist"
                    )
                cursor.execute(
                    "SELECT id, session_id, status, repair_count, started_at, "
                    "completed_at, error_code FROM agent_run WHERE id = %s FOR UPDATE",
                    (run_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    raise RecordNotFoundError(f"Run {run_id} does not exist")
                current = _run_from_row(cast(tuple[object, ...], row))
                if current.session_id != assistant_message.session_id:
                    raise PersistenceInvariantError("completion message belongs to another Session")
                if assistant_message.created_at != completed_at:
                    raise PersistenceInvariantError(
                        "completion message and Run must share one commit timestamp"
                    )
                RunStateMachine.transition(current.status, RunStatus.COMPLETED)
                updated = Run.model_validate(
                    {
                        **current.model_dump(mode="python"),
                        "status": RunStatus.COMPLETED,
                        "completed_at": completed_at,
                        "error_code": None,
                    }
                )
                RunStateMachine.require_consistent(updated)
                cursor.execute(
                    "SELECT CAST(COALESCE(MAX(sequence), 0) AS UNSIGNED) "
                    "FROM agent_message WHERE session_id = %s",
                    (assistant_message.session_id,),
                )
                sequence_row = cursor.fetchone()
                if sequence_row is None:
                    raise RuntimeError("message sequence query returned no row")
                sequence = require_int(sequence_row[0], field="agent_message.sequence") + 1
                stored_message = _insert_message(cursor, assistant_message, sequence=sequence)
                cursor.execute(
                    "UPDATE agent_run SET status = %s, completed_at = %s, error_code = NULL "
                    "WHERE id = %s",
                    (
                        RunStatus.COMPLETED.value,
                        to_database_datetime(completed_at),
                        run_id,
                    ),
                )
                _insert_trace_drafts(cursor, run=updated, drafts=trace_events)
                if trace_events:
                    TraceCompletenessPolicy().validate(
                        updated,
                        _load_trace_rows(cursor, str(updated.id)),
                    )
            connection.commit()
            return StoredRunCompletion(assistant_message=stored_message, run=updated)
        except (PersistenceInvariantError, RecordNotFoundError, ValueError):
            connection.rollback()
            raise
        except pymysql.MySQLError as error:
            connection.rollback()
            raise_write_error(error, record=f"Run completion {run_id}")
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def terminate_run_with_trace(
        self,
        *,
        run_id: str,
        target: RunStatus,
        completed_at: AwareDateTime,
        error_code: str,
        trace_events: tuple[TraceEventDraft, ...],
    ) -> Run:
        if target not in TERMINAL_RUN_STATUSES or target in {
            RunStatus.COMPLETED,
            RunStatus.CLARIFYING,
        }:
            raise PersistenceInvariantError("failure terminalization requires a failure Run state")
        if not trace_events:
            raise PersistenceInvariantError("failure terminalization requires trace evidence")
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
                current = _run_from_row(cast(tuple[object, ...], row))
                RunStateMachine.transition(current.status, target)
                updated = Run.model_validate(
                    {
                        **current.model_dump(mode="python"),
                        "status": target,
                        "completed_at": completed_at,
                        "error_code": error_code,
                    }
                )
                RunStateMachine.require_consistent(updated)
                cursor.execute(
                    "UPDATE agent_run SET status = %s, completed_at = %s, error_code = %s "
                    "WHERE id = %s",
                    (
                        target.value,
                        to_database_datetime(completed_at),
                        error_code,
                        run_id,
                    ),
                )
                _insert_trace_drafts(cursor, run=updated, drafts=trace_events)
                TraceCompletenessPolicy().validate(
                    updated,
                    _load_trace_rows(cursor, str(updated.id)),
                )
            connection.commit()
            return updated
        except (PersistenceInvariantError, RecordNotFoundError, ValueError):
            connection.rollback()
            raise
        except pymysql.MySQLError as error:
            connection.rollback()
            raise_write_error(error, record=f"Run terminalization {run_id}")
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
