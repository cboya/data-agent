"""FastAPI application boundary."""

from fastapi import FastAPI

from data_agent.config import Settings
from data_agent.observability import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the HTTP application without creating infrastructure clients."""
    resolved_settings = settings or Settings()  # type: ignore[call-arg]
    configure_logging(resolved_settings.log_level)

    app = FastAPI(title="Data Agent", version="0.1.0")
    app.state.settings = resolved_settings

    @app.get("/health", tags=["diagnostics"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
