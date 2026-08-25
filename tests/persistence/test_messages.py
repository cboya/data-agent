import pymysql
import pytest

from data_agent.config import Settings
from data_agent.contracts.message import MessageRole
from data_agent.persistence.mysql.common import control_connection
from data_agent.persistence.mysql.messages import MySQLMessageRepository
from data_agent.persistence.mysql.sessions import MySQLSessionRepository
from tests.persistence.factories import message, session

pytestmark = pytest.mark.integration


def test_messages_are_append_only_with_stable_session_order(settings: Settings) -> None:
    created_session = MySQLSessionRepository(settings).create(session()).session
    repository = MySQLMessageRepository(settings)
    expected = [
        message(created_session.id, "first"),
        message(created_session.id, "second", role=MessageRole.ASSISTANT),
        message(created_session.id, "third"),
    ]

    appended = [repository.append(value) for value in expected]
    reloaded = MySQLMessageRepository(settings).list_for_session(created_session.id)

    assert [value.sequence for value in appended] == [1, 2, 3]
    assert [value.sequence for value in reloaded] == [1, 2, 3]
    assert [value.message.content for value in reloaded] == ["first", "second", "third"]
    assert not hasattr(repository, "update")
    assert not hasattr(repository, "delete")


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE agent_message SET content = content WHERE id = %s",
        "DELETE FROM agent_message WHERE id = %s",
    ],
)
def test_control_principal_cannot_mutate_or_delete_message(
    settings: Settings, statement: str
) -> None:
    created_session = MySQLSessionRepository(settings).create(session()).session
    stored = MySQLMessageRepository(settings).append(message(created_session.id, "immutable"))
    connection = control_connection(settings)
    try:
        with connection.cursor() as cursor, pytest.raises(pymysql.MySQLError) as error:
            cursor.execute(statement, (stored.message.id,))
    finally:
        connection.close()

    assert error.value.args[0] == 1142
