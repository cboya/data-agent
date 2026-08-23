"""Validated application configuration."""

import re
from typing import Literal

from pydantic import Field, SecretStr, field_validator
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

    app_host: str = "127.0.0.1"
    app_port: int = Field(default=8000, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    mysql_host: str = "127.0.0.1"
    mysql_port: int = Field(default=3306, ge=1, le=65535)
    mysql_database: str = Field(default="data_agent", min_length=1)
    mysql_root_password: SecretStr
    mysql_readonly_user: str = Field(default="data_agent_reader", min_length=1)
    mysql_readonly_password: SecretStr

    max_query_time_ms: int = Field(default=5000, gt=0)
    max_result_rows: int = Field(default=1000, gt=0)
    max_sql_repair_attempts: int = Field(default=1, ge=0, le=3)
    max_retrieved_tables: int = Field(default=10, gt=0)
    max_relationship_hops: int = Field(default=2, ge=0, le=3)

    @field_validator("mysql_database", "mysql_readonly_user")
    @classmethod
    def validate_mysql_identifier(cls, value: str) -> str:
        if re.fullmatch(r"[A-Za-z0-9_]+", value) is None:
            raise ValueError("must contain only letters, digits, or underscores")
        return value
