"""Deterministic MySQL analytics-schema introspection and generated metadata output."""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Self

import pymysql
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from pymysql.connections import Connection

from data_agent.analytics import AnalyticsSourceProfile, active_analytics_source
from data_agent.catalog.workspace import (
    SYNTHETIC_GENERATED_ROOT,
    catalog_workspace,
    ensure_generated_output_path,
    is_safe_generated_root,
)
from data_agent.config import Settings

GENERATED_CATALOG_ROOT = SYNTHETIC_GENERATED_ROOT
GENERATED_SCHEMA_PATH = GENERATED_CATALOG_ROOT / "schema.json"
MAX_INTROSPECTED_COLUMNS = 10_000
MAX_INTROSPECTED_FOREIGN_KEYS = 10_000

_TABLES_SQL = """
SELECT TABLE_NAME, TABLE_COMMENT
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE' AND TABLE_NAME IN ({tables})
ORDER BY TABLE_NAME
LIMIT {limit}
"""

_COLUMNS_SQL = """
SELECT TABLE_NAME, ORDINAL_POSITION, COLUMN_NAME, COLUMN_TYPE,
       IS_NULLABLE, COLUMN_KEY, COLUMN_COMMENT
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = %s AND TABLE_NAME IN ({tables})
ORDER BY TABLE_NAME, ORDINAL_POSITION
LIMIT {limit}
"""

_FOREIGN_KEYS_SQL = """
SELECT TABLE_NAME, CONSTRAINT_NAME, COLUMN_NAME, ORDINAL_POSITION,
       REFERENCED_TABLE_SCHEMA, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME
FROM information_schema.KEY_COLUMN_USAGE
WHERE TABLE_SCHEMA = %s AND REFERENCED_TABLE_NAME IS NOT NULL
  AND TABLE_NAME IN ({tables}) AND REFERENCED_TABLE_NAME IN ({tables})
ORDER BY TABLE_NAME, CONSTRAINT_NAME, ORDINAL_POSITION
LIMIT {limit}
"""


class CatalogIntrospectionError(RuntimeError):
    """The configured analytics schema could not be introspected reliably."""


class CatalogOutputError(RuntimeError):
    """Generated catalog output could not be validated or written safely."""


