import asyncio

import httpx

from data_agent.api import create_app
from data_agent.config import Settings


def test_health_endpoint(settings: Settings) -> None:
    async def request_health() -> httpx.Response:
        app = create_app(settings)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/health")

    response = asyncio.run(request_health())

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
