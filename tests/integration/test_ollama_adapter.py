import asyncio
import os
from typing import Literal

import pytest

from data_agent.config import Settings
from data_agent.contracts.base import ContractModel
from data_agent.model_runtime.ollama import (
    OllamaChatModel,
    OllamaEmbeddingModel,
    OllamaStartupDiagnostics,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.ollama,
    pytest.mark.skipif(
        os.environ.get("RUN_OLLAMA_INTEGRATION") != "1",
        reason="set RUN_OLLAMA_INTEGRATION=1 to exercise configured local Ollama models",
    ),
]


class StructuredSmokeResult(ContractModel):
    status: Literal["ok"]


def _settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


def test_real_ollama_structured_chat_smoke() -> None:
    settings = _settings()
    diagnostics = asyncio.run(OllamaStartupDiagnostics(settings).diagnose())
    result = asyncio.run(
        OllamaChatModel(settings, fingerprint=diagnostics.chat).structured(
            messages=[
                {
                    "role": "system",
                    "content": "Return only the requested structured object.",
                },
                {"role": "user", "content": "Report success with status ok."},
            ],
            response_type=StructuredSmokeResult,
            purpose="m4-integration-smoke",
        )
    )

    assert result == StructuredSmokeResult(status="ok")


def test_real_ollama_bilingual_embedding_batch() -> None:
    settings = _settings()
    diagnostics = asyncio.run(OllamaStartupDiagnostics(settings).diagnose())
    embeddings = asyncio.run(
        OllamaEmbeddingModel(settings, fingerprint=diagnostics.embedding).embed(
            ["最近30天实际支付金额", "paid amount for the last 30 days"]
        )
    )

    assert len(embeddings) == 2
    assert len(embeddings[0]) > 0
    assert len(embeddings[0]) == len(embeddings[1])


def test_real_ollama_startup_diagnostics() -> None:
    settings = _settings()
    diagnostics = asyncio.run(OllamaStartupDiagnostics(settings).diagnose())

    assert diagnostics.chat.model == settings.ollama_chat_model
    assert diagnostics.embedding.model == settings.ollama_embed_model
    assert "completion" in diagnostics.chat.capabilities
    assert "embedding" in diagnostics.embedding.capabilities
