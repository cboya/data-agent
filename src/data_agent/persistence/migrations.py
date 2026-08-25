"""Version-controlled migration runner for the isolated control schema."""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pymysql
from pymysql.connections import Connection

from data_agent.config import Settings
from data_agent.persistence.errors import MigrationDriftError

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CONTROL_MIGRATION_ROOT = REPOSITORY_ROOT / "database" / "control_migrations"
_MIGRATION_NAME = re.compile(r"\d{3}_[a-z0-9_]+\.sql")
_MIGRATION_LEDGER_SQL = """
CREATE TABLE IF NOT EXISTS schema_migration (
    version VARCHAR(128) NOT NULL,
    checksum CHAR(64) NOT NULL,
    applied_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (version)
) ENGINE=InnoDB
"""


@dataclass(frozen=True)
class AppliedMigration:
    version: str
    checksum: str


def _admin_connection(
    settings: Settings, *, database: str | None = None, autocommit: bool = True
) -> Connection:
    return pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user="root",
        password=settings.mysql_root_password.get_secret_value(),
        database=database,
        charset="utf8mb4",
        autocommit=autocommit,
        connect_timeout=3,
        read_timeout=5,
        write_timeout=5,
    )


def _migration_files() -> list[Path]:
    paths = sorted(CONTROL_MIGRATION_ROOT.glob("*.sql"))
    if not paths:
        raise RuntimeError("control schema has no versioned migrations")
    invalid = [path.name for path in paths if _MIGRATION_NAME.fullmatch(path.name) is None]
    if invalid:
        raise RuntimeError(f"invalid control migration names: {invalid}")
    return paths


def _checksum(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


def _create_control_database(settings: Settings) -> None:
    connection = _admin_connection(settings)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{settings.mysql_control_database}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
            )
    finally:
        connection.close()


def applied_control_migrations(settings: Settings) -> list[AppliedMigration]:
    connection = _admin_connection(settings, database=settings.mysql_control_database)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT version, checksum FROM schema_migration ORDER BY version")
            rows = cast(tuple[tuple[object, ...], ...], cursor.fetchall())
    finally:
        connection.close()
    return [AppliedMigration(version=str(row[0]), checksum=str(row[1])) for row in rows]


def apply_control_migrations(settings: Settings) -> list[AppliedMigration]:
    """Create the isolated schema and apply each immutable migration exactly once."""

    _create_control_database(settings)
    connection = _admin_connection(
        settings,
        database=settings.mysql_control_database,
        autocommit=False,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(_MIGRATION_LEDGER_SQL)
        connection.commit()

        for path in _migration_files():
            sql = path.read_text(encoding="utf-8").strip()
            if not sql:
                raise RuntimeError(f"control migration is empty: {path.name}")
            checksum = _checksum(sql)
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT checksum FROM schema_migration WHERE version = %s",
                    (path.name,),
                )
                row = cursor.fetchone()
                if row is not None:
                    applied_checksum = str(row[0])
                    if applied_checksum != checksum:
                        raise MigrationDriftError(
                            f"applied migration {path.name} differs from repository content"
                        )
                    continue
                cursor.execute(sql)
                cursor.execute(
                    "INSERT INTO schema_migration (version, checksum) VALUES (%s, %s)",
                    (path.name, checksum),
                )
            connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()
    return applied_control_migrations(settings)
