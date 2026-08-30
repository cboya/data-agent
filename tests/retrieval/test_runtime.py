"""Current catalog authority must match the active M17 source profile."""

from pathlib import Path

import pytest
from pydantic import SecretStr

import data_agent.retrieval.runtime as retrieval_runtime
from data_agent.catalog.introspection import (
    GeneratedColumnMetadata,
    GeneratedSchemaMetadata,
    GeneratedTableMetadata,
    write_generated_schema,
)
from data_agent.catalog.workspace import CatalogWorkspace
from data_agent.config import Settings
from data_agent.retrieval.errors import RetrievalIndexStaleError


def _settings(*, database: str, allowed_tables: tuple[str, ...]) -> Settings:
    return Settings(
        ollama_chat_model="chat-model",
        ollama_embed_model="embedding-model",
        mysql_host="analytics.example.test",
        mysql_port=4406,
        mysql_database=database,
        mysql_root_password=None,
        mysql_readonly_user="external_reader",
        mysql_readonly_password=SecretStr("external-reader-secret"),
        mysql_control_host="control.example.test",
        mysql_control_port=5506,
        mysql_control_database="agent_control",
        mysql_control_user="agent_control",
        mysql_control_password=SecretStr("control-runtime-secret"),
        analytics_source_mode="EXTERNAL",
        analytics_source_id="external-fixture",
        analytics_allowed_tables=allowed_tables,
        analytics_catalog_workspace="external-fixture",
    )


def _generated(*, schema: str, tables: tuple[str, ...]) -> GeneratedSchemaMetadata:
    return GeneratedSchemaMetadata.build(
        schema=schema,
        tables=tuple(
            GeneratedTableMetadata(
                name=table,
                comment=None,
                columns=(
                    GeneratedColumnMetadata(
                        ordinal_position=1,
                        name="id",
                        data_type="bigint",
                        nullable=False,
                        primary_key=True,
                        comment=None,
                    ),
                ),
                foreign_keys=(),
            )
            for table in tables
        ),
    )


def _install_generated_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    generated: GeneratedSchemaMetadata,
) -> None:
    workspace = CatalogWorkspace(
        identity="external-fixture",
        generated_root=tmp_path / "catalog" / "workspaces" / "external-fixture" / "generated",
        semantic_root=tmp_path / "catalog" / "workspaces" / "external-fixture" / "semantic",
    )
    write_generated_schema(
        generated,
        output_path=workspace.generated_schema_path,
        generated_root=workspace.generated_root,
    )
    monkeypatch.setattr(retrieval_runtime, "active_catalog_workspace", lambda _: workspace)


def test_current_catalog_rejects_generated_tables_outside_active_allowlist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_generated_workspace(
        tmp_path,
        monkeypatch,
        _generated(schema="analytics", tables=("dim_parent", "fact_child")),
    )

    with pytest.raises(RetrievalIndexStaleError, match="allowed-table surface"):
        retrieval_runtime.load_current_catalog_authority(
            _settings(database="analytics", allowed_tables=("dim_parent",))
        )


def test_current_catalog_rejects_generated_database_identity_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_generated_workspace(
        tmp_path,
        monkeypatch,
        _generated(schema="analytics_a", tables=("dim_parent",)),
    )

    with pytest.raises(RetrievalIndexStaleError, match="database"):
        retrieval_runtime.load_current_catalog_authority(
            _settings(database="analytics_b", allowed_tables=("dim_parent",))
        )
