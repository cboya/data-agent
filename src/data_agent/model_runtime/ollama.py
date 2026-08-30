"""Ollama adapters for structured chat, embeddings, and startup diagnostics."""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, ValidationError

from data_agent.config import Settings
from data_agent.model_runtime.errors import (
    ModelContractError,
    ModelIdentityDriftError,
    ModelResponseError,
    ModelTimeoutError,
    ModelTransportError,
    ModelUnavailableError,
)
from data_agent.model_runtime.ports import (
    ModelFingerprint,
    ModelIdentityAssurance,
    ModelRuntimeDiagnostics,
    StructuredResultT,
)

JsonObject = dict[str, Any]


class OllamaJsonTransport(Protocol):
    async def request(
        self,
        method: str,
        path: str,
        payload: JsonObject | None = None,
    ) -> JsonObject: ...


class UrllibOllamaTransport:
    """Small bounded JSON transport using only the Python standard library."""

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.ollama_base_url
        self._timeout = settings.ollama_request_timeout_seconds
        self._max_response_bytes = settings.ollama_max_response_bytes

    async def request(
        self,
        method: str,
        path: str,
        payload: JsonObject | None = None,
    ) -> JsonObject:
        return await asyncio.to_thread(self._request_sync, method, path, payload)

    def _request_sync(
        self,
        method: str,
        path: str,
        payload: JsonObject | None,
    ) -> JsonObject:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self._base_url}{path}",
            data=data,
            method=method,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:
                raw = response.read(self._max_response_bytes + 1)
        except HTTPError as error:
            raise ModelResponseError(f"Ollama HTTP {error.code}: {error.reason}") from error
        except TimeoutError as error:
            raise ModelTimeoutError("Ollama request exceeded configured timeout") from error
        except URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise ModelTimeoutError("Ollama request exceeded configured timeout") from error
            raise ModelTransportError(f"Ollama request failed: {error.reason}") from error
        except OSError as error:
            raise ModelTransportError(f"Ollama request failed: {error}") from error

        if len(raw) > self._max_response_bytes:
            raise ModelResponseError("Ollama response exceeded configured byte limit")
        try:
            decoded = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ModelResponseError("Ollama returned invalid JSON") from error
        if not isinstance(decoded, dict):
            raise ModelResponseError("Ollama JSON response must be an object")
        return cast(JsonObject, decoded)


def _transport(settings: Settings, provided: OllamaJsonTransport | None) -> OllamaJsonTransport:
    return provided if provided is not None else UrllibOllamaTransport(settings)


def _validate_messages(messages: list[dict[str, str]]) -> None:
    if not messages:
        raise ModelContractError("structured chat requires at least one message")
    for message in messages:
        if set(message) != {"role", "content"}:
            raise ModelContractError("chat messages require exactly role and content")
        if message["role"] not in {"system", "user", "assistant"}:
            raise ModelContractError("chat message role is unsupported")
        if not message["content"].strip():
            raise ModelContractError("chat message content cannot be blank")


@dataclass(frozen=True)
class _OllamaModelBinding:
    model: str
    digest: str


def _required_model(value: str | None, setting_name: str) -> str:
    if value is None or not value.strip():
        raise ModelUnavailableError(f"{setting_name} is required for the Ollama provider")
    return value


def _binding_from_fingerprint(
    fingerprint: ModelFingerprint,
    *,
    configured_model: str,
    required_capability: str,
) -> _OllamaModelBinding:
    if fingerprint.provider != "ollama":
        raise ModelIdentityDriftError("Ollama adapter requires an Ollama model fingerprint")
    if fingerprint.model != configured_model:
        raise ModelIdentityDriftError(
            f"Ollama fingerprint does not match configured model: {configured_model}"
        )
    if fingerprint.digest is None or not fingerprint.digest.strip():
        raise ModelIdentityDriftError(
            f"Ollama fingerprint has no immutable digest: {configured_model}"
        )
    if fingerprint.identity_assurance is not ModelIdentityAssurance.IMMUTABLE_PROVIDER_REVISION:
        raise ModelIdentityDriftError("Ollama adapter requires immutable digest assurance")
    if required_capability not in fingerprint.capabilities:
        raise ModelIdentityDriftError(
            f"Ollama fingerprint lacks {required_capability} capability: {configured_model}"
        )
    return _OllamaModelBinding(model=configured_model, digest=fingerprint.digest)


