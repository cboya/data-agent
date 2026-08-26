import asyncio
from datetime import UTC, datetime

import httpx
import pytest

from data_agent.api import create_app
from data_agent.config import Settings
from data_agent.contracts.requirement import RequirementState, RequirementStatus
from data_agent.contracts.run import RunStatus
from data_agent.contracts.session import SessionStatus
from data_agent.conversation.models import (
    ClarificationResponse,
    ConversationResponse,
    RunView,
    SessionView,
)
from data_agent.model_runtime.errors import ModelUnavailableError
from data_agent.model_runtime.ports import (
    ModelFingerprint,
    ModelRuntimeDiagnostics,
)
from data_agent.persistence.errors import RecordNotFoundError

NOW = datetime(2026, 8, 26, tzinfo=UTC)


class StubConversationApplication:
    def __init__(self) -> None:
        self.session = SessionView(
            id="session-api",
            status=SessionStatus.ACTIVE,
            requirement=RequirementState(
                version="v0.1", status=RequirementStatus.INCOMPLETE
            ).model_dump(mode="json"),
            revision=0,
            created_at=NOW,
            updated_at=NOW,
        )
        self.run = RunView(
            id="run-api",
            session_id="session-api",
            status=RunStatus.CLARIFYING,
            repair_count=0,
            started_at=NOW,
            completed_at=NOW,
            error_code=None,
        )
        self.messages: list[str] = []

    def create_session(self) -> SessionView:
        return self.session

    def get_session(self, session_id: str) -> SessionView:
        if session_id != self.session.id:
            raise RecordNotFoundError("Session does not exist")
        return self.session

    def get_run(self, run_id: str) -> RunView:
        if run_id != self.run.id:
            raise RecordNotFoundError("Run does not exist")
        return self.run

    async def process_message(self, *, session_id: str, content: str) -> ConversationResponse:
        self.messages.append(content)
        return ClarificationResponse(
            session_id=session_id,
            run_id=str(self.run.id),
            question="你想使用哪个指标?",
            requirement=self.session.requirement,
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


def test_conversation_http_surface_is_typed(settings: Settings) -> None:
    async def requests() -> tuple[httpx.Response, ...]:
        application = StubConversationApplication()
        app = create_app(
            settings,
            model_runtime_probe=SuccessfulModelRuntimeProbe(),
            conversation_application=application,
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post("/sessions")
            session = await client.get("/sessions/session-api")
            response = await client.post(
                "/sessions/session-api/messages",
                json={"content": "看看销售"},
            )
            run = await client.get("/runs/run-api")
        assert application.messages == ["看看销售"]
        return created, session, response, run

    created, session, response, run = asyncio.run(requests())

    assert created.status_code == 201
    assert created.json()["id"] == "session-api"
    assert session.status_code == 200
    assert response.status_code == 200
    assert response.json()["type"] == "clarification"
    assert response.json()["run_id"] == "run-api"
    assert run.json()["status"] == "CLARIFYING"


def test_conversation_api_rejects_unknown_session_and_blank_message(
    settings: Settings,
) -> None:
    async def requests() -> tuple[httpx.Response, httpx.Response]:
        app = create_app(
            settings,
            model_runtime_probe=SuccessfulModelRuntimeProbe(),
            conversation_application=StubConversationApplication(),
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            missing = await client.get("/sessions/missing")
            blank = await client.post(
                "/sessions/session-api/messages",
                json={"content": "   "},
            )
        return missing, blank

    missing, blank = asyncio.run(requests())

    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "NOT_FOUND"
    assert blank.status_code == 422


def test_end_to_end_api_one_turn_returns_verified_result(settings: Settings) -> None:
    from tests.conversation.factories import MemoryConversationApplication
    from tests.conversation.test_service import _orchestrator

    orchestrator, _, _, _, answer_model, _, uow = _orchestrator()
    application = MemoryConversationApplication(
        orchestrator=orchestrator,
        unit_of_work=uow,
        runs=uow.runs,
    )

    async def request() -> httpx.Response:
        app = create_app(
            settings,
            model_runtime_probe=SuccessfulModelRuntimeProbe(),
            conversation_application=application,
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                "/sessions/session-m14/messages",
                json={"content": "最近支付金额"},
            )

    response = asyncio.run(request())

    assert response.status_code == 200
    assert response.json()["type"] == "result"
    assert response.json()["data"]["rows"][0][2] == "100.00"
    assert response.json()["verification"]["scope"] == "COVERAGE_BOUNDED"
    assert len(answer_model.calls) == 1


def test_end_to_end_api_multi_turn_clarification_then_result(settings: Settings) -> None:
    from data_agent.contracts.dialogue import DialogueAction
    from tests.conversation.factories import MemoryConversationApplication
    from tests.conversation.test_service import _orchestrator

    orchestrator, _, _, _, _, runs, uow = _orchestrator(
        actions=(DialogueAction.ASK_CLARIFICATION, DialogueAction.READY)
    )
    application = MemoryConversationApplication(
        orchestrator=orchestrator,
        unit_of_work=uow,
        runs=runs,
    )

    async def requests() -> tuple[httpx.Response, httpx.Response]:
        app = create_app(
            settings,
            model_runtime_probe=SuccessfulModelRuntimeProbe(),
            conversation_application=application,
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post(
                "/sessions/session-m14/messages", json={"content": "看看销售"}
            )
            second = await client.post(
                "/sessions/session-m14/messages", json={"content": "使用实付金额"}
            )
        return first, second

    first, second = asyncio.run(requests())

    assert first.json()["type"] == "clarification"
    assert second.json()["type"] == "result"
    assert first.json()["run_id"] != second.json()["run_id"]


def test_end_to_end_api_repair_and_terminal_policy_paths_are_typed(
    settings: Settings,
) -> None:
    from dataclasses import replace

    from tests.conversation.factories import MemoryConversationApplication
    from tests.conversation.test_service import _AlwaysFailedVerifier, _orchestrator
    from tests.verification.factories import evidence_bundle, valid_plan

    repaired_parts = _orchestrator(verifier=_AlwaysFailedVerifier())
    repaired_app = MemoryConversationApplication(
        orchestrator=repaired_parts[0],
        unit_of_work=repaired_parts[6],
        runs=repaired_parts[5],
    )
    original = evidence_bundle().planning_trace
    denied_parts = _orchestrator(
        planning_trace=replace(original, plan=valid_plan(sql="DELETE FROM fact_order"))
    )
    denied_app = MemoryConversationApplication(
        orchestrator=denied_parts[0],
        unit_of_work=denied_parts[6],
        runs=denied_parts[5],
    )

    async def request(application: MemoryConversationApplication) -> httpx.Response:
        app = create_app(
            settings,
            model_runtime_probe=SuccessfulModelRuntimeProbe(),
            conversation_application=application,
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                "/sessions/session-m14/messages",
                json={"content": "最近支付金额"},
            )

    async def requests() -> tuple[httpx.Response, httpx.Response]:
        return await request(repaired_app), await request(denied_app)

    repaired, denied = asyncio.run(requests())

    assert repaired.json()["type"] == "result"
    assert repaired.json()["evidence"]["repair_count"] == 1
    assert denied.json()["type"] == "failure"
    assert denied.json()["status"] == "POLICY_DENIED"
    assert denied_parts[4].calls == []
