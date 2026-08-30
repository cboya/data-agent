from pathlib import Path
from typing import Any

import pymysql
import pytest
from pydantic import SecretStr, ValidationError

from data_agent.analytics import AnalyticsSourceProfile, active_analytics_source
from data_agent.catalog.introspection import (
    GeneratedColumnMetadata,
    GeneratedSchemaMetadata,
    GeneratedTableMetadata,
    write_generated_schema,
)
from data_agent.catalog.workspace import (
    SYNTHETIC_GENERATED_ROOT,
    active_catalog_workspace,
    catalog_workspace,
)
from data_agent.config import Settings
from data_agent.infrastructure import mysql_world
from data_agent.persistence.mysql.common import control_connection
from data_agent.query_runtime.mysql import MySQLQueryConnectionFactory


def _external_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "ollama_chat_model": "chat-model",
        "ollama_embed_model": "embedding-model",
        "mysql_host": "analytics.example.test",
        "mysql_port": 4406,
        "mysql_database": "external_analytics",
        "mysql_root_password": SecretStr("control-admin-secret"),
        "mysql_readonly_user": "external_reader",
        "mysql_readonly_password": SecretStr("external-reader-secret"),
        "mysql_control_host": "control.example.test",
        "mysql_control_port": 5506,
        "mysql_control_database": "agent_control",
        "mysql_control_user": "agent_control",
        "mysql_control_password": SecretStr("control-runtime-secret"),
        "analytics_source_mode": "EXTERNAL",
        "analytics_source_id": "external-fixture",
        "analytics_allowed_tables": ("dim_parent", "fact_child"),
        "analytics_catalog_workspace": "external-fixture",
    }
    values.update(overrides)
    return Settings.model_validate(values)


def test_control_and_analytics_connections_use_independent_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def connect(**kwargs: Any) -> object:
        calls.append(kwargs)
        return object()

    monkeypatch.setattr(pymysql, "connect", connect)
    settings = _external_settings()

    control_connection(settings)
    MySQLQueryConnectionFactory(settings).connect()

    assert calls[0]["host"] == "control.example.test"
    assert calls[0]["port"] == 5506
    assert calls[0]["database"] == "agent_control"
    assert calls[0]["user"] == "agent_control"
    assert calls[1]["host"] == "analytics.example.test"
    assert calls[1]["port"] == 4406
    assert calls[1]["database"] == "external_analytics"
    assert calls[1]["user"] == "external_reader"


def test_external_source_profile_and_workspace_exclude_every_secret() -> None:
    settings = _external_settings()

    profile = active_analytics_source(settings)
    workspace = active_catalog_workspace(settings)
    serialized = profile.model_dump_json()

    assert profile.allowed_tables == ("dim_parent", "fact_child")
    assert workspace.generated_root != SYNTHETIC_GENERATED_ROOT
    assert workspace.generated_root.parts[-4:] == (
        "catalog",
        "workspaces",
        "external-fixture",
        "generated",
    )
    for forbidden in (
        "analytics.example.test",
        "control.example.test",
        "external_reader",
        "external-reader-secret",
        "control-runtime-secret",
        "control-admin-secret",
    ):
        assert forbidden not in serialized


def test_synthetic_defaults_preserve_reference_surface_and_paths(settings: Settings) -> None:
    profile = active_analytics_source(settings)
    workspace = catalog_workspace(profile)

    assert profile.mode == "SYNTHETIC"
    assert profile.source_id == "synthetic-reference"
    assert profile.catalog_workspace == "synthetic-reference"
    assert len(profile.allowed_tables) == 10
    assert workspace.generated_root == SYNTHETIC_GENERATED_ROOT
    assert workspace.semantic_root.name == "semantic"


def test_external_mode_cannot_enter_synthetic_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forbidden_calls: list[str] = []

    def forbidden(name: str) -> None:
        forbidden_calls.append(name)
        raise AssertionError(f"external mode invoked {name}")

    monkeypatch.setattr(mysql_world, "start_mysql", lambda: forbidden("container startup"))
    monkeypatch.setattr(
        mysql_world,
        "apply_control_migrations",
        lambda _: forbidden("control migrations"),
    )
    monkeypatch.setattr(
        mysql_world,
        "ensure_readonly_principal",
        lambda _: forbidden("analytics principal provisioning"),
    )

    with pytest.raises(RuntimeError, match="forbidden for an external"):
        mysql_world.bootstrap_mysql(_external_settings())

    assert forbidden_calls == []


def test_profile_revalidates_canonical_scope_and_fingerprint() -> None:
    profile = AnalyticsSourceProfile.build(
        source_id="external-fixture",
        mode="EXTERNAL",
        database="analytics",
        allowed_tables=("fact_child", "dim_parent"),
        catalog_workspace="external-fixture",
    )

    assert profile.allowed_tables == ("dim_parent", "fact_child")
    tampered = profile.model_dump(mode="json")
    tampered["database"] = "other"
    with pytest.raises(ValidationError, match="fingerprint"):
        AnalyticsSourceProfile.model_validate(tampered)


def test_external_generated_workspace_cannot_overwrite_synthetic_authority(
    tmp_path: Path,
) -> None:
    schema = GeneratedSchemaMetadata.build(
        schema="analytics",
        tables=(
            GeneratedTableMetadata(
                name="fact_external",
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
            ),
        ),
    )
    synthetic_root = tmp_path / "catalog" / "generated"
    external_root = tmp_path / "catalog" / "workspaces" / "external-fixture" / "generated"
    synthetic_path = synthetic_root / "schema.json"
    external_path = external_root / "schema.json"
    synthetic_path.parent.mkdir(parents=True)
    synthetic_path.write_text("synthetic-authority\n", encoding="utf-8")

    write_generated_schema(
        schema,
        output_path=external_path,
        generated_root=external_root,
    )

    assert synthetic_path.read_text(encoding="utf-8") == "synthetic-authority\n"
    assert external_path.exists()
    assert external_path != synthetic_path
