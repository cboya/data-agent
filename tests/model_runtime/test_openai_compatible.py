import asyncio
from email.message import Message
from typing import Any, Literal
from urllib.error import HTTPError

import pytest
from pydantic import SecretStr

from data_agent.config import Settings
from data_agent.contracts.base import ContractModel
from data_agent.model_runtime.composition import start_model_runtime
from data_agent.model_runtime.errors import (
    ModelContractError,
    ModelIdentityDriftError,
    ModelProviderError,
    ModelResponseError,
    ModelTimeoutError,
)
from data_agent.model_runtime.ollama import OllamaChatModel, OllamaEmbeddingModel
from data_agent.model_runtime.openai_compatible import (
    JsonObject,
    OpenAICompatibleChatModel,
    OpenAICompatibleEmbeddingModel,
    OpenAICompatibleStartupDiagnostics,
    UrllibOpenAICompatibleTransport,
)
from data_agent.model_runtime.ports import ModelIdentityAssurance


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


def _remote_settings(settings: Settings, **updates: object) -> Settings:
    values = settings.model_dump()
    values.update(
        {
            "model_runtime_provider": "openai_compatible",
            "openai_compatible_base_url": "https://models.example.test/v1",
            "openai_compatible_api_key": SecretStr("remote-test-secret"),
            "openai_compatible_chat_model": "chat-deployment",
            "openai_compatible_embed_model": "embed-deployment",
        }
    )
    values.update(updates)
    return Settings.model_validate(values)


def _descriptor(
    model: str,
    *,
    revision: str | None = None,
    provider_version: str = "provider-2026.08",
) -> JsonObject:
    result: JsonObject = {
        "id": model,
        "object": "model",
        "created": 1_777_593_600,
        "owned_by": "example-provider",
        "provider_version": provider_version,
    }
    if revision is not None:
        result["revision"] = revision
    return result


def _diagnostics(
    settings: Settings,
    *,
    revision: str | None = None,
) -> Any:
    chat = _descriptor(settings.openai_compatible_chat_model or "", revision=revision)
    embedding = _descriptor(settings.openai_compatible_embed_model or "", revision=revision)
    return _run(
        OpenAICompatibleStartupDiagnostics(
            settings,
            transport=StubTransport([chat, embedding, chat, embedding]),
        ).diagnose()
    )


def _chat_response(settings: Settings, content: str = '{"status":"ok"}') -> JsonObject:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": settings.openai_compatible_chat_model,
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content, "refusal": None},
            }
        ],
    }


def test_remote_structured_chat_sends_strict_schema_and_revalidates_output(
    settings: Settings,
) -> None:
    remote = _remote_settings(settings)
    diagnostics = _diagnostics(remote)
    descriptor = _descriptor(remote.openai_compatible_chat_model or "")
    transport = StubTransport([descriptor, _chat_response(remote)])
    model = OpenAICompatibleChatModel(
        remote,
        fingerprint=diagnostics.chat,
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
    assert transport.calls[0] == (
        "GET",
        "/models/chat-deployment",
        None,
    )
    method, path, payload = transport.calls[1]
    assert (method, path) == ("POST", "/chat/completions")
    assert payload is not None
    assert payload["model"] == "chat-deployment"
    assert payload["temperature"] == 0
    assert payload["max_completion_tokens"] == 2_048
    assert payload["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "SmokeResult",
            "strict": True,
            "schema": SmokeResult.model_json_schema(),
        },
    }


def test_remote_structured_chat_rejects_contract_invalid_content(settings: Settings) -> None:
    remote = _remote_settings(settings)
    diagnostics = _diagnostics(remote)
    transport = StubTransport(
        [
            _descriptor(remote.openai_compatible_chat_model or ""),
            _chat_response(remote, '{"status":"ok","unexpected":true}'),
        ]
    )
    model = OpenAICompatibleChatModel(
        remote,
        fingerprint=diagnostics.chat,
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


def test_remote_structured_chat_rejects_incomplete_generation(settings: Settings) -> None:
    remote = _remote_settings(settings)
    diagnostics = _diagnostics(remote)
    response = _chat_response(remote)
    response["choices"][0]["finish_reason"] = "length"
    transport = StubTransport([_descriptor(remote.openai_compatible_chat_model or ""), response])
    model = OpenAICompatibleChatModel(
        remote,
        fingerprint=diagnostics.chat,
        transport=transport,
    )

    with pytest.raises(ModelResponseError, match="did not finish cleanly"):
        _run(
            model.structured(
                messages=[{"role": "user", "content": "Report success"}],
                response_type=SmokeResult,
                purpose="adapter-test",
            )
        )
    assert len(transport.calls) == 2


@pytest.mark.parametrize(
    "response",
    [
        {"model": "chat-deployment", "choices": []},
        {
            "model": "chat-deployment",
            "choices": [{"finish_reason": "stop", "message": {"content": 42}}],
        },
        {
            "model": "different-deployment",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": '{"status":"ok"}'},
                }
            ],
        },
    ],
)
def test_remote_structured_chat_rejects_malformed_envelope(
    settings: Settings,
    response: JsonObject,
) -> None:
    remote = _remote_settings(settings)
    diagnostics = _diagnostics(remote)
    transport = StubTransport([_descriptor(remote.openai_compatible_chat_model or ""), response])
    model = OpenAICompatibleChatModel(
        remote,
        fingerprint=diagnostics.chat,
        transport=transport,
    )

    with pytest.raises((ModelResponseError, ModelIdentityDriftError)):
        _run(
            model.structured(
                messages=[{"role": "user", "content": "Report success"}],
                response_type=SmokeResult,
                purpose="adapter-test",
            )
        )


