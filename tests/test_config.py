import pytest
from pydantic import SecretStr, ValidationError

from data_agent.config import Settings


def test_settings_validate_runtime_limits(settings: Settings) -> None:
    assert settings.model_runtime_provider == "ollama"
    assert settings.max_query_time_ms == 5000
    assert settings.max_sql_characters == 64_000
    assert settings.max_explain_estimated_rows == 100_000
    assert settings.max_result_bytes == 8_388_608
    assert settings.mysql_query_read_timeout_seconds == 10
    assert settings.ollama_request_timeout_seconds == 60
    assert settings.planner_eval_request_timeout_seconds == 180
    assert settings.ollama_max_output_tokens == 2_048
    assert settings.openai_compatible_max_output_tokens == 2_048
    assert (
        Settings.model_fields["openai_compatible_identity_profile"].default == "openai_models_by_id"
    )
    assert settings.mysql_root_password.get_secret_value() == "change-me-local-only"
    assert settings.max_retrieved_tables == 8
    assert settings.max_relationship_hops == 1
    assert settings.retrieval_seed_tables == 4
    assert settings.retrieval_rrf_k == 60
    assert settings.max_answer_context_rows == 100
    assert settings.max_answer_context_bytes == 131_072


def test_empty_model_name_fails_validation() -> None:
    with pytest.raises(ValidationError):
        Settings(
            ollama_chat_model="",
            ollama_embed_model="embedding-model",
            mysql_root_password=SecretStr("root-test-password"),
            mysql_readonly_password=SecretStr("reader-test-password"),
            mysql_control_password=SecretStr("control-test-password"),
        )


def test_remote_provider_requires_only_its_own_model_configuration() -> None:
    settings = Settings.model_validate(
        {
            "model_runtime_provider": "openai_compatible",
            "openai_compatible_base_url": "https://models.example.test/v1",
            "openai_compatible_identity_profile": "openai_models_by_id",
            "openai_compatible_api_key": SecretStr("remote-secret"),
            "openai_compatible_chat_model": "chat-deployment",
            "openai_compatible_embed_model": "embed-deployment",
            "ollama_chat_model": "",
            "ollama_embed_model": "",
            "mysql_root_password": SecretStr("root-test-password"),
            "mysql_readonly_password": SecretStr("reader-test-password"),
            "mysql_control_password": SecretStr("control-test-password"),
        }
    )

    assert settings.ollama_chat_model == ""
    assert settings.ollama_embed_model == ""
    assert settings.openai_compatible_api_key is not None
    assert "remote-secret" not in repr(settings)


def test_cloudflare_identity_profile_accepts_only_exact_account_ai_v1_base() -> None:
    settings = Settings.model_validate(
        {
            "model_runtime_provider": "openai_compatible",
            "openai_compatible_base_url": (
                "https://api.cloudflare.com/client/v4/accounts/"
                "0123456789abcdef0123456789abcdef/ai/v1"
            ),
            "openai_compatible_identity_profile": "cloudflare_workers_ai",
            "openai_compatible_api_key": SecretStr("remote-secret"),
            "openai_compatible_chat_model": "@cf/meta/chat",
            "openai_compatible_embed_model": "@cf/baai/embed",
            "mysql_root_password": SecretStr("root-test-password"),
            "mysql_readonly_password": SecretStr("reader-test-password"),
            "mysql_control_password": SecretStr("control-test-password"),
        }
    )

    assert settings.openai_compatible_identity_profile == "cloudflare_workers_ai"


@pytest.mark.parametrize(
    "base_url",
    [
        "http://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/ai/v1",
        "https://example.test/client/v4/accounts/0123456789abcdef0123456789abcdef/ai/v1",
        "https://api.cloudflare.com/client/v4/accounts/not-an-account/ai/v1",
        "https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/ai",
    ],
)
def test_cloudflare_identity_profile_rejects_noncanonical_base(base_url: str) -> None:
    with pytest.raises(ValidationError, match="Cloudflare Workers AI identity profile"):
        Settings.model_validate(
            {
                "model_runtime_provider": "openai_compatible",
                "openai_compatible_base_url": base_url,
                "openai_compatible_identity_profile": "cloudflare_workers_ai",
                "openai_compatible_api_key": SecretStr("remote-secret"),
                "openai_compatible_chat_model": "@cf/meta/chat",
                "openai_compatible_embed_model": "@cf/baai/embed",
                "mysql_root_password": SecretStr("root-test-password"),
                "mysql_readonly_password": SecretStr("reader-test-password"),
                "mysql_control_password": SecretStr("control-test-password"),
            }
        )


