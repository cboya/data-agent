from __future__ import annotations

from collections.abc import Sequence

import pytest
from pydantic import SecretStr

import data_agent.catalog.introspection as introspection
from data_agent.analytics import active_analytics_source
from data_agent.catalog.introspection import (
    CatalogIntrospectionError,
    introspect_analytics_schema,
    preflight_external_mysql,
)
from data_agent.config import Settings


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "ollama_chat_model": "chat-model",
        "ollama_embed_model": "embedding-model",
        "mysql_host": "analytics.example.test",
        "mysql_port": 4406,
        "mysql_database": "analytics",
        "mysql_root_password": SecretStr("root-secret"),
        "mysql_readonly_user": "reader",
        "mysql_readonly_password": SecretStr("reader-secret"),
        "mysql_control_password": SecretStr("control-secret"),
        "analytics_source_mode": "EXTERNAL",
        "analytics_source_id": "external-fixture",
        "analytics_allowed_tables": ("dim_parent", "fact_child"),
        "analytics_catalog_workspace": "external-fixture",
    }
    values.update(overrides)
    return Settings.model_validate(values)


class _Cursor:
    def __init__(self, connection: _Connection) -> None:
        self._connection = connection
        self._statement = ""

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, statement: str, parameters: Sequence[object] | None = None) -> None:
        self._statement = statement
        self._connection.queries.append((statement, tuple(parameters or ())))

    def fetchone(self) -> tuple[object, ...] | None:
        if "DATABASE()" in self._statement:
            return (self._connection.database, "8.4.11-external")
        raise AssertionError(f"unexpected scalar query: {self._statement}")

    def fetchall(self) -> tuple[tuple[object, ...], ...]:
        if "information_schema.TABLES" in self._statement:
            return (
                ("dim_parent", "Parent dimension"),
                ("fact_child", ""),
            )
        if "information_schema.COLUMNS" in self._statement:
            return (
                ("dim_parent", 1, "id", "bigint", "NO", "PRI", "Parent id"),
                ("fact_child", 1, "id", "bigint", "NO", "PRI", ""),
                ("fact_child", 2, "parent_id", "bigint", "NO", "", "Parent ref"),
            )
        if "information_schema.KEY_COLUMN_USAGE" in self._statement:
            return (
                (
                    "fact_child",
                    "fk_child_parent",
                    "parent_id",
                    1,
                    "analytics",
                    "dim_parent",
                    "id",
                ),
            )
        raise AssertionError(f"unexpected metadata query: {self._statement}")


class _Connection:
    def __init__(self, *, database: str = "analytics") -> None:
        self.database = database
        self.queries: list[tuple[str, tuple[object, ...]]] = []
        self.closed = False

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    def close(self) -> None:
        self.closed = True


def _install_connection(
    monkeypatch: pytest.MonkeyPatch,
    connection: _Connection,
) -> None:
    monkeypatch.setattr(introspection, "_connect_readonly", lambda _: connection)


def test_scoped_introspection_uses_only_the_explicit_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()
    _install_connection(monkeypatch, connection)
    settings = _settings()

    generated = introspect_analytics_schema(settings)

    assert [table.name for table in generated.tables] == ["dim_parent", "fact_child"]
    assert generated.schema_name == "analytics"
    assert connection.closed is True
    metadata_queries = [query for query in connection.queries if "information_schema" in query[0]]
    assert len(metadata_queries) == 3
    for statement, parameters in metadata_queries:
        assert "TABLE_NAME IN (%s, %s)" in statement
        assert parameters[0] == "analytics"
        assert set(parameters[1:]) == {"dim_parent", "fact_child"}
        assert "outside_table" not in parameters


def test_external_preflight_is_read_only_bounded_and_secret_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()
    _install_connection(monkeypatch, connection)
    settings = _settings()

    result = preflight_external_mysql(settings)

    assert (
        result.generated_schema.fingerprint
        == introspection.GeneratedSchemaMetadata.build(
            schema="analytics",
            tables=result.generated_schema.tables,
        ).fingerprint
    )
    assert result.report.allowed_table_count == 2
    assert result.report.column_count == 3
    assert result.report.foreign_key_count == 1
    assert result.report.table_comment_coverage == 0.5
    assert result.report.column_comment_coverage == pytest.approx(2 / 3)
    assert all(
        statement.lstrip().upper().startswith("SELECT") for statement, _ in connection.queries
    )
    serialized = result.report.model_dump_json()
    for forbidden in (
        "reader-secret",
        "root-secret",
        "control-secret",
        "analytics.example.test",
        "reader",
        "dim_parent",
        "fact_child",
    ):
        assert forbidden not in serialized


def test_database_identity_mismatch_fails_closed_before_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection(database="wrong_database")
    _install_connection(monkeypatch, connection)

    with pytest.raises(CatalogIntrospectionError, match="identity mismatch"):
        preflight_external_mysql(_settings())

    assert len(connection.queries) == 1
    assert connection.closed is True


def test_missing_allowlisted_table_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()
    original_fetchall = _Cursor.fetchall

    def missing_table(self: _Cursor) -> tuple[tuple[object, ...], ...]:
        rows = original_fetchall(self)
        if "information_schema.TABLES" in self._statement:
            return rows[:1]
        return rows

    monkeypatch.setattr(_Cursor, "fetchall", missing_table)
    _install_connection(monkeypatch, connection)

    with pytest.raises(CatalogIntrospectionError, match="coverage mismatch"):
        introspect_analytics_schema(_settings())


def test_allowed_surface_changes_generated_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()
    _install_connection(monkeypatch, connection)
    full_settings = _settings()
    full = introspect_analytics_schema(full_settings)

    parent_only_settings = _settings(
        analytics_allowed_tables=("dim_parent",),
        analytics_source_id="external-parent",
        analytics_catalog_workspace="external-parent",
    )

    def parent_only(self: _Cursor) -> tuple[tuple[object, ...], ...]:
        if "information_schema.TABLES" in self._statement:
            return (("dim_parent", "Parent dimension"),)
        if "information_schema.COLUMNS" in self._statement:
            return (("dim_parent", 1, "id", "bigint", "NO", "PRI", "Parent id"),)
        if "information_schema.KEY_COLUMN_USAGE" in self._statement:
            return ()
        raise AssertionError(f"unexpected metadata query: {self._statement}")

    monkeypatch.setattr(_Cursor, "fetchall", parent_only)
    connection = _Connection()
    _install_connection(monkeypatch, connection)
    parent_only_schema = introspect_analytics_schema(
        parent_only_settings,
        profile=active_analytics_source(parent_only_settings),
    )

    assert parent_only_schema.fingerprint != full.fingerprint
