import pytest
from pydantic import SecretStr, ValidationError

from data_agent.config import Settings


def test_settings_validate_runtime_limits(settings: Settings) -> None:
    assert settings.max_query_time_ms == 5000
    assert settings.ollama_request_timeout_seconds == 60
    assert settings.mysql_root_password.get_secret_value() == "change-me-local-only"


def test_empty_model_name_fails_validation() -> None:
    with pytest.raises(ValidationError):
        Settings(
            ollama_chat_model="",
            ollama_embed_model="embedding-model",
            mysql_root_password=SecretStr("root-test-password"),
            mysql_readonly_password=SecretStr("reader-test-password"),
            mysql_control_password=SecretStr("control-test-password"),
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"mysql_database": "shared", "mysql_control_database": "shared"},
        {"mysql_readonly_user": "shared", "mysql_control_user": "shared"},
    ],
)
def test_control_plane_configuration_must_be_distinct(overrides: dict[str, str]) -> None:
    values: dict[str, object] = {
        "ollama_chat_model": "chat-model",
        "ollama_embed_model": "embedding-model",
        "mysql_root_password": SecretStr("root-test-password"),
        "mysql_readonly_password": SecretStr("reader-test-password"),
        "mysql_control_password": SecretStr("control-test-password"),
    }
    values.update(overrides)
    with pytest.raises(ValidationError, match="must be distinct"):
        Settings.model_validate(values)


@pytest.mark.parametrize(
    "base_url",
    ["127.0.0.1:11434", "file:///tmp/ollama", "http://user:secret@localhost:11434"],
)
def test_ollama_base_url_rejects_unsafe_or_ambiguous_values(base_url: str) -> None:
    with pytest.raises(ValidationError):
        Settings(
            ollama_base_url=base_url,
            ollama_chat_model="chat-model",
            ollama_embed_model="embedding-model",
            mysql_root_password=SecretStr("root-test-password"),
            mysql_readonly_password=SecretStr("reader-test-password"),
            mysql_control_password=SecretStr("control-test-password"),
        )