class ExternalMySQLPreflightReport(BaseModel):
    """Bounded non-secret evidence from one external read-only metadata pass."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal["external-mysql-preflight-v0.1"] = "external-mysql-preflight-v0.1"
    source_profile_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_id: str = Field(min_length=1)
    backend: Literal["mysql"] = "mysql"
    database: str = Field(min_length=1)
    server_version: str = Field(min_length=1, max_length=256)
    allowed_table_count: int = Field(ge=1, le=100)
    column_count: int = Field(ge=1, le=MAX_INTROSPECTED_COLUMNS)
    foreign_key_count: int = Field(ge=0, le=MAX_INTROSPECTED_FOREIGN_KEYS)
    table_comment_coverage: float = Field(ge=0, le=1)
    column_comment_coverage: float = Field(ge=0, le=1)


@dataclass(frozen=True)
class ExternalMySQLPreflightResult:
    """Internal composition result; only report is bounded evidence."""

    report: ExternalMySQLPreflightReport
    generated_schema: GeneratedSchemaMetadata


class _GeneratedMetadataModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class GeneratedColumnMetadata(_GeneratedMetadataModel):
    ordinal_position: int = Field(ge=1)
    name: str = Field(min_length=1)
    data_type: str = Field(min_length=1)
    nullable: bool
    primary_key: bool
    comment: str | None


class GeneratedForeignKeyMetadata(_GeneratedMetadataModel):
    constraint_name: str = Field(min_length=1)
    columns: tuple[str, ...] = Field(min_length=1)
    referenced_table: str = Field(min_length=1)
    referenced_columns: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def column_counts_match(self) -> Self:
        if len(self.columns) != len(self.referenced_columns):
            raise ValueError("foreign key column counts must match")
        if len(self.columns) != len(set(self.columns)):
            raise ValueError("foreign key columns must be unique")
        return self


class GeneratedTableMetadata(_GeneratedMetadataModel):
    name: str = Field(min_length=1)
    comment: str | None
    columns: tuple[GeneratedColumnMetadata, ...] = Field(min_length=1)
    foreign_keys: tuple[GeneratedForeignKeyMetadata, ...]

    @model_validator(mode="after")
    def members_are_unique_and_ordered(self) -> Self:
        positions = [column.ordinal_position for column in self.columns]
        if positions != sorted(positions) or len(positions) != len(set(positions)):
            raise ValueError("catalog columns must have unique sorted ordinal positions")
        names = [column.name for column in self.columns]
        if len(names) != len(set(names)):
            raise ValueError("catalog column names must be unique")
        foreign_key_names = [foreign_key.constraint_name for foreign_key in self.foreign_keys]
        if foreign_key_names != sorted(foreign_key_names) or len(foreign_key_names) != len(
            set(foreign_key_names)
        ):
            raise ValueError("foreign keys must have unique sorted constraint names")
        column_names = set(names)
        for foreign_key in self.foreign_keys:
            if not set(foreign_key.columns) <= column_names:
                raise ValueError("foreign key references an unknown local column")
        return self


def _canonical_payload(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _metadata_fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_payload(payload).encode("utf-8")).hexdigest()


class GeneratedSchemaMetadata(_GeneratedMetadataModel):
    version: Literal["v0.1"] = "v0.1"
    schema_name: str = Field(alias="schema", serialization_alias="schema", min_length=1)
    tables: tuple[GeneratedTableMetadata, ...] = Field(min_length=1)
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def build(
        cls,
        *,
        schema: str,
        tables: tuple[GeneratedTableMetadata, ...],
    ) -> Self:
        payload: dict[str, Any] = {
            "version": "v0.1",
            "schema": schema,
            "tables": [table.model_dump(mode="json") for table in tables],
        }
        return cls(**payload, fingerprint=_metadata_fingerprint(payload))

    @model_validator(mode="after")
    def artifact_is_complete_ordered_and_untampered(self) -> Self:
        table_names = [table.name for table in self.tables]
        if table_names != sorted(table_names) or len(table_names) != len(set(table_names)):
            raise ValueError("catalog tables must have unique sorted names")

        table_columns = {
            table.name: {column.name for column in table.columns} for table in self.tables
        }
        for table in self.tables:
            for foreign_key in table.foreign_keys:
                referenced_columns = table_columns.get(foreign_key.referenced_table)
                if referenced_columns is None:
                    raise ValueError("foreign key references an unknown table")
                if not set(foreign_key.referenced_columns) <= referenced_columns:
                    raise ValueError("foreign key references an unknown target column")

        payload = self.model_dump(mode="json", by_alias=True, exclude={"fingerprint"})
        if self.fingerprint != _metadata_fingerprint(payload):
            raise ValueError("generated schema fingerprint does not match canonical metadata")
        return self


def _connect_readonly(settings: Settings) -> Connection:
    return pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_readonly_user,
        password=settings.mysql_readonly_password.get_secret_value(),
        database=settings.mysql_database,
        charset="utf8mb4",
        autocommit=True,
        connect_timeout=3,
        read_timeout=5,
        write_timeout=5,
    )


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise CatalogIntrospectionError(f"information_schema returned invalid {field}")
    return value


def _optional_comment(value: object, field: str) -> str | None:
    if not isinstance(value, str):
        raise CatalogIntrospectionError(f"information_schema returned invalid {field}")
    return value or None


def _ordinal(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CatalogIntrospectionError(
            "information_schema returned invalid column ordinal position"
        )
    return value


def _rows(
    connection: Connection,
    query: str,
    profile: AnalyticsSourceProfile,
    *,
    table_list_count: int = 1,
    max_rows: int,
) -> Sequence[tuple[Any, ...]]:
    placeholders = ", ".join("%s" for _ in profile.allowed_tables)
    statement = query.format(tables=placeholders, limit=max_rows + 1)
    parameters: tuple[object, ...] = (profile.database,) + (
        profile.allowed_tables * table_list_count
    )
    with connection.cursor() as cursor:
        cursor.execute(statement, parameters)
        rows = cursor.fetchall()
    if len(rows) > max_rows:
        raise CatalogIntrospectionError("information_schema metadata exceeds the configured bound")
    return rows


def _build_columns(
    rows: Sequence[tuple[Any, ...]],
    table_names: set[str],
) -> dict[str, list[GeneratedColumnMetadata]]:
    columns: dict[str, list[GeneratedColumnMetadata]] = {table: [] for table in table_names}
    for row in rows:
        table = _required_text(row[0], "column table name")
        if table not in columns:
            raise CatalogIntrospectionError("column metadata references an unknown analytics table")
        nullable = _required_text(row[4], "column nullability")
        if nullable not in {"YES", "NO"}:
            raise CatalogIntrospectionError(
                "information_schema returned invalid column nullability"
            )
        key = row[5]
        if not isinstance(key, str):
            raise CatalogIntrospectionError("information_schema returned invalid column key")
        columns[table].append(
            GeneratedColumnMetadata(
                ordinal_position=_ordinal(row[1]),
                name=_required_text(row[2], "column name"),
                data_type=_required_text(row[3], "column type"),
                nullable=nullable == "YES",
                primary_key=key == "PRI",
                comment=_optional_comment(row[6], "column comment"),
            )
        )
    if any(not table_columns for table_columns in columns.values()):
        raise CatalogIntrospectionError("an analytics base table has no visible columns")
    return columns


def _build_foreign_keys(
    rows: Sequence[tuple[Any, ...]],
    *,
    schema: str,
    table_names: set[str],
) -> dict[str, list[GeneratedForeignKeyMetadata]]:
    parts: dict[tuple[str, str, str], list[tuple[int, str, str]]] = {}
    for row in rows:
        table = _required_text(row[0], "foreign key table")
        constraint = _required_text(row[1], "foreign key constraint")
        column = _required_text(row[2], "foreign key column")
        ordinal = _ordinal(row[3])
        referenced_schema = _required_text(row[4], "referenced schema")
        referenced_table = _required_text(row[5], "referenced table")
        referenced_column = _required_text(row[6], "referenced column")
        if table not in table_names:
            raise CatalogIntrospectionError("foreign key metadata references an unknown table")
        if referenced_schema != schema:
            raise CatalogIntrospectionError("cross-schema foreign keys are not catalog-safe")
        if referenced_table not in table_names:
            raise CatalogIntrospectionError("foreign key references a non-catalog table")
        parts.setdefault((table, constraint, referenced_table), []).append(
            (ordinal, column, referenced_column)
        )

    foreign_keys: dict[str, list[GeneratedForeignKeyMetadata]] = {
        table: [] for table in table_names
    }
    for (table, constraint, referenced_table), members in sorted(parts.items()):
        ordered = sorted(members)
        positions = [position for position, _, _ in ordered]
        if positions != list(range(1, len(ordered) + 1)):
            raise CatalogIntrospectionError("foreign key ordinals are incomplete")
        foreign_keys[table].append(
            GeneratedForeignKeyMetadata(
                constraint_name=constraint,
                columns=tuple(column for _, column, _ in ordered),
                referenced_table=referenced_table,
                referenced_columns=tuple(referenced for _, _, referenced in ordered),
            )
        )
    return foreign_keys


def _introspect_connection(
    connection: Connection,
    profile: AnalyticsSourceProfile,
) -> GeneratedSchemaMetadata:
    table_rows = _rows(connection, _TABLES_SQL, profile, max_rows=len(profile.allowed_tables))
    tables: list[tuple[str, str | None]] = []
    for row in table_rows:
        tables.append(
            (
                _required_text(row[0], "table name"),
                _optional_comment(row[1], "table comment"),
            )
        )
    table_names = {name for name, _ in tables}
    if len(table_names) != len(tables):
        raise CatalogIntrospectionError("information_schema returned duplicate table metadata")
    expected_tables = set(profile.allowed_tables)
    if table_names != expected_tables:
        missing = sorted(expected_tables - table_names)
        unexpected = sorted(table_names - expected_tables)
        raise CatalogIntrospectionError(
            f"allowed analytics table coverage mismatch: missing={missing}, unexpected={unexpected}"
        )

    columns = _build_columns(
        _rows(connection, _COLUMNS_SQL, profile, max_rows=MAX_INTROSPECTED_COLUMNS),
        table_names,
    )
    foreign_keys = _build_foreign_keys(
        _rows(
            connection,
            _FOREIGN_KEYS_SQL,
            profile,
            table_list_count=2,
            max_rows=MAX_INTROSPECTED_FOREIGN_KEYS,
        ),
        schema=profile.database,
        table_names=table_names,
    )
    normalized_tables = tuple(
        GeneratedTableMetadata(
            name=name,
            comment=comment,
            columns=tuple(columns[name]),
            foreign_keys=tuple(foreign_keys[name]),
        )
        for name, comment in sorted(tables)
    )
    return GeneratedSchemaMetadata.build(
        schema=profile.database,
        tables=normalized_tables,
    )


def introspect_analytics_schema(
    settings: Settings,
    *,
    profile: AnalyticsSourceProfile | None = None,
) -> GeneratedSchemaMetadata:
    """Read only the active source's allowlisted surface through its reader principal."""
    selected = profile or active_analytics_source(settings)
    connection: Connection | None = None
    try:
        connection = _connect_readonly(settings)
        return _introspect_connection(connection, selected)
    except pymysql.MySQLError as error:
        raise CatalogIntrospectionError("MySQL catalog introspection failed") from error
    except (IndexError, ValidationError) as error:
        raise CatalogIntrospectionError("MySQL catalog metadata failed validation") from error
    finally:
        if connection is not None:
            connection.close()


