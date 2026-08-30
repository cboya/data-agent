"""Configuration-owned model-runtime selection and adapter binding."""

from __future__ import annotations

from dataclasses import dataclass

from data_agent.config import Settings
from data_agent.model_runtime.ollama import (
    OllamaChatModel,
    OllamaEmbeddingModel,
    OllamaJsonTransport,
    OllamaStartupDiagnostics,
)
from data_agent.model_runtime.openai_compatible import (
    OpenAICompatibleChatModel,
    OpenAICompatibleEmbeddingModel,
    OpenAICompatibleJsonTransport,
    OpenAICompatibleStartupDiagnostics,
)
from data_agent.model_runtime.ports import (
    ChatModel,
    EmbeddingModel,
    ModelFingerprint,
    ModelIdentityAssurance,
    ModelRuntimeDiagnostics,
)


@dataclass(frozen=True)
class ModelRuntimeResourceEvidence:
    """Provider-neutral identity and bounds for the exact selected runtime."""

    provider: str
    runtime_version: str
    chat_fingerprint: ModelFingerprint
    embedding_fingerprint: ModelFingerprint
    request_timeout_seconds: float
    max_output_tokens: int

    @property
    def product_acceptance_identity_eligible(self) -> bool:
        return all(
            fingerprint.identity_assurance is not ModelIdentityAssurance.ALIAS_ONLY
            for fingerprint in (self.chat_fingerprint, self.embedding_fingerprint)
        )


@dataclass(frozen=True)
class BoundModelRuntime:
    diagnostics: ModelRuntimeDiagnostics
    chat_model: ChatModel
    embedding_model: EmbeddingModel
    embedding_batch_size: int
    request_timeout_seconds: float
    max_output_tokens: int

    @property
    def resource_evidence(self) -> ModelRuntimeResourceEvidence:
        return ModelRuntimeResourceEvidence(
            provider=self.diagnostics.provider,
            runtime_version=self.diagnostics.runtime_version,
            chat_fingerprint=self.diagnostics.chat,
            embedding_fingerprint=self.diagnostics.embedding,
            request_timeout_seconds=self.request_timeout_seconds,
            max_output_tokens=self.max_output_tokens,
        )


async def start_model_runtime(
    settings: Settings,
    *,
    ollama_transport: OllamaJsonTransport | None = None,
    openai_compatible_transport: OpenAICompatibleJsonTransport | None = None,
) -> BoundModelRuntime:
    """Diagnose and bind the configured provider once at a composition boundary."""
    if settings.model_runtime_provider == "ollama":
        diagnostics = await OllamaStartupDiagnostics(
            settings,
            transport=ollama_transport,
        ).diagnose()
        return BoundModelRuntime(
            diagnostics=diagnostics,
            chat_model=OllamaChatModel(
                settings,
                fingerprint=diagnostics.chat,
                transport=ollama_transport,
            ),
            embedding_model=OllamaEmbeddingModel(
                settings,
                fingerprint=diagnostics.embedding,
                transport=ollama_transport,
            ),
            embedding_batch_size=settings.ollama_max_embedding_batch,
            request_timeout_seconds=settings.ollama_request_timeout_seconds,
            max_output_tokens=settings.ollama_max_output_tokens,
        )

    diagnostics = await OpenAICompatibleStartupDiagnostics(
        settings,
        transport=openai_compatible_transport,
    ).diagnose()
    return BoundModelRuntime(
        diagnostics=diagnostics,
        chat_model=OpenAICompatibleChatModel(
            settings,
            fingerprint=diagnostics.chat,
            transport=openai_compatible_transport,
        ),
        embedding_model=OpenAICompatibleEmbeddingModel(
            settings,
            fingerprint=diagnostics.embedding,
            transport=openai_compatible_transport,
        ),
        embedding_batch_size=settings.openai_compatible_max_embedding_batch,
        request_timeout_seconds=settings.openai_compatible_request_timeout_seconds,
        max_output_tokens=settings.openai_compatible_max_output_tokens,
    )


def with_planner_request_timeout(settings: Settings) -> Settings:
    """Apply the existing planner-eval timeout to whichever provider is selected."""
    field = (
        "ollama_request_timeout_seconds"
        if settings.model_runtime_provider == "ollama"
        else "openai_compatible_request_timeout_seconds"
    )
    return settings.model_copy(
        update={field: settings.planner_eval_request_timeout_seconds},
    )
