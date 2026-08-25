"""Validated application configuration."""

import re
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration loaded from environment variables and an optional .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_chat_model: str = Field(min_length=1)
    ollama_embed_model: str = Field(min_length=1)
    ollama_request_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    planner_eval_request_timeout_seconds: float = Field(default=180.0, gt=0, le=300)
    ollama_max_embedding_batch: int = Field(default=32, ge=1, le=256)
    ollama_max_response_bytes: int = Field(default=4_194_304, ge=1024, le=16_777_216)

    app_host: str = "127.0.0.1"
    app_port: int = Field(default=8000, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    mysql_host: str = "127.0.0.1"
    mysql_port: int = Field(default=3306, ge=1, le=65535)
    mysql_database: str = Field(default="data_agent", min_length=1)
    mysql_root_password: SecretStr
    mysql_readonly_user: str = Field(default="data_agent_reader", min_length=1)
    mysql_readonly_password: SecretStr
    mysql_control_database: str = Field(default="data_agent_control", min_length=1)
    mysql_control_user: str = Field(default="data_agent_control", min_length=1)
    mysql_control_password: SecretStr

    max_query_time_ms: int = Field(default=5000, gt=0)
    max_result_rows: int = Field(default=1000, gt=0)
    max_sql_characters: int = Field(default=64_000, ge=1_024, le=1_000_000)
    max_explain_estimated_rows: int = Field(default=100_000, gt=0)
    max_sql_repair_attempts: int = Field(default=1, ge=0, le=3)
    max_retrieved_tables: int = Field(default=8, gt=0, le=100)
    max_relationship_hops: int = Field(default=1, ge=0, le=3)
    retrieval_lexical_top_k: int = Field(default=10, ge=1, le=100)
    retrieval_semantic_top_k: int = Field(default=10, ge=1, le=100)
    retrieval_seed_tables: int = Field(default=4, ge=1, le=20)
    retrieval_rrf_k: float = Field(default=60.0, gt=0, le=1000)

    @field_validator("ollama_base_url")
    @classmethod
    def validate_ollama_base_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
            raise ValueError("must be an absolute HTTP(S) URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("must not contain credentials")
        if parsed.query or parsed.fragment:
            raise ValueError("must not contain a query or fragment")
        return value.rstrip("/")

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

    @model_validator(mode="after")
    def control_plane_is_separate(self) -> Self:
        if self.mysql_control_database == self.mysql_database:
            raise ValueError("control and analytics MySQL databases must be distinct")
        if self.mysql_control_user == self.mysql_readonly_user:
            raise ValueError("control and analytics runtime users must be distinct")
        if self.retrieval_seed_tables > self.max_retrieved_tables:
            raise ValueError("retrieval seed table bound cannot exceed total retrieved table bound")
        return self