def preflight_external_mysql(
    settings: Settings,
    *,
    profile: AnalyticsSourceProfile | None = None,
) -> ExternalMySQLPreflightResult:
    """Prove an external allowlisted surface using metadata reads only."""

    selected = profile or active_analytics_source(settings)
    if selected.mode != "EXTERNAL":
        raise CatalogIntrospectionError("external MySQL preflight requires an EXTERNAL source")
    connection: Connection | None = None
    try:
        connection = _connect_readonly(settings)
        with connection.cursor() as cursor:
            cursor.execute("SELECT DATABASE(), VERSION()")
            identity_row = cursor.fetchone()
        if identity_row is None or len(identity_row) != 2:
            raise CatalogIntrospectionError("external MySQL returned invalid database identity")
        selected_database = _required_text(identity_row[0], "selected database identity")
        server_version = _required_text(identity_row[1], "server version")
        if selected_database != selected.database:
            raise CatalogIntrospectionError("external MySQL selected database identity mismatch")

        generated = _introspect_connection(connection, selected)
        column_count = sum(len(table.columns) for table in generated.tables)
        foreign_key_count = sum(len(table.foreign_keys) for table in generated.tables)
        table_comments = sum(table.comment is not None for table in generated.tables)
        column_comments = sum(
            column.comment is not None for table in generated.tables for column in table.columns
        )
        report = ExternalMySQLPreflightReport(
            source_profile_fingerprint=selected.fingerprint,
            source_id=selected.source_id,
            database=selected.database,
            server_version=server_version,
            allowed_table_count=len(generated.tables),
            column_count=column_count,
            foreign_key_count=foreign_key_count,
            table_comment_coverage=table_comments / len(generated.tables),
            column_comment_coverage=column_comments / column_count,
        )
        return ExternalMySQLPreflightResult(report=report, generated_schema=generated)
    except pymysql.MySQLError as error:
        raise CatalogIntrospectionError("external MySQL preflight failed") from error
    except (IndexError, ValidationError) as error:
        raise CatalogIntrospectionError(
            "external MySQL preflight metadata failed validation"
        ) from error
    finally:
        if connection is not None:
            connection.close()


