import asyncio
from typing import Any, Literal

import pytest

from data_agent.config import Settings
from data_agent.contracts.base import ContractModel
from data_agent.model_runtime.errors import (
    ModelContractError,
    ModelIdentityDriftError,
    ModelResponseError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from data_agent.model_runtime.ollama import (
    JsonObject,
    OllamaChatModel,
    OllamaEmbeddingModel,
    OllamaStartupDiagnostics,
    UrllibOllamaTransport,
)
from data_agent.model_runtime.ports import ChatModel, EmbeddingModel, ModelFingerprint


class SmokeResult(ContractModel):
    status: Literal["ok"]


class StubTransport:
    def __init__(self, responses: list[JsonObject]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, JsonObject | None]] = []

    async def request(
        self,
        method: str,
        path: str,
        payload: JsonObject | None = None,
    ) -> JsonObject:
        self.calls.append((method, path, payload))
        if not self.responses:
            raise AssertionError("unexpected transport request")
        return self.responses.pop(0)


def _run(awaitable: Any) -> Any:
    return asyncio.run(awaitable)


def _chat_fingerprint(settings: Settings, digest: str = "chat-digest") -> ModelFingerprint:
    return ModelFingerprint(
        provider="ollama",
        model=settings.ollama_chat_model,
        digest=digest,
        capabilities=("completion",),
    )


def _embedding_fingerprint(settings: Settings, digest: str = "embed-digest") -> ModelFingerprint:
    return ModelFingerprint(
        provider="ollama",
        model=settings.ollama_embed_model,
        digest=digest,
        capabilities=("embedding",),
    )


def _tags(
    settings: Settings,
    *,
    chat_digest: str = "chat-digest",
    embed_digest: str = "embed-digest",
) -> JsonObject:
    return {
        "models": [
            {"name": settings.ollama_chat_model, "digest": chat_digest},
            {"name": settings.ollama_embed_model, "digest": embed_digest},
        ]
    }


def test_structured_chat_sends_json_schema_and_revalidates_output(settings: Settings) -> None:
    transport = StubTransport(
        [
            _tags(settings),
            {"done": True, "message": {"role": "assistant", "content": '{"status":"ok"}'}},
        ]
    )
    model: ChatModel = OllamaChatModel(
        settings,
        fingerprint=_chat_fingerprint(settings),
        transport=transport,
    )

    result = _run(
        model.structured(
            messages=[{"role": "user", "content": "Report success"}],
            response_type=SmokeResult,
            purpose="adapter-test",
        )
    )

    assert result == SmokeResult(status="ok")
    assert transport.calls[0] == ("GET", "/api/tags", None)
    method, path, payload = transport.calls[1]
    assert (method, path) == ("POST", "/api/chat")
    assert payload is not None
    assert payload["stream"] is False
    assert payload["think"] is False
    assert payload["format"] == SmokeResult.model_json_schema()
    assert payload["model"] == settings.ollama_chat_model
    assert payload["options"] == {"temperature": 0, "num_predict": 2_048}


@pytest.mark.parametrize(
    "response",
    [
        {"done": False, "message": {"content": '{"status":"ok"}'}},
        {"done": True},
        {"done": True, "message": {"content": 42}},
    ],
)
def test_structured_chat_rejects_malformed_envelope(
    settings: Settings, response: JsonObject
) -> None:
    model = OllamaChatModel(
        settings,
        fingerprint=_chat_fingerprint(settings),
        transport=StubTransport([_tags(settings), response]),
    )

    with pytest.raises(ModelResponseError):
        _run(
            model.structured(
                messages=[{"role": "user", "content": "Report success"}],
                response_type=SmokeResult,
                purpose="adapter-test",
            )
        )


def test_structured_chat_rejects_contract_invalid_content(settings: Settings) -> None:
    transport = StubTransport(
        [
            _tags(settings),
            {
                "done": True,
                "message": {"content": '{"status":"ok","unexpected":"not allowed"}'},
            },
        ]
    )
    model = OllamaChatModel(
        settings,
        fingerprint=_chat_fingerprint(settings),
        transport=transport,
    )

    with pytest.raises(ModelContractError, match="failed SmokeResult"):
        _run(
            model.structured(
                messages=[{"role": "user", "content": "Report success"}],
                response_type=SmokeResult,
                purpose="adapter-test",
            )
        )


def test_embedding_batch_returns_finite_consistent_vectors(settings: Settings) -> None:
    transport = StubTransport([_tags(settings), {"embeddings": [[1, 2.5], [3.5, 4]]}])
    model: EmbeddingModel = OllamaEmbeddingModel(
        settings,
        fingerprint=_embedding_fingerprint(settings),
        transport=transport,
    )

    embeddings = _run(model.embed(["最近30天实际支付金额", "paid amount last 30 days"]))

    assert embeddings == [[1.0, 2.5], [3.5, 4.0]]
    assert transport.calls[0] == ("GET", "/api/tags", None)
    _, path, payload = transport.calls[1]
    assert path == "/api/embed"
    assert payload is not None
    assert payload["truncate"] is False
    assert payload["model"] == settings.ollama_embed_model


