"""MySQL Session repository with optimistic concurrency."""

from typing import cast

import pymysql
from pydantic import ValidationError

from data_agent.config import Settings
from data_agent.contracts.requirement import RequirementState
from data_agent.contracts.session import Session
from data_agent.persistence.errors import (
    CorruptRecordError,
    OptimisticConcurrencyError,
    PersistenceInvariantError,
    RecordNotFoundError,
)
from data_agent.persistence.mysql.common import (
    control_connection,
    corrupt_record,
    from_database_datetime,
    raise_write_error,
    require_int,
    require_string,
    to_database_datetime,
)
from data_agent.persistence.ports import StoredSession


def _session_from_row(row: tuple[object, ...]) -> StoredSession:
    try:
        requirement = RequirementState.model_validate_json(
            require_string(row[2], field="agent_session.requirement_json")
        )
        session = Session.model_validate(
            {
                "id": row[0],
                "status": row[1],
                "requirement": requirement,
                "created_at": from_database_datetime(row[4], field="agent_session.created_at"),
                "updated_at": from_database_datetime(row[5], field="agent_session.updated_at"),
            }
        )
        revision = require_int(row[3], field="agent_session.revision")
        return StoredSession(session=session, revision=revision)
    except (ValidationError, ValueError) as error:
        if isinstance(error, CorruptRecordError):
            raise
        raise corrupt_record("agent_session", error) from error


class MySQLSessionRepository:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def create(self, session: Session) -> StoredSession:
        connection = control_connection(self._settings)
        try:
            with connection.cursor() as cursor:
                try:
                    cursor.execute(
                        "INSERT INTO agent_session "
                        "(id, status, requirement_json, revision, created_at, updated_at) "
                        "VALUES (%s, %s, %s, 0, %s, %s)",
                        (
                            session.id,
                            session.status.value,
                            session.requirement.model_dump_json(),
                            to_database_datetime(session.created_at),
                            to_database_datetime(session.updated_at),
                        ),
                    )
                except pymysql.MySQLError as error:
                    raise_write_error(error, record=f"Session {session.id}")
        finally:
            connection.close()
        return StoredSession(session=session, revision=0)

    def get(self, session_id: str) -> StoredSession:
        connection = control_connection(self._settings)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, status, requirement_json, revision, created_at, updated_at "
                    "FROM agent_session WHERE id = %s",
                    (session_id,),
                )
                row = cursor.fetchone()
        finally:
            connection.close()
        if row is None:
            raise RecordNotFoundError(f"Session {session_id} does not exist")
        return _session_from_row(cast(tuple[object, ...], row))

    def update(self, session: Session, *, expected_revision: int) -> StoredSession:
        if expected_revision < 0:
            raise ValueError("expected Session revision cannot be negative")

        created_at = to_database_datetime(session.created_at)
        updated_at = to_database_datetime(session.updated_at)
        connection = control_connection(self._settings, autocommit=False)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE agent_session SET status = %s, requirement_json = %s, "
                    "updated_at = %s, revision = revision + 1 "
                    "WHERE id = %s AND revision = %s AND created_at = %s "
                    "AND updated_at <= %s",
                    (
                        session.status.value,
                        session.requirement.model_dump_json(),
                        updated_at,
                        session.id,
                        expected_revision,
                        created_at,
                        updated_at,
                    ),
                )
                if cursor.rowcount == 1:
                    connection.commit()
                    return StoredSession(session=session, revision=expected_revision + 1)

                cursor.execute(
                    "SELECT revision, created_at, updated_at FROM agent_session WHERE id = %s",
                    (session.id,),
                )
                current = cursor.fetchone()
            connection.rollback()
        except pymysql.MySQLError as error:
            connection.rollback()
            raise_write_error(error, record=f"Session {session.id}")
        finally:
            connection.close()

        if current is None:
            raise RecordNotFoundError(f"Session {session.id} does not exist")
        current_row = cast(tuple[object, ...], current)
        current_revision = require_int(current_row[0], field="agent_session.revision")
        if current_revision != expected_revision:
            raise OptimisticConcurrencyError(
                f"Session {session.id} revision is {current_revision}, expected {expected_revision}"
            )
        persisted_created_at = from_database_datetime(
            current_row[1], field="agent_session.created_at"
        )
        if to_database_datetime(persisted_created_at) != created_at:
            raise PersistenceInvariantError("Session created_at is immutable")
        raise PersistenceInvariantError("Session updated_at cannot move backwards")