def _ensure_generated_path(output_path: Path, generated_root: Path) -> None:
    try:
        ensure_generated_output_path(output_path, generated_root)
    except ValueError as error:
        raise CatalogOutputError(str(error)) from error


def write_generated_schema(
    schema: GeneratedSchemaMetadata,
    *,
    output_path: Path = GENERATED_SCHEMA_PATH,
    generated_root: Path = GENERATED_CATALOG_ROOT,
) -> Path:
    """Atomically write canonical generated metadata without touching curated semantics."""
    _ensure_generated_path(output_path, generated_root)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = (
        json.dumps(
            schema.model_dump(mode="json", by_alias=True),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    temporary_path = output_path.with_name(f".{output_path.name}.tmp")
    try:
        temporary_path.write_text(serialized, encoding="utf-8")
        temporary_path.replace(output_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return output_path


def load_generated_schema(path: Path = GENERATED_SCHEMA_PATH) -> GeneratedSchemaMetadata:
    """Load a generated artifact and revalidate its canonical fingerprint."""
    try:
        return GeneratedSchemaMetadata.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise CatalogOutputError("generated schema artifact is missing or invalid") from error


def generate_schema_catalog(
    settings: Settings,
    *,
    profile: AnalyticsSourceProfile | None = None,
    output_path: Path = GENERATED_SCHEMA_PATH,
    generated_root: Path = GENERATED_CATALOG_ROOT,
) -> GeneratedSchemaMetadata:
    """Introspect the analytics schema and write its generated artifact."""
    schema = introspect_analytics_schema(settings, profile=profile)
    write_generated_schema(
        schema,
        output_path=output_path,
        generated_root=generated_root,
    )
    return schema


def preflight_and_write_external_schema(
    settings: Settings,
) -> ExternalMySQLPreflightResult:
    """Run external read-only preflight and persist only its local generated schema."""

    profile = active_analytics_source(settings)
    result = preflight_external_mysql(settings, profile=profile)
    workspace = catalog_workspace(profile)
    write_generated_schema(
        result.generated_schema,
        output_path=workspace.generated_schema_path,
        generated_root=workspace.generated_root,
    )
    return result


def reset_generated_catalog(*, generated_root: Path = GENERATED_CATALOG_ROOT) -> None:
    """Remove rebuildable catalog state while leaving curated semantics untouched."""
    resolved_root = generated_root.resolve()
    if not is_safe_generated_root(resolved_root):
        raise CatalogOutputError(
            "generated catalog root must be catalog/generated or catalog/workspaces/<id>/generated"
        )
    if resolved_root.exists():
        shutil.rmtree(resolved_root)
