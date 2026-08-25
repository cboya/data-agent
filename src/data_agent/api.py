"""FastAPI application boundary."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from data_agent.config import Settings
from data_agent.model_runtime.ollama import (
    OllamaChatModel,
    OllamaEmbeddingModel,
    OllamaStartupDiagnostics,
)
from data_agent.model_runtime.ports import ModelRuntimeProbe
from data_agent.observability import configure_logging


def create_app(
    settings: Settings | None = None,
    *,
    model_runtime_probe: ModelRuntimeProbe | None = None,
) -> FastAPI:
    """Build the HTTP application with fail-closed model runtime startup diagnostics."""
    resolved_settings = settings or Settings()  # type: ignore[call-arg]
    configure_logging(resolved_settings.log_level)
    bind_default_ollama_adapters = model_runtime_probe is None
    probe = model_runtime_probe or OllamaStartupDiagnostics(resolved_settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        diagnostics = await probe.diagnose()
        app.state.model_runtime_diagnostics = diagnostics
        if bind_default_ollama_adapters:
            app.state.chat_model = OllamaChatModel(
                resolved_settings,
                fingerprint=diagnostics.chat,
            )
            app.state.embedding_model = OllamaEmbeddingModel(
                resolved_settings,
                fingerprint=diagnostics.embedding,
            )
        yield

    app = FastAPI(title="Data Agent", version="0.1.0", lifespan=lifespan)
    app.state.settings = resolved_settings

    @app.get("/health", tags=["diagnostics"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
