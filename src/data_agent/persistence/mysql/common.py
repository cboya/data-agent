"""Shared MySQL mapping and connection helpers."""

from datetime import UTC, datetime
from typing import NoReturn

import pymysql
from pymysql.connections import Connection

from data_agent.config import Settings
from data_agent.persistence.errors import (
    CorruptRecordError,
    DuplicateRecordError,
    PersistenceInvariantError,
)


def control_connection(settings: Settings, *, autocommit: bool = True) -> Connection:
    return pymysql.connect(
        host=settings.mysql_control_host,
        port=settings.mysql_control_port,
        user=settings.mysql_control_user,
        password=settings.mysql_control_password.get_secret_value(),
        database=settings.mysql_control_database,
        charset="utf8mb4",
        autocommit=autocommit,
        connect_timeout=3,
        read_timeout=5,
        write_timeout=5,
    )


def to_database_datetime(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)


def from_database_datetime(value: object, *, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise CorruptRecordError(f"persisted {field} is not a datetime")
    return value.replace(tzinfo=UTC)


def require_string(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise CorruptRecordError(f"persisted {field} is not a string")
    return value


def require_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CorruptRecordError(f"persisted {field} is not an integer")
    return value


def raise_write_error(error: pymysql.MySQLError, *, record: str) -> NoReturn:
    if error.args and error.args[0] == 1062:
        raise DuplicateRecordError(f"{record} already exists") from error
    if error.args and error.args[0] in {1451, 1452, 3819}:
        raise PersistenceInvariantError(f"{record} violates a database invariant") from error
    raise error


def corrupt_record(record: str, error: Exception) -> CorruptRecordError:
    return CorruptRecordError(f"persisted {record} failed domain validation: {error}")
