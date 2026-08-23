from collections.abc import Iterator

import pytest
from pydantic import SecretStr

from data_agent.config import Settings


@pytest.fixture
def settings() -> Iterator[Settings]:
    yield Settings(
        ollama_chat_model="gemma4:latest",
        ollama_embed_model="example-embedding-model",
        mysql_root_password=SecretStr("change-me-local-only"),
        mysql_readonly_password=SecretStr("change-me-local-only"),
    )
