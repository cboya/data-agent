import pymysql
import pytest

from data_agent.config import Settings
from data_agent.contracts.artifact import Artifact, ArtifactType
from data_agent.persistence.errors import CorruptRecordError
from data_agent.persistence.mysql.artifacts import MySQLArtifactRepository
from data_agent.persistence.mysql.common import control_connection
from data_agent.persistence.mysql.runs import MySQLRunRepository
from data_agent.persistence.mysql.sessions import MySQLSessionRepository
from tests.persistence.factories import (
    admin_connection,
    artifact,
    run,
    session,
    timestamp,
    unique_id,
)

pytestmark = pytest.mark.integration


def _run_context(settings: Settings) -> tuple[str, str]:
    session_id = MySQLSessionRepository(settings).create(session()).session.id
    run_id = MySQLRunRepository(settings).create(run(session_id)).id
    return session_id, run_id


def test_artifact_is_immutable_and_revalidated_after_reload(settings: Settings) -> None:
    session_id, run_id = _run_context(settings)
    repository = MySQLArtifactRepository(settings)
    created = artifact(session_id, run_id)

    stored = repository.append(created)
    reloaded = MySQLArtifactRepository(settings).list_for_run(run_id)

    assert stored == created
    assert reloaded == [created]
    assert not hasattr(repository, "update")
    assert not hasattr(repository, "delete")


def test_invalid_artifact_payload_is_rejected_before_insert(settings: Settings) -> None:
    session_id, run_id = _run_context(settings)
    invalid = Artifact(
        id=unique_id("artifact"),
        session_id=session_id,
        run_id=run_id,
        type=ArtifactType.REQUIREMENT_STATE,
        contract_version="v0.1",
        payload={"version": "v9", "status": "READY"},
        created_at=timestamp(),
    )

    with pytest.raises(CorruptRecordError, match="payload_json"):
        MySQLArtifactRepository(settings).append(invalid)


def test_corrupt_persisted_artifact_fails_closed(settings: Settings) -> None:
    session_id, run_id = _run_context(settings)
    repository = MySQLArtifactRepository(settings)
    created = repository.append(artifact(session_id, run_id))
    connection = admin_connection(settings, database=settings.mysql_control_database)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE agent_artifact SET payload_json = %s WHERE id = %s",
                ('{"version":"v9","status":"READY"}', created.id),
            )
    finally:
        connection.close()

    with pytest.raises(CorruptRecordError, match="failed domain validation"):
        repository.list_for_run(run_id)


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE agent_artifact SET payload_json = payload_json WHERE id = %s",
        "DELETE FROM agent_artifact WHERE id = %s",
    ],
)
def test_control_principal_cannot_mutate_or_delete_artifact(
    settings: Settings, statement: str
) -> None:
    session_id, run_id = _run_context(settings)
    stored = MySQLArtifactRepository(settings).append(artifact(session_id, run_id))
    connection = control_connection(settings)
    try:
        with connection.cursor() as cursor, pytest.raises(pymysql.MySQLError) as error:
            cursor.execute(statement, (stored.id,))
    finally:
        connection.close()

    assert error.value.args[0] == 1142