def _tag_digest(tags: JsonObject, model: str) -> str | None:
    models = tags.get("models")
    if not isinstance(models, list):
        raise ModelResponseError("Ollama tags response is invalid")
    tag = next(
        (item for item in models if isinstance(item, Mapping) and item.get("name") == model),
        None,
    )
    if tag is None:
        return None
    digest = tag.get("digest")
    if not isinstance(digest, str) or not digest.strip():
        raise ModelResponseError(f"Ollama model digest is missing: {model}")
    return digest


def _assert_model_identity(tags: JsonObject, binding: _OllamaModelBinding) -> None:
    current_digest = _tag_digest(tags, binding.model)
    if current_digest != binding.digest:
        raise ModelIdentityDriftError(f"configured Ollama model identity drifted: {binding.model}")


async def _guard_model_identity(
    transport: OllamaJsonTransport,
    binding: _OllamaModelBinding,
) -> None:
    tags = await transport.request("GET", "/api/tags")
    _assert_model_identity(tags, binding)


class OllamaChatModel:
    def __init__(
        self,
        settings: Settings,
        *,
        fingerprint: ModelFingerprint,
        transport: OllamaJsonTransport | None = None,
    ) -> None:
        self._binding = _binding_from_fingerprint(
            fingerprint,
            configured_model=_required_model(settings.ollama_chat_model, "OLLAMA_CHAT_MODEL"),
            required_capability="completion",
        )
        self._transport = _transport(settings, transport)
        self._max_output_tokens = settings.ollama_max_output_tokens

    async def structured(
        self,
        *,
        messages: list[dict[str, str]],
        response_type: type[StructuredResultT],
        purpose: str,
    ) -> StructuredResultT:
        _validate_messages(messages)
        if not purpose.strip():
            raise ModelContractError("structured chat purpose cannot be blank")
        if not issubclass(response_type, BaseModel):
            raise TypeError("response_type must be a Pydantic model")

        await _guard_model_identity(self._transport, self._binding)
        response = await self._transport.request(
            "POST",
            "/api/chat",
            {
                "model": self._binding.model,
                "messages": messages,
                "stream": False,
                "think": False,
                "format": response_type.model_json_schema(),
                "options": {
                    "temperature": 0,
                    "num_predict": self._max_output_tokens,
                },
            },
        )
        if response.get("done") is not True:
            raise ModelResponseError("Ollama chat response is not complete")
        message = response.get("message")
        if not isinstance(message, Mapping):
            raise ModelResponseError("Ollama chat response has no message object")
        content = message.get("content")
        if not isinstance(content, str):
            raise ModelResponseError("Ollama chat response content is not text")
        try:
            return response_type.model_validate_json(content)
        except ValidationError as error:
            raise ModelContractError(
                f"Ollama output failed {response_type.__name__} for {purpose}"
            ) from error


