"""FastAPI application boundary."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from data_agent.config import Settings
from data_agent.conversation.models import (
    ConversationResponse,
    RunView,
    SessionView,
)
from data_agent.conversation.runtime import (
    ConversationApplicationPort,
    build_conversation_application,
)
from data_agent.model_runtime.ollama import (
    OllamaChatModel,
    OllamaEmbeddingModel,
    OllamaStartupDiagnostics,
)
from data_agent.model_runtime.ports import ModelRuntimeProbe
from data_agent.observability import configure_logging
from data_agent.persistence.errors import RecordNotFoundError


class MessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=20_000)

    @field_validator("content")
    @classmethod
    def content_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must contain a non-whitespace character")
        return value


def create_app(
    settings: Settings | None = None,
    *,
    model_runtime_probe: ModelRuntimeProbe | None = None,
    conversation_application: ConversationApplicationPort | None = None,
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
            chat_model = OllamaChatModel(
                resolved_settings,
                fingerprint=diagnostics.chat,
            )
            embedding_model = OllamaEmbeddingModel(
                resolved_settings,
                fingerprint=diagnostics.embedding,
            )
            app.state.chat_model = chat_model
            app.state.embedding_model = embedding_model
            if conversation_application is None:
                app.state.conversation_application = build_conversation_application(
                    resolved_settings,
                    diagnostics=diagnostics,
                    chat_model=chat_model,
                    embedding_model=embedding_model,
                )
        yield

    app = FastAPI(title="Data Agent", version="0.1.0", lifespan=lifespan)
    app.state.settings = resolved_settings
    app.state.conversation_application = conversation_application

    def conversation(request: Request) -> ConversationApplicationPort:
        application = cast(
            ConversationApplicationPort | None,
            request.app.state.conversation_application,
        )
        if application is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "CONVERSATION_RUNTIME_UNAVAILABLE",
                    "message": "Conversation runtime is not configured.",
                },
            )
        return application

    def not_found(error: RecordNotFoundError) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": str(error)},
        )

    @app.get("/health", tags=["diagnostics"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post(
        "/sessions",
        tags=["conversation"],
        response_model=SessionView,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_session(request: Request) -> SessionView:
        return conversation(request).create_session()

    @app.get(
        "/sessions/{session_id}",
        tags=["conversation"],
        response_model=SessionView,
    )
    async def get_session(session_id: str, request: Request) -> SessionView:
        try:
            return conversation(request).get_session(session_id)
        except RecordNotFoundError as error:
            raise not_found(error) from error

    @app.get(
        "/runs/{run_id}",
        tags=["conversation"],
        response_model=RunView,
    )
    async def get_run(run_id: str, request: Request) -> RunView:
        try:
            return conversation(request).get_run(run_id)
        except RecordNotFoundError as error:
            raise not_found(error) from error

    @app.post(
        "/sessions/{session_id}/messages",
        tags=["conversation"],
        response_model=ConversationResponse,
    )
    async def post_message(
        session_id: str,
        payload: MessageRequest,
        request: Request,
    ) -> ConversationResponse:
        application = conversation(request)
        try:
            application.get_session(session_id)
            return await application.process_message(
                session_id=session_id,
                content=payload.content,
            )
        except RecordNotFoundError as error:
            raise not_found(error) from error

    return app
