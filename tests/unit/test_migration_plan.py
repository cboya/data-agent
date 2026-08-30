import pytest
from pydantic import SecretStr

from data_agent.config import MissingMySQLAdminCredentialError, Settings
from data_agent.persistence.errors import MigrationDriftError
from data_agent.persistence.migrations import (
    AppliedMigration,
    RepositoryMigration,
    apply_control_migrations,
    plan_control_migrations,
)


def _repository(*versions: str) -> list[RepositoryMigration]:
    return [
        RepositoryMigration(version=version, checksum=f"checksum-{version}", sql=version)
        for version in versions
    ]


def _applied(*versions: str) -> list[AppliedMigration]:
    return [
        AppliedMigration(version=version, checksum=f"checksum-{version}") for version in versions
    ]


def test_complete_matching_prefix_has_no_pending_migrations() -> None:
    repository = _repository("001.sql", "002.sql", "003.sql")

    assert plan_control_migrations(repository, _applied("001.sql", "002.sql", "003.sql")) == []


def test_checksum_drift_is_rejected() -> None:
    repository = _repository("001.sql", "002.sql")
    applied = _applied("001.sql", "002.sql")
    applied[1] = AppliedMigration(version="002.sql", checksum="changed")

    with pytest.raises(MigrationDriftError, match="differs from repository content"):
        plan_control_migrations(repository, applied)


def test_applied_migration_missing_from_repository_is_rejected() -> None:
    repository = _repository("001.sql", "003.sql", "004.sql")
    applied = _applied("001.sql", "002.sql", "003.sql", "004.sql")

    with pytest.raises(MigrationDriftError, match="not a prefix"):
        plan_control_migrations(repository, applied)


def test_migration_inserted_before_applied_tail_is_rejected() -> None:
    repository = _repository("001.sql", "002.sql", "002_new.sql", "003.sql", "004.sql")
    applied = _applied("001.sql", "002.sql", "003.sql", "004.sql")

    with pytest.raises(MigrationDriftError, match="not a prefix"):
        plan_control_migrations(repository, applied)


def test_only_new_repository_suffix_is_pending() -> None:
    repository = _repository("001.sql", "002.sql", "003.sql", "004.sql")

    assert plan_control_migrations(repository, _applied("001.sql", "002.sql")) == repository[2:]


def test_control_migration_admin_path_requires_explicit_admin_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    settings = Settings(
        ollama_chat_model="chat-model",
        ollama_embed_model="embedding-model",
        mysql_root_password=None,
        mysql_readonly_password=SecretStr("reader-test-password"),
        mysql_control_password=SecretStr("control-test-password"),
    )
    monkeypatch.setattr(
        "data_agent.persistence.migrations.pymysql.connect",
        lambda **_: calls.append("admin connection"),
    )

    with pytest.raises(MissingMySQLAdminCredentialError, match="control schema migration"):
        apply_control_migrations(settings)

    assert calls == []
