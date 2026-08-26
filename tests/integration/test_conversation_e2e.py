"""One real host-only HTTP path through Ollama, MySQL, and M8-M14."""

from __future__ import annotations

import asyncio
import os

import httpx
import pytest

from data_agent.api import create_app
from data_agent.config import Settings

pytestmark = [pytest.mark.integration, pytest.mark.ollama]


@pytest.mark.skipif(
    os.getenv("RUN_OLLAMA_INTEGRATION") != "1",
    reason="set RUN_OLLAMA_INTEGRATION=1 for the host Ollama/MySQL smoke",
)
def test_real_complete_request_reaches_verified_http_result() -> None:
    async def request() -> tuple[httpx.Response, httpx.Response, httpx.Response]:
        settings = Settings()  # type: ignore[call-arg]
        app = create_app(settings)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://test",
            ) as client:
                session = await client.post("/sessions")
                session_id = session.json()["id"]
                result = await client.post(
                    f"/sessions/{session_id}/messages",
                    json={"content": "请按天统计最近30天实际支付金额"},
                )
                run = await client.get(f"/runs/{result.json()['run_id']}")
        return session, result, run

    session, result, run = asyncio.run(request())

    assert session.status_code == 201
    assert result.status_code == 200
    assert result.json()["type"] == "result"
    assert result.json()["verification"]["status"] == "PASSED"
    assert result.json()["verification"]["scope"] == "COVERAGE_BOUNDED"
    assert result.json()["synthesis"]["mode"] in {"MODEL", "DETERMINISTIC_FALLBACK"}
    assert run.status_code == 200
    assert run.json()["status"] == "COMPLETED"
