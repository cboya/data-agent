"""Append-only MySQL Message repository."""

from typing import cast

import pymysql
from pydantic import ValidationError

from data_agent.config import Settings
from data_agent.contracts.message import Message
from data_agent.persistence.errors import CorruptRecordError, RecordNotFoundError
from data_agent.persistence.mysql.common import (
    control_connection,
    corrupt_record,
    from_database_datetime,
    raise_write_error,
    require_int,
    to_database_datetime,
)
from data_agent.persistence.ports import StoredMessage


def _message_from_row(row: tuple[object, ...]) -> StoredMessage:
    try:
        message = Message.model_validate(
            {
                "id": row[0],
                "session_id": row[1],
                "role": row[3],
                "content": row[4],
                "created_at": from_database_datetime(row[5], field="agent_message.created_at"),
            }
        )
        sequence = require_int(row[2], field="agent_message.sequence")
        return StoredMessage(message=message, sequence=sequence)
    except (ValidationError, ValueError) as error:
        if isinstance(error, CorruptRecordError):
            raise
        raise corrupt_record("agent_message", error) from error


class MySQLMessageRepository:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def append(self, message: Message) -> StoredMessage:
        connection = control_connection(self._settings, autocommit=False)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM agent_session WHERE id = %s FOR UPDATE",
                    (message.session_id,),
                )
                if cursor.fetchone() is None:
                    raise RecordNotFoundError(f"Session {message.session_id} does not exist")
                cursor.execute(
                    "SELECT CAST(COALESCE(MAX(sequence), 0) AS UNSIGNED) "
                    "FROM agent_message WHERE session_id = %s",
                    (message.session_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    raise RuntimeError("message sequence query returned no row")
                sequence = require_int(row[0], field="agent_message.sequence") + 1
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
            connection.commit()
        except RecordNotFoundError:
            connection.rollback()
            raise
        except pymysql.MySQLError as error:
            connection.rollback()
            raise_write_error(error, record=f"Message {message.id}")
        finally:
            connection.close()
        return StoredMessage(message=message, sequence=sequence)

    def list_for_session(self, session_id: str) -> list[StoredMessage]:
        connection = control_connection(self._settings)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, session_id, sequence, role, content, created_at "
                    "FROM agent_message WHERE session_id = %s ORDER BY sequence",
                    (session_id,),
                )
                rows = cast(tuple[tuple[object, ...], ...], cursor.fetchall())
        finally:
            connection.close()
        return [_message_from_row(row) for row in rows]
