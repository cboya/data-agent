import asyncio

import httpx
import pytest

from data_agent.api import create_app
from data_agent.config import Settings
from data_agent.model_runtime.errors import ModelUnavailableError
from data_agent.model_runtime.ports import (
    ModelFingerprint,
    ModelRuntimeDiagnostics,
)


class SuccessfulModelRuntimeProbe:
    async def diagnose(self) -> ModelRuntimeDiagnostics:
        chat = ModelFingerprint(
            provider="test",
            model="chat",
            digest="chat-digest",
            capabilities=("completion",),
        )
        embedding = ModelFingerprint(
            provider="test",
            model="embedding",
            digest="embedding-digest",
            capabilities=("embedding",),
        )
        return ModelRuntimeDiagnostics(
            provider="test",
            runtime_version="test-version",
            chat=chat,
            embedding=embedding,
        )


class FailingModelRuntimeProbe:
    async def diagnose(self) -> ModelRuntimeDiagnostics:
        raise ModelUnavailableError("configured model unavailable")


def test_health_endpoint(settings: Settings) -> None:
    async def request_health() -> httpx.Response:
        app = create_app(settings, model_runtime_probe=SuccessfulModelRuntimeProbe())
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/health")

    response = asyncio.run(request_health())

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_application_startup_records_model_runtime_diagnostics(settings: Settings) -> None:
    async def start() -> ModelRuntimeDiagnostics:
        app = create_app(settings, model_runtime_probe=SuccessfulModelRuntimeProbe())
        async with app.router.lifespan_context(app):
            return app.state.model_runtime_diagnostics  # type: ignore[no-any-return]

    diagnostics = asyncio.run(start())
    assert diagnostics.provider == "test"
    assert diagnostics.chat.model == "chat"


def test_application_startup_fails_when_configured_model_is_unavailable(
    settings: Settings,
) -> None:
    async def start() -> None:
        app = create_app(settings, model_runtime_probe=FailingModelRuntimeProbe())
        async with app.router.lifespan_context(app):
            pass

    with pytest.raises(ModelUnavailableError, match="unavailable"):
        asyncio.run(start())
