from datetime import timedelta

import pytest

from data_agent.config import Settings
from data_agent.contracts.session import Session
from data_agent.persistence.errors import CorruptRecordError, OptimisticConcurrencyError
from data_agent.persistence.mysql.sessions import MySQLSessionRepository
from tests.persistence.factories import admin_connection, requirement, session

pytestmark = pytest.mark.integration


def _updated(session_value: Session, *, goal: str, minutes: int) -> Session:
    return Session.model_validate(
        {
            **session_value.model_dump(),
            "requirement": requirement(goal=goal),
            "updated_at": session_value.updated_at + timedelta(minutes=minutes),
        }
    )


def test_session_survives_repository_restart(settings: Settings) -> None:
    created = session()
    first_process = MySQLSessionRepository(settings)
    stored = first_process.create(created)

    second_process = MySQLSessionRepository(settings)
    reloaded = second_process.get(created.id)

    assert stored.revision == 0
    assert reloaded.revision == 0
    assert reloaded.session == created
    assert reloaded.session.requirement == created.requirement


def test_stale_session_revision_cannot_overwrite_newer_requirement(settings: Settings) -> None:
    repository = MySQLSessionRepository(settings)
    created = repository.create(session())
    request_a = repository.get(created.session.id)
    request_b = repository.get(created.session.id)

    update_a = _updated(request_a.session, goal="A wins", minutes=1)
    saved_a = repository.update(update_a, expected_revision=request_a.revision)

    update_b = _updated(request_b.session, goal="B is stale", minutes=2)
    with pytest.raises(OptimisticConcurrencyError, match="expected 0"):
        repository.update(update_b, expected_revision=request_b.revision)

    current = repository.get(created.session.id)
    assert saved_a.revision == 1
    assert current.revision == 1
    assert current.session.requirement.goal == "A wins"


def test_corrupt_persisted_requirement_fails_closed(settings: Settings) -> None:
    repository = MySQLSessionRepository(settings)
    created = repository.create(session())
    connection = admin_connection(settings, database=settings.mysql_control_database)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE agent_session SET requirement_json = %s WHERE id = %s",
                ('{"version":"v9","status":"READY"}', created.session.id),
            )
    finally:
        connection.close()

    with pytest.raises(CorruptRecordError, match="failed domain validation"):
        repository.get(created.session.id)