def test_remote_embedding_batch_restores_index_order(settings: Settings) -> None:
    remote = _remote_settings(settings)
    diagnostics = _diagnostics(remote)
    transport = StubTransport(
        [
            _descriptor(remote.openai_compatible_embed_model or ""),
            {
                "object": "list",
                "model": remote.openai_compatible_embed_model,
                "data": [
                    {"object": "embedding", "index": 1, "embedding": [3, 4.5]},
                    {"object": "embedding", "index": 0, "embedding": [1.0, 2]},
                ],
            },
        ]
    )
    model = OpenAICompatibleEmbeddingModel(
        remote,
        fingerprint=diagnostics.embedding,
        transport=transport,
    )

    vectors = _run(model.embed(["最近30天实际支付金额", "paid amount last 30 days"]))

    assert vectors == [[1.0, 2.0], [3.0, 4.5]]
    _, path, payload = transport.calls[1]
    assert path == "/embeddings"
    assert payload == {
        "model": "embed-deployment",
        "input": ["最近30天实际支付金额", "paid amount last 30 days"],
        "encoding_format": "float",
    }


@pytest.mark.parametrize(
    "data",
    [
        [{"index": 0, "embedding": [1.0, 2.0]}],
        [
            {"index": 0, "embedding": [1.0]},
            {"index": 1, "embedding": [1.0, 2.0]},
        ],
        [
            {"index": 0, "embedding": [1.0, float("nan")]},
            {"index": 1, "embedding": [2.0, 3.0]},
        ],
        [
            {"index": 0, "embedding": [1.0, True]},
            {"index": 1, "embedding": [2.0, 3.0]},
        ],
        [
            {"index": 0, "embedding": [1.0, 2.0]},
            {"index": 0, "embedding": [2.0, 3.0]},
        ],
    ],
)
def test_remote_embedding_invariants_fail_closed(
    settings: Settings,
    data: list[dict[str, object]],
) -> None:
    remote = _remote_settings(settings)
    diagnostics = _diagnostics(remote)
    transport = StubTransport(
        [
            _descriptor(remote.openai_compatible_embed_model or ""),
            {"model": remote.openai_compatible_embed_model, "data": data},
        ]
    )
    model = OpenAICompatibleEmbeddingModel(
        remote,
        fingerprint=diagnostics.embedding,
        transport=transport,
    )

    with pytest.raises(ModelResponseError):
        _run(model.embed(["one", "two"]))


def test_remote_embedding_input_batch_is_bounded(settings: Settings) -> None:
    remote = _remote_settings(settings, openai_compatible_max_embedding_batch=1)
    diagnostics = _diagnostics(remote)
    model = OpenAICompatibleEmbeddingModel(
        remote,
        fingerprint=diagnostics.embedding,
        transport=StubTransport([]),
    )

    with pytest.raises(ModelContractError, match="configured limit"):
        _run(model.embed(["one", "two"]))


@pytest.mark.parametrize("texts", [[], ["   "]])
def test_remote_embedding_input_must_be_nonempty(
    settings: Settings,
    texts: list[str],
) -> None:
    remote = _remote_settings(settings)
    diagnostics = _diagnostics(remote)
    model = OpenAICompatibleEmbeddingModel(
        remote,
        fingerprint=diagnostics.embedding,
        transport=StubTransport([]),
    )

    with pytest.raises(ModelContractError):
        _run(model.embed(texts))


def test_remote_alias_identity_is_honest_stable_and_endpoint_bound(settings: Settings) -> None:
    remote = _remote_settings(settings)
    first = _diagnostics(remote)
    second = _diagnostics(remote)

    assert first.provider == "openai_compatible"
    assert first.runtime_version == "provider-2026.08"
    assert first.chat.digest is None
    assert first.chat.provider_revision is None
    assert first.chat.identity_assurance is ModelIdentityAssurance.ALIAS_ONLY
    assert first.chat.endpoint_identity is not None
    assert first.chat.value == second.chat.value
    assert first.chat.value != first.embedding.value


