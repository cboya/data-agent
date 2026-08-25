"""Developer bootstrap for the deterministic MySQL test world."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import pymysql
from pymysql.connections import Connection
from pymysql.cursors import Cursor

from data_agent.config import Settings
from data_agent.persistence.migrations import apply_control_migrations
from data_agent.persistence.mysql.common import control_connection

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class FixtureSummary:
    table_count: int
    order_count: int
    paid_amount_total: str
    successful_refund_total: str


def _compose_command() -> list[str]:
    return ["docker", "compose", "--env-file", ".env", "--file", "compose.yaml"]


def start_mysql() -> None:
    subprocess.run(
        [*_compose_command(), "up", "--detach", "--wait"],
        cwd=REPOSITORY_ROOT,
        check=True,
    )


def reset_mysql() -> None:
    subprocess.run(
        [*_compose_command(), "down", "--volumes", "--remove-orphans"],
        cwd=REPOSITORY_ROOT,
        check=True,
    )


def _connect(
    settings: Settings,
    *,
    user: str,
    password: str,
    database: str | None = None,
) -> Connection:
    return pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=user,
        password=password,
        database=database,
        charset="utf8mb4",
        autocommit=True,
        connect_timeout=3,
        read_timeout=5,
        write_timeout=5,
    )


def wait_for_mysql(settings: Settings, timeout_seconds: int = 90) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            connection = _connect(
                settings,
                user="root",
                password=settings.mysql_root_password.get_secret_value(),
            )
            connection.close()
            return
        except pymysql.MySQLError as error:
            last_error = error
            time.sleep(1)
    raise RuntimeError(
        "MySQL did not become reachable before the bootstrap timeout"
    ) from last_error


def ensure_readonly_principal(settings: Settings) -> None:
    username = settings.mysql_readonly_user
    password = settings.mysql_readonly_password.get_secret_value()
    database = settings.mysql_database
    connection = _connect(
        settings,
        user="root",
        password=settings.mysql_root_password.get_secret_value(),
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "CREATE USER IF NOT EXISTS %s@'%%' IDENTIFIED BY %s", (username, password)
            )
            cursor.execute("ALTER USER %s@'%%' IDENTIFIED BY %s", (username, password))
            cursor.execute("REVOKE ALL PRIVILEGES, GRANT OPTION FROM %s@'%%'", (username,))
            cursor.execute(f"GRANT SELECT ON `{database}`.* TO %s@'%%'", (username,))
    finally:
        connection.close()


def ensure_control_principal(settings: Settings) -> None:
    username = settings.mysql_control_user
    password = settings.mysql_control_password.get_secret_value()
    database = settings.mysql_control_database
    connection = _connect(
        settings,
        user="root",
        password=settings.mysql_root_password.get_secret_value(),
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "CREATE USER IF NOT EXISTS %s@'%%' IDENTIFIED BY %s", (username, password)
            )
            cursor.execute("ALTER USER %s@'%%' IDENTIFIED BY %s", (username, password))
            cursor.execute("REVOKE ALL PRIVILEGES, GRANT OPTION FROM %s@'%%'", (username,))
            for table in ("agent_session", "agent_run"):
                cursor.execute(
                    f"GRANT SELECT, INSERT, UPDATE ON `{database}`.`{table}` TO %s@'%%'",
                    (username,),
                )
            for table in ("agent_message", "agent_artifact"):
                cursor.execute(
                    f"GRANT SELECT, INSERT ON `{database}`.`{table}` TO %s@'%%'",
                    (username,),
                )
    finally:
        connection.close()


def readonly_connection(settings: Settings) -> Connection:
    return _connect(
        settings,
        user=settings.mysql_readonly_user,
        password=settings.mysql_readonly_password.get_secret_value(),
        database=settings.mysql_database,
    )


def verify_control_principal(settings: Settings) -> None:
    expected = {
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
    connection = _connect(
        settings,
        user="root",
        password=settings.mysql_root_password.get_secret_value(),
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT table_name, privilege_type FROM information_schema.table_privileges "
                "WHERE grantee = %s AND table_schema = %s",
                (f"'{settings.mysql_control_user}'@'%'", settings.mysql_control_database),
            )
            actual = {(str(row[0]), str(row[1])) for row in cursor.fetchall()}
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.schema_privileges "
                "WHERE grantee = %s AND table_schema = %s",
                (f"'{settings.mysql_control_user}'@'%'", settings.mysql_database),
            )
            analytics_privilege_count = _integer_scalar(cursor)
    finally:
        connection.close()
    if actual != expected:
        raise RuntimeError(
            f"Control MySQL principal has unexpected table privileges: {sorted(actual)}"
        )
    if analytics_privilege_count != 0:
        raise RuntimeError("Control MySQL principal unexpectedly has analytics privileges")

    runtime_connection = control_connection(settings)
    try:
        with runtime_connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM agent_session")
            try:
                cursor.execute(f"SELECT COUNT(*) FROM `{settings.mysql_database}`.`fact_order`")
            except pymysql.MySQLError as error:
                if error.args[0] == 1142:
                    return
                raise
    finally:
        runtime_connection.close()
    raise RuntimeError("Control MySQL principal unexpectedly read analytics data")


def _scalar(cursor: Cursor) -> object:
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError("Expected a scalar query result but MySQL returned no row")
    return row[0]


def _integer_scalar(cursor: Cursor) -> int:
    value = _scalar(cursor)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError(f"Expected an integer query result, received {type(value).__name__}")
    return value


def fixture_summary(settings: Settings) -> FixtureSummary:
    connection = readonly_connection(settings)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = %s AND table_type = 'BASE TABLE'",
                (settings.mysql_database,),
            )
            table_count = _integer_scalar(cursor)
            cursor.execute("SELECT COUNT(*) FROM fact_order")
            order_count = _integer_scalar(cursor)
            cursor.execute(
                "SELECT CAST(SUM(paid_amount) AS CHAR) FROM fact_order "
                "WHERE status IN ('PAID', 'COMPLETED')"
            )
            paid_amount_total = str(_scalar(cursor))
            cursor.execute(
                "SELECT CAST(SUM(refund_amount) AS CHAR) FROM fact_refund WHERE status = 'SUCCESS'"
            )
            successful_refund_total = str(_scalar(cursor))
    finally:
        connection.close()
    return FixtureSummary(
        table_count=table_count,
        order_count=order_count,
        paid_amount_total=paid_amount_total,
        successful_refund_total=successful_refund_total,
    )


def verify_readonly_principal(settings: Settings) -> None:
    connection = readonly_connection(settings)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM fact_order")
            try:
                cursor.execute("UPDATE dim_region SET province = province WHERE id = 1")
            except pymysql.MySQLError as error:
                if error.args[0] == 1142:
                    return
                raise
    finally:
        connection.close()
    raise RuntimeError("Runtime MySQL principal unexpectedly accepted a write")


def bootstrap_mysql(settings: Settings) -> FixtureSummary:
    start_mysql()
    wait_for_mysql(settings)
    apply_control_migrations(settings)
    ensure_readonly_principal(settings)
    ensure_control_principal(settings)
    verify_readonly_principal(settings)
    verify_control_principal(settings)
    return fixture_summary(settings)
