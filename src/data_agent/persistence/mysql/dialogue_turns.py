"""Atomic MySQL persistence boundary for one successful dialogue turn."""

from __future__ import annotations

from typing import cast

import pymysql

from data_agent.config import Settings
from data_agent.contracts.message import Message, MessageRole
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
from data_agent.persistence.mysql.sessions import _session_from_row
from data_agent.persistence.ports import (
    DialogueTurnSnapshot,
    StoredDialogueTurn,
    StoredMessage,
    StoredSession,
)


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
        return StoredDialogueTurn(
            session=StoredSession(session=session, revision=expected_revision + 1),
            user_message=stored_user,
            assistant_message=stored_assistant,
        )
