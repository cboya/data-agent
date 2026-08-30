"""Validated application configuration."""

import re
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SYNTHETIC_SOURCE_ID = "synthetic-reference"
SYNTHETIC_CATALOG_WORKSPACE = "synthetic-reference"
SYNTHETIC_ALLOWED_TABLES = (
    "dim_category",
    "dim_channel",
    "dim_product",
    "dim_region",
    "dim_user",
    "fact_order",
    "fact_order_item",
    "fact_payment_transaction",
    "fact_refund",
    "fact_user_event",
)


class MissingMySQLAdminCredentialError(RuntimeError):
    """An explicitly invoked MySQL admin path has no configured admin secret."""


class Settings(BaseSettings):
    """Configuration loaded from environment variables and an optional .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    model_runtime_provider: Literal["ollama", "openai_compatible"] = "ollama"

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_chat_model: str = ""
    ollama_embed_model: str = ""
    ollama_request_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    planner_eval_request_timeout_seconds: float = Field(default=180.0, gt=0, le=300)
    ollama_max_embedding_batch: int = Field(default=32, ge=1, le=256)
    ollama_max_response_bytes: int = Field(default=4_194_304, ge=1024, le=16_777_216)
    ollama_max_output_tokens: int = Field(default=2_048, ge=256, le=32_768)

    openai_compatible_base_url: str | None = None
    openai_compatible_identity_profile: Literal[
        "openai_models_by_id",
        "cloudflare_workers_ai",
    ] = "openai_models_by_id"
    openai_compatible_api_key: SecretStr | None = None
    openai_compatible_chat_model: str | None = None
    openai_compatible_embed_model: str | None = None
    openai_compatible_request_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    openai_compatible_max_response_bytes: int = Field(
        default=4_194_304,
        ge=1024,
        le=16_777_216,
    )
    openai_compatible_max_output_tokens: int = Field(default=2_048, ge=256, le=32_768)
    openai_compatible_max_embedding_batch: int = Field(default=32, ge=1, le=256)

    app_host: str = "127.0.0.1"
    app_port: int = Field(default=8000, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    mysql_host: str = "127.0.0.1"
    mysql_port: int = Field(default=3306, ge=1, le=65535)
    mysql_database: str = Field(default="data_agent", min_length=1)
    mysql_root_password: SecretStr | None = None
    mysql_readonly_user: str = Field(default="data_agent_reader", min_length=1)
    mysql_readonly_password: SecretStr
    mysql_control_host: str = "127.0.0.1"
    mysql_control_port: int = Field(default=3306, ge=1, le=65535)
    mysql_control_database: str = Field(default="data_agent_control", min_length=1)
    mysql_control_user: str = Field(default="data_agent_control", min_length=1)
    mysql_control_password: SecretStr

    analytics_source_mode: Literal["SYNTHETIC", "EXTERNAL"] = "SYNTHETIC"
    analytics_source_id: str = SYNTHETIC_SOURCE_ID
    analytics_allowed_tables: tuple[str, ...] = SYNTHETIC_ALLOWED_TABLES
    analytics_catalog_workspace: str = SYNTHETIC_CATALOG_WORKSPACE

    max_query_time_ms: int = Field(default=5000, gt=0)
    max_result_rows: int = Field(default=1000, gt=0)
    max_result_bytes: int = Field(default=8_388_608, ge=1_024, le=104_857_600)
    mysql_query_read_timeout_seconds: int = Field(default=10, ge=1, le=300)
    max_sql_characters: int = Field(default=64_000, ge=1_024, le=1_000_000)
    max_explain_estimated_rows: int = Field(default=100_000, gt=0)
    max_sql_repair_attempts: int = Field(default=1, ge=0, le=3)
    max_retrieved_tables: int = Field(default=8, gt=0, le=100)
    max_relationship_hops: int = Field(default=1, ge=0, le=3)
    retrieval_lexical_top_k: int = Field(default=10, ge=1, le=100)
    retrieval_semantic_top_k: int = Field(default=10, ge=1, le=100)
    retrieval_seed_tables: int = Field(default=4, ge=1, le=20)
    retrieval_rrf_k: float = Field(default=60.0, gt=0, le=1000)
    max_answer_context_rows: int = Field(default=100, ge=1, le=1_000)
    max_answer_context_bytes: int = Field(default=131_072, ge=1_024, le=4_194_304)

    @staticmethod
    def _normalized_model_base_url(value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
            raise ValueError("must be an absolute HTTP(S) URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("must not contain credentials")
        if parsed.query or parsed.fragment:
            raise ValueError("must not contain a query or fragment")
        return value.rstrip("/")

    @field_validator("ollama_base_url")
    @classmethod
    def validate_ollama_base_url(cls, value: str) -> str:
        return cls._normalized_model_base_url(value)

    @field_validator("openai_compatible_base_url", mode="before")
    @classmethod
    def validate_remote_model_base_url(cls, value: object) -> str | None:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        if not isinstance(value, str):
            raise ValueError("must be an absolute HTTP(S) URL")
        return cls._normalized_model_base_url(value)

    @field_validator(
        "mysql_database",
        "mysql_readonly_user",
        "mysql_control_database",
        "mysql_control_user",
    )
    @classmethod
    def validate_mysql_identifier(cls, value: str) -> str:
        if re.fullmatch(r"[A-Za-z0-9_]+", value) is None:
            raise ValueError("must contain only letters, digits, or underscores")
        return value

    @field_validator("analytics_source_id", "analytics_catalog_workspace")
    @classmethod
    def validate_analytics_identity(cls, value: str) -> str:
        if re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", value) is None:
            raise ValueError("must be a lowercase safe source/workspace identifier")
        return value

    @field_validator("analytics_allowed_tables")
    @classmethod
    def validate_analytics_allowed_tables(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("analytics allowed-table surface cannot be empty")
        if len(value) > 100:
            raise ValueError("analytics allowed-table surface cannot exceed 100 tables")
        if any(re.fullmatch(r"[A-Za-z0-9_]{1,64}", table) is None for table in value):
            raise ValueError(
                "analytics allowed tables must contain only letters, digits, or underscores"
            )
        if len(value) != len(set(value)):
            raise ValueError("analytics allowed tables must be unique")
        return tuple(sorted(value))

    @model_validator(mode="after")
    def control_plane_is_separate(self) -> Self:
        if self.model_runtime_provider == "ollama":
            if self.ollama_chat_model is None or not self.ollama_chat_model.strip():
                raise ValueError("OLLAMA_CHAT_MODEL is required for the Ollama provider")
            if self.ollama_embed_model is None or not self.ollama_embed_model.strip():
                raise ValueError("OLLAMA_EMBED_MODEL is required for the Ollama provider")
        else:
            required_remote = {
                "OPENAI_COMPATIBLE_BASE_URL": self.openai_compatible_base_url,
                "OPENAI_COMPATIBLE_CHAT_MODEL": self.openai_compatible_chat_model,
                "OPENAI_COMPATIBLE_EMBED_MODEL": self.openai_compatible_embed_model,
            }
            missing = [
                name
                for name, value in required_remote.items()
                if value is None or not value.strip()
            ]
            if missing:
                raise ValueError(
                    "OpenAI-compatible provider requires: " + ", ".join(sorted(missing))
                )
            if self.openai_compatible_identity_profile == "cloudflare_workers_ai":
                cloudflare_base = self.openai_compatible_base_url or ""
                if (
                    re.fullmatch(
                        r"https://api\.cloudflare\.com/client/v4/accounts/"
                        r"[0-9a-f]{32}/ai/v1",
                        cloudflare_base,
                    )
                    is None
                ):
                    raise ValueError(
                        "Cloudflare Workers AI identity profile requires an exact "
                        "https://api.cloudflare.com/client/v4/accounts/"
                        "<32-hex-account-id>/ai/v1 base URL"
                    )
            if (
                self.openai_compatible_api_key is None
                or not self.openai_compatible_api_key.get_secret_value().strip()
            ):
                raise ValueError(
                    "OPENAI_COMPATIBLE_API_KEY is required for the OpenAI-compatible provider"
                )
        same_mysql_endpoint = (
            self.mysql_control_host.casefold() == self.mysql_host.casefold()
            and self.mysql_control_port == self.mysql_port
        )
        if same_mysql_endpoint and self.mysql_control_database == self.mysql_database:
            raise ValueError(
                "control and analytics MySQL databases must be distinct on a shared endpoint"
            )
        if same_mysql_endpoint and self.mysql_control_user == self.mysql_readonly_user:
            raise ValueError(
                "control and analytics runtime users must be distinct on a shared endpoint"
            )
        if self.analytics_source_mode == "SYNTHETIC":
            if self.analytics_source_id != SYNTHETIC_SOURCE_ID:
                raise ValueError("synthetic source must retain the reference source identity")
            if self.analytics_catalog_workspace != SYNTHETIC_CATALOG_WORKSPACE:
                raise ValueError("synthetic source must retain the reference catalog workspace")
            if self.analytics_allowed_tables != SYNTHETIC_ALLOWED_TABLES:
                raise ValueError("synthetic source must retain the reference allowed-table surface")
        elif (
            self.analytics_source_id == SYNTHETIC_SOURCE_ID
            or self.analytics_catalog_workspace == SYNTHETIC_CATALOG_WORKSPACE
        ):
            raise ValueError("external source must use independent source and workspace identities")
        if self.retrieval_seed_tables > self.max_retrieved_tables:
            raise ValueError("retrieval seed table bound cannot exceed total retrieved table bound")
        if self.mysql_query_read_timeout_seconds * 1000 <= self.max_query_time_ms:
            raise ValueError(
                "MySQL query read timeout must be greater than the server query-time bound"
            )
        return self


def require_mysql_admin_password(settings: Settings, *, operation: str) -> str:
    """Return the admin secret only for an explicit admin operation, or fail closed."""

    secret = settings.mysql_root_password
    if secret is None or not secret.get_secret_value().strip():
        raise MissingMySQLAdminCredentialError(
            f"MYSQL_ROOT_PASSWORD is required for MySQL admin operation: {operation}"
        )
    return secret.get_secret_value()
