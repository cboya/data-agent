"""Dedicated least-privilege MySQL connection factory for M11 queries."""

from __future__ import annotations

from typing import Protocol

import pymysql
from pymysql.connections import Connection

from data_agent.config import Settings

ANALYTICS_READONLY_PRINCIPAL = "ANALYTICS_READONLY"
QUERY_CONNECT_TIMEOUT_SECONDS = 5
QUERY_WRITE_TIMEOUT_SECONDS = 5


class QueryConnectionFactory(Protocol):
    """A fresh connection per execution; implementations must not pool it."""

    @property
    def database_schema(self) -> str: ...

    @property
    def principal_name(self) -> str: ...

    @property
    def principal_class(self) -> str: ...

    @property
    def read_timeout_seconds(self) -> int: ...

    @property
    def redaction_values(self) -> tuple[str, ...]: ...

    def connect(self) -> Connection: ...


class MySQLQueryConnectionFactory:
    """Connect only as the configured analytics reader, never as control/admin."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def database_schema(self) -> str:
        return self._settings.mysql_database

    @property
    def principal_name(self) -> str:
        return self._settings.mysql_readonly_user

    @property
    def principal_class(self) -> str:
        return ANALYTICS_READONLY_PRINCIPAL

    @property
    def read_timeout_seconds(self) -> int:
        return self._settings.mysql_query_read_timeout_seconds

    @property
    def redaction_values(self) -> tuple[str, ...]:
        return (self._settings.mysql_readonly_password.get_secret_value(),)

    def connect(self) -> Connection:
        return pymysql.connect(
            host=self._settings.mysql_host,
            port=self._settings.mysql_port,
            user=self._settings.mysql_readonly_user,
            password=self._settings.mysql_readonly_password.get_secret_value(),
            database=self._settings.mysql_database,
            charset="utf8mb4",
            autocommit=False,
            connect_timeout=QUERY_CONNECT_TIMEOUT_SECONDS,
            read_timeout=self._settings.mysql_query_read_timeout_seconds,
            write_timeout=QUERY_WRITE_TIMEOUT_SECONDS,
        )
