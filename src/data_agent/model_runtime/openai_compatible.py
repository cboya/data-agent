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
OPENAI_MODELS_BY_ID_PROFILE = "openai_models_by_id"
CLOUDFLARE_WORKERS_AI_PROFILE = "cloudflare_workers_ai"
_CLOUDFLARE_EXECUTION_BASE = re.compile(
    r"https://api\.cloudflare\.com/client/v4/accounts/[0-9a-f]{32}/ai/v1"
)


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

    def __init__(self, settings: Settings, *, base_url_override: str | None = None) -> None:
        self._base_url = base_url_override or _required_text(
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


def _cloudflare_catalog_base_url(execution_base_url: str) -> str:
    if _CLOUDFLARE_EXECUTION_BASE.fullmatch(execution_base_url) is None:
        raise ModelUnavailableError(
            "Cloudflare Workers AI identity profile requires its canonical account ai/v1 base URL"
        )
    return execution_base_url.removesuffix("/v1")


def _identity_transport(
    settings: Settings,
    provided: OpenAICompatibleJsonTransport | None,
) -> OpenAICompatibleJsonTransport:
    if provided is not None:
        return provided
    if settings.openai_compatible_identity_profile == CLOUDFLARE_WORKERS_AI_PROFILE:
        execution_base_url = _required_text(
            settings.openai_compatible_base_url,
            "OPENAI_COMPATIBLE_BASE_URL",
        )
        return UrllibOpenAICompatibleTransport(
            settings,
            base_url_override=_cloudflare_catalog_base_url(execution_base_url),
        )
    return UrllibOpenAICompatibleTransport(settings)


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


def _cloudflare_descriptor(
    response: JsonObject,
    configured_model: str,
    *,
    required_capability: str,
) -> _RemoteModelDescriptor:
    if response.get("success") is not True:
        raise ModelResponseError("Cloudflare Workers AI model catalog request was unsuccessful")
    result = response.get("result")
    if not isinstance(result, list):
        raise ModelResponseError("Cloudflare Workers AI model catalog result is invalid")
    exact_matches = [
        item
        for item in result
        if isinstance(item, Mapping) and item.get("name") == configured_model
    ]
    if len(exact_matches) != 1:
        raise ModelIdentityDriftError(
            "Cloudflare Workers AI model catalog must contain exactly one exact configured "
            f"model match: {configured_model}"
        )
    match = exact_matches[0]
    task = match.get("task")
    if not isinstance(task, Mapping):
        raise ModelResponseError("Cloudflare Workers AI model task metadata is invalid")
    expected_task = {
        "completion": "Text Generation",
        "embedding": "Text Embeddings",
    }.get(required_capability)
    if expected_task is None:
        raise ModelContractError(
            f"unsupported OpenAI-compatible model capability: {required_capability}"
        )
    task_name = task.get("name")
    if task_name != expected_task:
        raise ModelIdentityDriftError(
            f"Cloudflare Workers AI model does not provide {expected_task}: {configured_model}"
        )
    task_id = task.get("id")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ModelResponseError("Cloudflare Workers AI model task id is invalid")
    created_at = match.get("created_at")
    if not isinstance(created_at, str) or not created_at.strip():
        raise ModelResponseError("Cloudflare Workers AI model created_at is invalid")
    source = match.get("source")
    if isinstance(source, bool) or not isinstance(source, int) or source < 0:
        raise ModelResponseError("Cloudflare Workers AI model source is invalid")
    return _RemoteModelDescriptor(
        model=configured_model,
        provider_revision=None,
        runtime_version=RUNTIME_VERSION_NOT_EXPOSED,
        metadata=tuple(
            sorted(
                (
                    ("catalog_created_at", created_at),
                    ("catalog_source", str(source)),
                    ("catalog_task", task_name),
                    ("catalog_task_id", task_id),
                )
            )
        ),
    )


def _fingerprint(
    descriptor: _RemoteModelDescriptor,
    *,
    endpoint_identity: str,
    required_capability: str,
    identity_profile: str,
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
        metadata=tuple(sorted((*descriptor.metadata, ("identity_profile", identity_profile)))),
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
    identity_profile: str,
) -> tuple[ModelFingerprint, str]:
    if identity_profile == OPENAI_MODELS_BY_ID_PROFILE:
        response = await transport.request("GET", f"/models/{quote(model, safe='')}")
        descriptor = _descriptor(response, model)
    elif identity_profile == CLOUDFLARE_WORKERS_AI_PROFILE:
        response = await transport.request(
            "GET",
            f"/models/search?search={quote(model, safe='')}",
        )
        descriptor = _cloudflare_descriptor(
            response,
            model,
            required_capability=required_capability,
        )
    else:
        raise ModelUnavailableError(
            f"unsupported OpenAI-compatible identity profile: {identity_profile}"
        )
    return (
        _fingerprint(
            descriptor,
            endpoint_identity=endpoint_identity,
            required_capability=required_capability,
            identity_profile=identity_profile,
        ),
        descriptor.runtime_version,
    )


@dataclass(frozen=True)
class _RemoteModelBinding:
    model: str
    fingerprint: ModelFingerprint
    endpoint_identity: str
    required_capability: str
    identity_profile: str


def _binding_from_fingerprint(
    fingerprint: ModelFingerprint,
    *,
    configured_model: str,
    endpoint_identity: str,
    required_capability: str,
    identity_profile: str,
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
    if dict(fingerprint.metadata).get("identity_profile") != identity_profile:
        raise ModelIdentityDriftError("OpenAI-compatible identity profile changed")
    return _RemoteModelBinding(
        model=configured_model,
        fingerprint=fingerprint,
        endpoint_identity=endpoint_identity,
        required_capability=required_capability,
        identity_profile=identity_profile,
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
        identity_profile=binding.identity_profile,
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
            identity_profile=settings.openai_compatible_identity_profile,
        )
        self._transport = _transport(settings, transport)
        self._identity_transport = _identity_transport(settings, transport)
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

        await _guard_model_identity(self._identity_transport, self._binding)
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
            identity_profile=settings.openai_compatible_identity_profile,
        )
        self._transport = _transport(settings, transport)
        self._identity_transport = _identity_transport(settings, transport)
        self._max_batch = settings.openai_compatible_max_embedding_batch

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            raise ModelContractError("embedding batch cannot be empty")
        if len(texts) > self._max_batch:
            raise ModelContractError("embedding batch exceeds configured limit")
        if any(not text.strip() for text in texts):
            raise ModelContractError("embedding input cannot be blank")

        await _guard_model_identity(self._identity_transport, self._binding)
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
        self._identity_profile = settings.openai_compatible_identity_profile
        self._transport = _identity_transport(settings, transport)

    async def diagnose(self) -> ModelRuntimeDiagnostics:
        endpoint_identity = _endpoint_identity(self._base_url)
        chat, chat_runtime = await _load_fingerprint(
            self._transport,
            model=self._chat_model,
            endpoint_identity=endpoint_identity,
            required_capability="completion",
            identity_profile=self._identity_profile,
        )
        embedding, embedding_runtime = await _load_fingerprint(
            self._transport,
            model=self._embedding_model,
            endpoint_identity=endpoint_identity,
            required_capability="embedding",
            identity_profile=self._identity_profile,
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
            identity_profile=self._identity_profile,
        )
        current_embedding, current_embedding_runtime = await _load_fingerprint(
            self._transport,
            model=self._embedding_model,
            endpoint_identity=endpoint_identity,
            required_capability="embedding",
            identity_profile=self._identity_profile,
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
