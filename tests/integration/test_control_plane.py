from typing import cast

import pymysql
import pytest

from data_agent.config import Settings
from data_agent.infrastructure.mysql_world import readonly_connection
from data_agent.persistence.migrations import apply_control_migrations
from data_agent.persistence.mysql.common import control_connection
from tests.persistence.factories import admin_connection

pytestmark = pytest.mark.integration

EXPECTED_CONTROL_TABLES = {
    "agent_session",
    "agent_message",
    "agent_run",
    "agent_artifact",
    "schema_migration",
}
EXPECTED_RUNTIME_PRIVILEGES = {
    ("agent_session", "SELECT"),
    ("agent_session", "INSERT"),
    ("agent_session", "UPDATE"),
    ("agent_message", "SELECT"),
    ("agent_message", "INSERT"),
    ("agent_run", "SELECT"),
    ("agent_run", "INSERT"),
    ("agent_run", "UPDATE"),
    ("agent_artifact", "SELECT"),
    ("agent_artifact", "INSERT"),
}


def test_control_migrations_are_versioned_and_idempotent(settings: Settings) -> None:
    first = apply_control_migrations(settings)
    second = apply_control_migrations(settings)

    assert first == second
    assert [migration.version for migration in first] == [
        "001_agent_session.sql",
        "002_agent_message.sql",
        "003_agent_run.sql",
        "004_agent_artifact.sql",
    ]
    assert all(len(migration.checksum) == 64 for migration in first)


def test_control_and_business_tables_are_physically_isolated(settings: Settings) -> None:
    connection = admin_connection(settings)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT table_schema, table_name FROM information_schema.tables "
                "WHERE table_schema IN (%s, %s) AND table_type = 'BASE TABLE'",
                (settings.mysql_database, settings.mysql_control_database),
            )
            rows = cast(tuple[tuple[object, ...], ...], cursor.fetchall())
    finally:
        connection.close()

    business_tables = {str(row[1]) for row in rows if row[0] == settings.mysql_database}
    control_tables = {str(row[1]) for row in rows if row[0] == settings.mysql_control_database}
    assert len(business_tables) == 10
    assert control_tables == EXPECTED_CONTROL_TABLES
    assert business_tables.isdisjoint(control_tables)


def test_analytics_reader_cannot_read_control_schema(settings: Settings) -> None:
    connection = readonly_connection(settings)
    try:
        with connection.cursor() as cursor, pytest.raises(pymysql.MySQLError) as error:
            cursor.execute(
                f"SELECT COUNT(*) FROM `{settings.mysql_control_database}`.`agent_session`"
            )
    finally:
        connection.close()
    assert error.value.args[0] == 1142


def test_control_principal_cannot_read_business_schema(settings: Settings) -> None:
    connection = control_connection(settings)
    try:
        with connection.cursor() as cursor, pytest.raises(pymysql.MySQLError) as error:
            cursor.execute(f"SELECT COUNT(*) FROM `{settings.mysql_database}`.`fact_order`")
    finally:
        connection.close()
    assert error.value.args[0] == 1142


def test_control_runtime_has_exact_table_privilege_matrix(settings: Settings) -> None:
    connection = admin_connection(settings)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT table_name, privilege_type FROM information_schema.table_privileges "
                "WHERE grantee = %s AND table_schema = %s",
                (f"'{settings.mysql_control_user}'@'%'", settings.mysql_control_database),
            )
            rows = cast(tuple[tuple[object, ...], ...], cursor.fetchall())
    finally:
        connection.close()

    assert {(str(row[0]), str(row[1])) for row in rows} == EXPECTED_RUNTIME_PRIVILEGES


@pytest.mark.parametrize("table", ["agent_session", "agent_run"])
def test_control_runtime_cannot_delete_mutable_records(settings: Settings, table: str) -> None:
    connection = control_connection(settings)
    try:
        with connection.cursor() as cursor, pytest.raises(pymysql.MySQLError) as error:
            cursor.execute(f"DELETE FROM `{table}` WHERE 1 = 0")
    finally:
        connection.close()
    assert error.value.args[0] == 1142