def test_remote_revision_drift_fails_before_chat_execution(settings: Settings) -> None:
    remote = _remote_settings(settings)
    diagnostics = _diagnostics(remote, revision="snapshot-a")
    assert diagnostics.chat.identity_assurance is ModelIdentityAssurance.IMMUTABLE_PROVIDER_REVISION
    assert diagnostics.chat.digest is None
    assert diagnostics.chat.provider_revision == "snapshot-a"
    transport = StubTransport(
        [_descriptor(remote.openai_compatible_chat_model or "", revision="snapshot-b")]
    )
    model = OpenAICompatibleChatModel(
        remote,
        fingerprint=diagnostics.chat,
        transport=transport,
    )

    with pytest.raises(ModelIdentityDriftError, match="identity drifted"):
        _run(
            model.structured(
                messages=[{"role": "user", "content": "Report success"}],
                response_type=SmokeResult,
                purpose="adapter-test",
            )
        )
    assert transport.calls == [("GET", "/models/chat-deployment", None)]


def test_remote_startup_rejects_runtime_version_drift(settings: Settings) -> None:
    remote = _remote_settings(settings)
    chat = remote.openai_compatible_chat_model or ""
    embedding = remote.openai_compatible_embed_model or ""
    transport = StubTransport(
        [
            _descriptor(chat, provider_version="provider-a"),
            _descriptor(embedding, provider_version="provider-a"),
            _descriptor(chat, provider_version="provider-b"),
            _descriptor(embedding, provider_version="provider-a"),
        ]
    )

    with pytest.raises(ModelIdentityDriftError, match="runtime identity drifted"):
        _run(OpenAICompatibleStartupDiagnostics(remote, transport=transport).diagnose())


def test_configured_runtime_selects_remote_and_ollama(settings: Settings) -> None:
    remote = _remote_settings(settings)
    chat = _descriptor(remote.openai_compatible_chat_model or "")
    embedding = _descriptor(remote.openai_compatible_embed_model or "")
    remote_runtime = _run(
        start_model_runtime(
            remote,
            openai_compatible_transport=StubTransport([chat, embedding, chat, embedding]),
        )
    )
    assert isinstance(remote_runtime.chat_model, OpenAICompatibleChatModel)
    assert isinstance(remote_runtime.embedding_model, OpenAICompatibleEmbeddingModel)

    tags = {
        "models": [
            {"name": settings.ollama_chat_model, "digest": "chat-digest"},
            {"name": settings.ollama_embed_model, "digest": "embed-digest"},
        ]
    }
    ollama_runtime = _run(
        start_model_runtime(
            settings,
            ollama_transport=StubTransport(
                [
                    {"version": "0.32.15"},
                    tags,
                    {"capabilities": ["completion"], "details": {}},
                    {"capabilities": ["embedding"], "details": {}},
                    tags,
                ]
            ),
        )
    )
    assert isinstance(ollama_runtime.chat_model, OllamaChatModel)
    assert isinstance(ollama_runtime.embedding_model, OllamaEmbeddingModel)


def test_transport_maps_provider_error_without_leaking_api_key(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = _remote_settings(settings)

    def provider_error(request: Any, *args: object, **kwargs: object) -> None:
        assert request.get_header("Authorization") == "Bearer remote-test-secret"
        raise HTTPError(
            "https://models.example.test/v1/models/chat-deployment",
            429,
            "rate limited",
            hdrs=Message(),
            fp=None,
        )

    monkeypatch.setattr(
        "data_agent.model_runtime.openai_compatible.urlopen",
        provider_error,
    )

    with pytest.raises(ModelProviderError, match="HTTP 429") as captured:
        _run(UrllibOpenAICompatibleTransport(remote).request("GET", "/models/chat-deployment"))
    assert "remote-test-secret" not in str(captured.value)
    assert "rate limited" not in str(captured.value)


def test_transport_classifies_timeout(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = _remote_settings(settings)

    def timeout(*args: object, **kwargs: object) -> None:
        raise TimeoutError

    monkeypatch.setattr("data_agent.model_runtime.openai_compatible.urlopen", timeout)

    with pytest.raises(ModelTimeoutError, match="configured timeout"):
        _run(UrllibOpenAICompatibleTransport(remote).request("GET", "/models/chat-deployment"))


def test_transport_enforces_response_byte_bound(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = _remote_settings(settings, openai_compatible_max_response_bytes=1_024)

    class OversizedResponse:
        def __enter__(self) -> "OversizedResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, amount: int) -> bytes:
            assert amount == 1_025
            return b"x" * amount

    monkeypatch.setattr(
        "data_agent.model_runtime.openai_compatible.urlopen",
        lambda *args, **kwargs: OversizedResponse(),
    )

    with pytest.raises(ModelResponseError, match="byte limit"):
        _run(UrllibOpenAICompatibleTransport(remote).request("GET", "/models/chat-deployment"))