def test_ollama_provider_accepts_blank_unused_remote_example_values() -> None:
    settings = Settings(
        ollama_chat_model="chat-model",
        ollama_embed_model="embed-model",
        openai_compatible_base_url="",
        openai_compatible_api_key=SecretStr(""),
        openai_compatible_chat_model="",
        openai_compatible_embed_model="",
        mysql_root_password=SecretStr("root-test-password"),
        mysql_readonly_password=SecretStr("reader-test-password"),
        mysql_control_password=SecretStr("control-test-password"),
    )

    assert settings.openai_compatible_base_url is None


@pytest.mark.parametrize(
    "missing",
    [
        "openai_compatible_base_url",
        "openai_compatible_api_key",
        "openai_compatible_chat_model",
        "openai_compatible_embed_model",
    ],
)
def test_remote_provider_rejects_missing_required_configuration(missing: str) -> None:
    values: dict[str, object] = {
        "model_runtime_provider": "openai_compatible",
        "openai_compatible_base_url": "https://models.example.test/v1",
        "openai_compatible_identity_profile": "openai_models_by_id",
        "openai_compatible_api_key": SecretStr("remote-secret"),
        "openai_compatible_chat_model": "chat-deployment",
        "openai_compatible_embed_model": "embed-deployment",
        "mysql_root_password": SecretStr("root-test-password"),
        "mysql_readonly_password": SecretStr("reader-test-password"),
        "mysql_control_password": SecretStr("control-test-password"),
    }
    values[missing] = None

    with pytest.raises(ValidationError, match="OpenAI-compatible provider"):
        Settings.model_validate(values)


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


def test_separate_mysql_endpoints_may_reuse_local_schema_and_user_names() -> None:
    settings = Settings(
        ollama_chat_model="chat-model",
        ollama_embed_model="embedding-model",
        mysql_host="analytics.example.test",
        mysql_port=4406,
        mysql_database="shared_name",
        mysql_readonly_user="shared_user",
        mysql_root_password=SecretStr("root-test-password"),
        mysql_readonly_password=SecretStr("reader-test-password"),
        mysql_control_host="control.example.test",
        mysql_control_port=5506,
        mysql_control_database="shared_name",
        mysql_control_user="shared_user",
        mysql_control_password=SecretStr("control-test-password"),
    )

    assert settings.mysql_host != settings.mysql_control_host
    assert settings.mysql_database == settings.mysql_control_database
    assert settings.mysql_readonly_user == settings.mysql_control_user


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


@pytest.mark.parametrize(
    "base_url",
    [
        "models.example.test/v1",
        "file:///tmp/models",
        "https://user:secret@models.example.test/v1",
        "https://models.example.test/v1?key=secret",
    ],
)
def test_remote_base_url_rejects_unsafe_or_ambiguous_values(base_url: str) -> None:
    with pytest.raises(ValidationError):
        Settings(
            model_runtime_provider="openai_compatible",
            openai_compatible_base_url=base_url,
            openai_compatible_identity_profile="openai_models_by_id",
            openai_compatible_api_key=SecretStr("remote-secret"),
            openai_compatible_chat_model="chat-deployment",
            openai_compatible_embed_model="embed-deployment",
            mysql_root_password=SecretStr("root-test-password"),
            mysql_readonly_password=SecretStr("reader-test-password"),
            mysql_control_password=SecretStr("control-test-password"),
        )


def test_retrieval_seed_bound_cannot_exceed_total_table_bound() -> None:
    with pytest.raises(ValidationError, match="seed table bound"):
        Settings(
            ollama_chat_model="chat-model",
            ollama_embed_model="embedding-model",
            mysql_root_password=SecretStr("root-test-password"),
            mysql_readonly_password=SecretStr("reader-test-password"),
            mysql_control_password=SecretStr("control-test-password"),
            retrieval_seed_tables=4,
            max_retrieved_tables=3,
        )


def test_query_read_timeout_must_exceed_server_bound() -> None:
    with pytest.raises(ValidationError, match="read timeout"):
        Settings(
            ollama_chat_model="chat-model",
            ollama_embed_model="embedding-model",
            mysql_root_password=SecretStr("root-test-password"),
            mysql_readonly_password=SecretStr("reader-test-password"),
            mysql_control_password=SecretStr("control-test-password"),
            max_query_time_ms=5_000,
            mysql_query_read_timeout_seconds=5,
        )