class OllamaEmbeddingModel:
    def __init__(
        self,
        settings: Settings,
        *,
        fingerprint: ModelFingerprint,
        transport: OllamaJsonTransport | None = None,
    ) -> None:
        self._binding = _binding_from_fingerprint(
            fingerprint,
            configured_model=_required_model(settings.ollama_embed_model, "OLLAMA_EMBED_MODEL"),
            required_capability="embedding",
        )
        self._max_batch = settings.ollama_max_embedding_batch
        self._transport = _transport(settings, transport)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            raise ModelContractError("embedding batch cannot be empty")
        if len(texts) > self._max_batch:
            raise ModelContractError("embedding batch exceeds configured limit")
        if any(not text.strip() for text in texts):
            raise ModelContractError("embedding input cannot be blank")

        await _guard_model_identity(self._transport, self._binding)
        response = await self._transport.request(
            "POST",
            "/api/embed",
            {"model": self._binding.model, "input": texts, "truncate": False},
        )
        embeddings = response.get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise ModelResponseError("Ollama returned the wrong number of embeddings")

        normalized: list[list[float]] = []
        expected_dimensions: int | None = None
        for vector in embeddings:
            if not isinstance(vector, list) or not vector:
                raise ModelResponseError("Ollama returned an empty or invalid embedding")
            normalized_vector: list[float] = []
            for value in vector:
                if isinstance(value, bool) or not isinstance(value, int | float):
                    raise ModelResponseError("Ollama embedding contains a non-numeric value")
                numeric = float(value)
                if not math.isfinite(numeric):
                    raise ModelResponseError("Ollama embedding contains a non-finite value")
                normalized_vector.append(numeric)
            if expected_dimensions is None:
                expected_dimensions = len(normalized_vector)
            elif len(normalized_vector) != expected_dimensions:
                raise ModelResponseError("Ollama embedding dimensions are inconsistent")
            normalized.append(normalized_vector)
        return normalized


class OllamaStartupDiagnostics:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: OllamaJsonTransport | None = None,
    ) -> None:
        self._chat_model = _required_model(settings.ollama_chat_model, "OLLAMA_CHAT_MODEL")
        self._embedding_model = _required_model(settings.ollama_embed_model, "OLLAMA_EMBED_MODEL")
        self._transport = _transport(settings, transport)

    async def diagnose(self) -> ModelRuntimeDiagnostics:
        version_response = await self._transport.request("GET", "/api/version")
        version = version_response.get("version")
        if not isinstance(version, str) or not version.strip():
            raise ModelResponseError("Ollama version response is invalid")
        tags = await self._transport.request("GET", "/api/tags")
        chat = await self._fingerprint(tags, self._chat_model, "completion")
        embedding = await self._fingerprint(tags, self._embedding_model, "embedding")
        current_tags = await self._transport.request("GET", "/api/tags")
        _assert_model_identity(
            current_tags,
            _binding_from_fingerprint(
                chat,
                configured_model=self._chat_model,
                required_capability="completion",
            ),
        )
        _assert_model_identity(
            current_tags,
            _binding_from_fingerprint(
                embedding,
                configured_model=self._embedding_model,
                required_capability="embedding",
            ),
        )
        return ModelRuntimeDiagnostics(
            provider="ollama",
            runtime_version=version,
            chat=chat,
            embedding=embedding,
        )

    async def _fingerprint(
        self,
        tags: JsonObject,
        model: str,
        required_capability: str,
    ) -> ModelFingerprint:
        digest = _tag_digest(tags, model)
        if digest is None:
            raise ModelUnavailableError(f"configured Ollama model is missing: {model}")

        shown = await self._transport.request("POST", "/api/show", {"model": model})
        raw_capabilities = shown.get("capabilities")
        if not isinstance(raw_capabilities, list) or not all(
            isinstance(value, str) for value in raw_capabilities
        ):
            raise ModelResponseError(f"Ollama model capabilities are invalid: {model}")
        capabilities = tuple(sorted(cast(list[str], raw_capabilities)))
        if required_capability not in capabilities:
            raise ModelUnavailableError(
                f"Ollama model {model} lacks {required_capability} capability"
            )
        details = shown.get("details")
        if not isinstance(details, Mapping):
            raise ModelResponseError(f"Ollama model details are invalid: {model}")
        metadata = tuple(
            sorted(
                (key, str(details[key]))
                for key in ("family", "parameter_size", "quantization_level")
                if details.get(key) is not None
            )
        )
        return ModelFingerprint(
            provider="ollama",
            model=model,
            digest=digest,
            capabilities=capabilities,
            metadata=metadata,
        )
