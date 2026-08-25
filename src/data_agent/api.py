"""FastAPI application boundary."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from data_agent.config import Settings
from data_agent.model_runtime.ollama import OllamaStartupDiagnostics
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
    probe = model_runtime_probe or OllamaStartupDiagnostics(resolved_settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.model_runtime_diagnostics = await probe.diagnose()
        yield

    app = FastAPI(title="Data Agent", version="0.1.0", lifespan=lifespan)
    app.state.settings = resolved_settings

    @app.get("/health", tags=["diagnostics"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