@pytest.mark.parametrize(
    "response",
    [
        {"embeddings": [[1.0, 2.0]]},
        {"embeddings": [[1.0], [1.0, 2.0]]},
        {"embeddings": [[1.0, float("nan")], [2.0, 3.0]]},
        {"embeddings": [[1.0, True], [2.0, 3.0]]},
    ],
)
def test_embedding_response_invariants_fail_closed(
    settings: Settings, response: JsonObject
) -> None:
    model = OllamaEmbeddingModel(
        settings,
        fingerprint=_embedding_fingerprint(settings),
        transport=StubTransport([_tags(settings), response]),
    )

    with pytest.raises(ModelResponseError):
        _run(model.embed(["中文", "English"]))


def test_embedding_input_batch_is_bounded(settings: Settings) -> None:
    limited = settings.model_copy(update={"ollama_max_embedding_batch": 1})
    model = OllamaEmbeddingModel(
        limited,
        fingerprint=_embedding_fingerprint(limited),
        transport=StubTransport([]),
    )

    with pytest.raises(ModelContractError, match="configured limit"):
        _run(model.embed(["one", "two"]))


@pytest.mark.parametrize("texts", [[], ["   "]])
def test_embedding_input_must_be_nonempty(settings: Settings, texts: list[str]) -> None:
    model = OllamaEmbeddingModel(
        settings,
        fingerprint=_embedding_fingerprint(settings),
        transport=StubTransport([]),
    )

    with pytest.raises(ModelContractError):
        _run(model.embed(texts))


def test_startup_diagnostics_validate_capabilities_and_fingerprint(settings: Settings) -> None:
    transport = StubTransport(
        [
            {"version": "0.32.15"},
            {
                "models": [
                    {"name": settings.ollama_chat_model, "digest": "chat-digest"},
                    {"name": settings.ollama_embed_model, "digest": "embed-digest"},
                ]
            },
            {
                "capabilities": ["completion", "thinking"],
                "details": {
                    "family": "gemma4",
                    "parameter_size": "8B",
                    "quantization_level": "Q4",
                },
            },
            {
                "capabilities": ["embedding"],
                "details": {
                    "family": "qwen3",
                    "parameter_size": "0.6B",
                    "quantization_level": "Q8",
                },
            },
            _tags(settings),
        ]
    )

    diagnostics = _run(OllamaStartupDiagnostics(settings, transport=transport).diagnose())

    assert diagnostics.provider == "ollama"
    assert diagnostics.runtime_version == "0.32.15"
    assert diagnostics.chat.model == settings.ollama_chat_model
    assert diagnostics.embedding.model == settings.ollama_embed_model
    assert len(diagnostics.chat.value) == 64
    assert diagnostics.chat.value == diagnostics.chat.value
    assert diagnostics.chat.value != diagnostics.embedding.value


def test_startup_diagnostics_reject_missing_model(settings: Settings) -> None:
    transport = StubTransport([{"version": "0.32.15"}, {"models": []}])

    with pytest.raises(ModelUnavailableError, match=settings.ollama_chat_model):
        _run(OllamaStartupDiagnostics(settings, transport=transport).diagnose())


def test_startup_diagnostics_reject_missing_capability(settings: Settings) -> None:
    transport = StubTransport(
        [
            {"version": "0.32.15"},
            {
                "models": [
                    {"name": settings.ollama_chat_model, "digest": "chat-digest"},
                    {"name": settings.ollama_embed_model, "digest": "embed-digest"},
                ]
            },
            {"capabilities": ["embedding"], "details": {}},
        ]
    )

    with pytest.raises(ModelUnavailableError, match="completion capability"):
        _run(OllamaStartupDiagnostics(settings, transport=transport).diagnose())


def test_structured_chat_rejects_tag_identity_drift_before_execution(settings: Settings) -> None:
    transport = StubTransport([_tags(settings, chat_digest="moved-chat-digest")])
    model = OllamaChatModel(
        settings,
        fingerprint=_chat_fingerprint(settings),
        transport=transport,
    )

    with pytest.raises(ModelIdentityDriftError, match=settings.ollama_chat_model):
        _run(
            model.structured(
                messages=[{"role": "user", "content": "Report success"}],
                response_type=SmokeResult,
                purpose="adapter-test",
            )
        )

    assert transport.calls == [("GET", "/api/tags", None)]


def test_embedding_rejects_tag_identity_drift_before_execution(settings: Settings) -> None:
    transport = StubTransport([_tags(settings, embed_digest="moved-embed-digest")])
    model = OllamaEmbeddingModel(
        settings,
        fingerprint=_embedding_fingerprint(settings),
        transport=transport,
    )

    with pytest.raises(ModelIdentityDriftError, match=settings.ollama_embed_model):
        _run(model.embed(["bound identity"]))

    assert transport.calls == [("GET", "/api/tags", None)]


def test_startup_diagnostics_reject_tag_move_during_capability_probe(
    settings: Settings,
) -> None:
    transport = StubTransport(
        [
            {"version": "0.32.15"},
            _tags(settings),
            {"capabilities": ["completion"], "details": {}},
            {"capabilities": ["embedding"], "details": {}},
            _tags(settings, chat_digest="moved-chat-digest"),
        ]
    )

    with pytest.raises(ModelIdentityDriftError, match=settings.ollama_chat_model):
        _run(OllamaStartupDiagnostics(settings, transport=transport).diagnose())


def test_urllib_transport_classifies_timeout(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def timeout(*args: object, **kwargs: object) -> None:
        raise TimeoutError

    monkeypatch.setattr("data_agent.model_runtime.ollama.urlopen", timeout)

    with pytest.raises(ModelTimeoutError, match="configured timeout"):
        _run(UrllibOllamaTransport(settings).request("GET", "/api/version"))
