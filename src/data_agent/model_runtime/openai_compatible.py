"""Narrow OpenAI-compatible REST adapters for structured chat and embeddings."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from pydantic import BaseModel, ValidationError

from data_agent.config import Settings
from data_agent.model_runtime.errors import (
    ModelContractError,
    ModelIdentityDriftError,
    ModelProviderError,
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
OPENAI_COMPATIBLE_PROVIDER = "openai_compatible"
RUNTIME_VERSION_NOT_EXPOSED = "not-exposed"


class OpenAICompatibleJsonTransport(Protocol):
    async def request(
        self,
        method: str,
        path: str,
        payload: JsonObject | None = None,
    ) -> JsonObject: ...


def _required_text(value: str | None, setting_name: str) -> str:
    if value is None or not value.strip():
        raise ModelUnavailableError(
            f"{setting_name} is required for the OpenAI-compatible provider"
        )
    return value


class UrllibOpenAICompatibleTransport:
    """Credential-safe, bounded, no-retry JSON transport."""

    def __init__(self, settings: Settings) -> None:
        self._base_url = _required_text(
            settings.openai_compatible_base_url,
            "OPENAI_COMPATIBLE_BASE_URL",
        )
        api_key = settings.openai_compatible_api_key
        if api_key is None or not api_key.get_secret_value().strip():
            raise ModelUnavailableError(
                "OPENAI_COMPATIBLE_API_KEY is required for the OpenAI-compatible provider"
            )
        self._api_key = api_key.get_secret_value()
        self._timeout = settings.openai_compatible_request_timeout_seconds
        self._max_response_bytes = settings.openai_compatible_max_response_bytes

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
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:
                raw = response.read(self._max_response_bytes + 1)
        except HTTPError as error:
            raise ModelProviderError(
                f"OpenAI-compatible provider returned HTTP {error.code}"
            ) from error
        except TimeoutError as error:
            raise ModelTimeoutError(
                "OpenAI-compatible request exceeded configured timeout"
            ) from error
        except URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise ModelTimeoutError(
                    "OpenAI-compatible request exceeded configured timeout"
                ) from error
            raise ModelTransportError("OpenAI-compatible request failed") from error
        except OSError as error:
            raise ModelTransportError("OpenAI-compatible request failed") from error

        if len(raw) > self._max_response_bytes:
            raise ModelResponseError("OpenAI-compatible response exceeded configured byte limit")
        try:
            decoded = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ModelResponseError("OpenAI-compatible provider returned invalid JSON") from error
        if not isinstance(decoded, dict):
            raise ModelResponseError("OpenAI-compatible JSON response must be an object")
        return cast(JsonObject, decoded)


def _transport(
    settings: Settings,
    provided: OpenAICompatibleJsonTransport | None,
) -> OpenAICompatibleJsonTransport:
    return provided if provided is not None else UrllibOpenAICompatibleTransport(settings)


def _endpoint_identity(base_url: str) -> str:
    return hashlib.sha256(base_url.encode("utf-8")).hexdigest()


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
class _RemoteModelDescriptor:
    model: str
    provider_revision: str | None
    runtime_version: str
    metadata: tuple[tuple[str, str], ...]


def _optional_nonblank_text(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ModelResponseError(f"OpenAI-compatible model {field} is invalid")
    return value


def _descriptor(response: JsonObject, configured_model: str) -> _RemoteModelDescriptor:
    model = response.get("id")
    if not isinstance(model, str) or model != configured_model:
        raise ModelIdentityDriftError(
            f"OpenAI-compatible model descriptor does not match configured model: "
            f"{configured_model}"
        )
    revision = _optional_nonblank_text(response.get("revision"), field="revision")
    snapshot = _optional_nonblank_text(response.get("snapshot"), field="snapshot")
    if revision is not None and snapshot is not None and revision != snapshot:
        raise ModelResponseError("OpenAI-compatible model revision metadata conflicts")
    provider_revision = revision or snapshot
    runtime_version = (
        _optional_nonblank_text(response.get("provider_version"), field="provider_version")
        or RUNTIME_VERSION_NOT_EXPOSED
    )
    metadata: list[tuple[str, str]] = []
    for field in ("object", "owned_by"):
        value = response.get(field)
        if value is not None:
            if not isinstance(value, str) or not value.strip():
                raise ModelResponseError(f"OpenAI-compatible model {field} is invalid")
            metadata.append((field, value))
    created = response.get("created")
    if created is not None:
        if isinstance(created, bool) or not isinstance(created, int) or created < 0:
            raise ModelResponseError("OpenAI-compatible model created value is invalid")
        metadata.append(("created", str(created)))
    return _RemoteModelDescriptor(
        model=model,
        provider_revision=provider_revision,
        runtime_version=runtime_version,
        metadata=tuple(sorted(metadata)),
    )


def _fingerprint(
    descriptor: _RemoteModelDescriptor,
    *,
    endpoint_identity: str,
    required_capability: str,
) -> ModelFingerprint:
    assurance = (
        ModelIdentityAssurance.IMMUTABLE_PROVIDER_REVISION
        if descriptor.provider_revision is not None
        else ModelIdentityAssurance.ALIAS_ONLY
    )
    return ModelFingerprint(
        provider=OPENAI_COMPATIBLE_PROVIDER,
        model=descriptor.model,
        digest=None,
        capabilities=(required_capability,),
        metadata=descriptor.metadata,
        endpoint_identity=endpoint_identity,
        provider_revision=descriptor.provider_revision,
        identity_assurance=assurance,
    )


async def _load_fingerprint(
    transport: OpenAICompatibleJsonTransport,
    *,
    model: str,
    endpoint_identity: str,
    required_capability: str,
) -> tuple[ModelFingerprint, str]:
    response = await transport.request("GET", f"/models/{quote(model, safe='')}")
    descriptor = _descriptor(response, model)
    return (
        _fingerprint(
            descriptor,
            endpoint_identity=endpoint_identity,
            required_capability=required_capability,
        ),
        descriptor.runtime_version,
    )


@dataclass(frozen=True)
class _RemoteModelBinding:
    model: str
    fingerprint: ModelFingerprint
    endpoint_identity: str
    required_capability: str


def _binding_from_fingerprint(
    fingerprint: ModelFingerprint,
    *,
    configured_model: str,
    endpoint_identity: str,
    required_capability: str,
) -> _RemoteModelBinding:
    if fingerprint.provider != OPENAI_COMPATIBLE_PROVIDER:
        raise ModelIdentityDriftError(
            "OpenAI-compatible adapter requires an OpenAI-compatible fingerprint"
        )
    if fingerprint.model != configured_model:
        raise ModelIdentityDriftError(
            f"OpenAI-compatible fingerprint does not match configured model: {configured_model}"
        )
    if fingerprint.endpoint_identity != endpoint_identity:
        raise ModelIdentityDriftError("OpenAI-compatible endpoint identity changed")
    if required_capability not in fingerprint.capabilities:
        raise ModelIdentityDriftError(
            f"OpenAI-compatible fingerprint lacks {required_capability} capability: "
            f"{configured_model}"
        )
    if fingerprint.digest is not None:
        raise ModelIdentityDriftError(
            "OpenAI-compatible fingerprint must not fabricate a weights digest"
        )
    return _RemoteModelBinding(
        model=configured_model,
        fingerprint=fingerprint,
        endpoint_identity=endpoint_identity,
        required_capability=required_capability,
    )


async def _guard_model_identity(
    transport: OpenAICompatibleJsonTransport,
    binding: _RemoteModelBinding,
) -> None:
    current, _ = await _load_fingerprint(
        transport,
        model=binding.model,
        endpoint_identity=binding.endpoint_identity,
        required_capability=binding.required_capability,
    )
    if current.value != binding.fingerprint.value:
        raise ModelIdentityDriftError(
            f"configured OpenAI-compatible model identity drifted: {binding.model}"
        )


def _schema_name(response_type: type[BaseModel]) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_-]", "_", response_type.__name__)
    return (normalized or "structured_response")[:64]


def _assert_response_model(response: JsonObject, configured_model: str) -> None:
    response_model = response.get("model")
    if not isinstance(response_model, str) or response_model != configured_model:
        raise ModelIdentityDriftError(
            f"OpenAI-compatible response model does not match configured model: {configured_model}"
        )


class OpenAICompatibleChatModel:
    def __init__(
        self,
        settings: Settings,
        *,
        fingerprint: ModelFingerprint,
        transport: OpenAICompatibleJsonTransport | None = None,
    ) -> None:
        base_url = _required_text(
            settings.openai_compatible_base_url,
            "OPENAI_COMPATIBLE_BASE_URL",
        )
        self._binding = _binding_from_fingerprint(
            fingerprint,
            configured_model=_required_text(
                settings.openai_compatible_chat_model,
                "OPENAI_COMPATIBLE_CHAT_MODEL",
            ),
            endpoint_identity=_endpoint_identity(base_url),
            required_capability="completion",
        )
        self._transport = _transport(settings, transport)
        self._max_output_tokens = settings.openai_compatible_max_output_tokens

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
            "/chat/completions",
            {
                "model": self._binding.model,
                "messages": messages,
                "temperature": 0,
                "max_completion_tokens": self._max_output_tokens,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": _schema_name(response_type),
                        "strict": True,
                        "schema": response_type.model_json_schema(),
                    },
                },
            },
        )
        _assert_response_model(response, self._binding.model)
        choices = response.get("choices")
        if not isinstance(choices, list) or len(choices) != 1:
            raise ModelResponseError(
                "OpenAI-compatible chat response must contain exactly one choice"
            )
        choice = choices[0]
        if not isinstance(choice, Mapping):
            raise ModelResponseError("OpenAI-compatible chat choice is invalid")
        if choice.get("finish_reason") != "stop":
            raise ModelResponseError("OpenAI-compatible structured chat did not finish cleanly")
        message = choice.get("message")
        if not isinstance(message, Mapping):
            raise ModelResponseError("OpenAI-compatible chat response has no message object")
        refusal = message.get("refusal")
        if refusal is not None and (not isinstance(refusal, str) or refusal.strip()):
            raise ModelProviderError("OpenAI-compatible provider refused structured output")
        content = message.get("content")
        if not isinstance(content, str):
            raise ModelResponseError("OpenAI-compatible chat response content is not text")
        try:
            return response_type.model_validate_json(content)
        except ValidationError as error:
            raise ModelContractError(
                f"OpenAI-compatible output failed {response_type.__name__} for {purpose}"
            ) from error


class OpenAICompatibleEmbeddingModel:
    def __init__(
        self,
        settings: Settings,
        *,
        fingerprint: ModelFingerprint,
        transport: OpenAICompatibleJsonTransport | None = None,
    ) -> None:
        base_url = _required_text(
            settings.openai_compatible_base_url,
            "OPENAI_COMPATIBLE_BASE_URL",
        )
        self._binding = _binding_from_fingerprint(
            fingerprint,
            configured_model=_required_text(
                settings.openai_compatible_embed_model,
                "OPENAI_COMPATIBLE_EMBED_MODEL",
            ),
            endpoint_identity=_endpoint_identity(base_url),
            required_capability="embedding",
        )
        self._transport = _transport(settings, transport)
        self._max_batch = settings.openai_compatible_max_embedding_batch

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
            "/embeddings",
            {
                "model": self._binding.model,
                "input": texts,
                "encoding_format": "float",
            },
        )
        _assert_response_model(response, self._binding.model)
        data = response.get("data")
        if not isinstance(data, list) or len(data) != len(texts):
            raise ModelResponseError(
                "OpenAI-compatible provider returned the wrong number of embeddings"
            )

        indexed: dict[int, list[float]] = {}
        expected_dimensions: int | None = None
        for item in data:
            if not isinstance(item, Mapping):
                raise ModelResponseError("OpenAI-compatible embedding item is invalid")
            index = item.get("index")
            if isinstance(index, bool) or not isinstance(index, int) or index in indexed:
                raise ModelResponseError("OpenAI-compatible embedding index is invalid")
            vector = item.get("embedding")
            if not isinstance(vector, list) or not vector:
                raise ModelResponseError(
                    "OpenAI-compatible provider returned an empty or invalid embedding"
                )
            normalized: list[float] = []
            for value in vector:
                if isinstance(value, bool) or not isinstance(value, int | float):
                    raise ModelResponseError(
                        "OpenAI-compatible embedding contains a non-numeric value"
                    )
                numeric = float(value)
                if not math.isfinite(numeric):
                    raise ModelResponseError(
                        "OpenAI-compatible embedding contains a non-finite value"
                    )
                normalized.append(numeric)
            if expected_dimensions is None:
                expected_dimensions = len(normalized)
            elif len(normalized) != expected_dimensions:
                raise ModelResponseError("OpenAI-compatible embedding dimensions are inconsistent")
            indexed[index] = normalized
        if set(indexed) != set(range(len(texts))):
            raise ModelResponseError("OpenAI-compatible embedding indices are incomplete")
        return [indexed[index] for index in range(len(texts))]


class OpenAICompatibleStartupDiagnostics:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: OpenAICompatibleJsonTransport | None = None,
    ) -> None:
        self._base_url = _required_text(
            settings.openai_compatible_base_url,
            "OPENAI_COMPATIBLE_BASE_URL",
        )
        self._chat_model = _required_text(
            settings.openai_compatible_chat_model,
            "OPENAI_COMPATIBLE_CHAT_MODEL",
        )
        self._embedding_model = _required_text(
            settings.openai_compatible_embed_model,
            "OPENAI_COMPATIBLE_EMBED_MODEL",
        )
        self._transport = _transport(settings, transport)

    async def diagnose(self) -> ModelRuntimeDiagnostics:
        endpoint_identity = _endpoint_identity(self._base_url)
        chat, chat_runtime = await _load_fingerprint(
            self._transport,
            model=self._chat_model,
            endpoint_identity=endpoint_identity,
            required_capability="completion",
        )
        embedding, embedding_runtime = await _load_fingerprint(
            self._transport,
            model=self._embedding_model,
            endpoint_identity=endpoint_identity,
            required_capability="embedding",
        )
        exposed_versions = {
            value
            for value in (chat_runtime, embedding_runtime)
            if value != RUNTIME_VERSION_NOT_EXPOSED
        }
        if len(exposed_versions) > 1:
            raise ModelResponseError("OpenAI-compatible provider runtime versions conflict")
        runtime_version = next(iter(exposed_versions), RUNTIME_VERSION_NOT_EXPOSED)

        current_chat, current_chat_runtime = await _load_fingerprint(
            self._transport,
            model=self._chat_model,
            endpoint_identity=endpoint_identity,
            required_capability="completion",
        )
        current_embedding, current_embedding_runtime = await _load_fingerprint(
            self._transport,
            model=self._embedding_model,
            endpoint_identity=endpoint_identity,
            required_capability="embedding",
        )
        if current_chat.value != chat.value:
            raise ModelIdentityDriftError(
                f"configured OpenAI-compatible model identity drifted: {self._chat_model}"
            )
        if current_embedding.value != embedding.value:
            raise ModelIdentityDriftError(
                f"configured OpenAI-compatible model identity drifted: {self._embedding_model}"
            )
        if current_chat_runtime != chat_runtime or current_embedding_runtime != embedding_runtime:
            raise ModelIdentityDriftError("OpenAI-compatible provider runtime identity drifted")
        return ModelRuntimeDiagnostics(
            provider=OPENAI_COMPATIBLE_PROVIDER,
            runtime_version=runtime_version,
            chat=chat,
            embedding=embedding,
        )
