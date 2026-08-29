"""Provider-neutral model capabilities owned by the harness."""

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, TypeVar

from pydantic import BaseModel

StructuredResultT = TypeVar("StructuredResultT", bound=BaseModel)


class ModelIdentityAssurance(StrEnum):
    """Strength of the provider identity represented by a model fingerprint."""

    IMMUTABLE_PROVIDER_REVISION = "IMMUTABLE_PROVIDER_REVISION"
    PINNED_DEPLOYMENT = "PINNED_DEPLOYMENT"
    ALIAS_ONLY = "ALIAS_ONLY"


@dataclass(frozen=True)
class ModelFingerprint:
    provider: str
    model: str
    digest: str | None
    capabilities: tuple[str, ...]
    metadata: tuple[tuple[str, str], ...] = ()
    endpoint_identity: str | None = None
    provider_revision: str | None = None
    identity_assurance: ModelIdentityAssurance = ModelIdentityAssurance.IMMUTABLE_PROVIDER_REVISION

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.model.strip():
            raise ValueError("model fingerprint provider and model cannot be blank")
        if self.digest is not None and not self.digest.strip():
            raise ValueError("model fingerprint digest must be non-blank or absent")
        if not self.capabilities or any(not value.strip() for value in self.capabilities):
            raise ValueError("model fingerprint capabilities cannot be empty or blank")
        if self.identity_assurance is ModelIdentityAssurance.ALIAS_ONLY and self.digest is not None:
            raise ValueError("alias-only model identity cannot claim an immutable digest")
        if (
            self.identity_assurance is ModelIdentityAssurance.ALIAS_ONLY
            and self.provider_revision is not None
        ):
            raise ValueError("alias-only model identity cannot claim a provider revision")
        if (
            self.identity_assurance is ModelIdentityAssurance.IMMUTABLE_PROVIDER_REVISION
            and self.digest is None
            and self.provider_revision is None
        ):
            raise ValueError("immutable model identity requires a digest or provider revision")

    @property
    def value(self) -> str:
        payload: dict[str, object] = {
            "provider": self.provider,
            "model": self.model,
            "digest": self.digest,
            "capabilities": self.capabilities,
            "metadata": self.metadata,
        }
        # Preserve the frozen Phase-1 Ollama fingerprint encoding while extending remote
        # identities with the additional facts they actually expose.
        if self.endpoint_identity is not None:
            payload["endpoint_identity"] = self.endpoint_identity
        if self.provider_revision is not None:
            payload["provider_revision"] = self.provider_revision
        if (
            self.endpoint_identity is not None
            or self.identity_assurance is not ModelIdentityAssurance.IMMUTABLE_PROVIDER_REVISION
        ):
            payload["identity_assurance"] = self.identity_assurance.value
        canonical = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ModelRuntimeDiagnostics:
    provider: str
    runtime_version: str
    chat: ModelFingerprint
    embedding: ModelFingerprint


class ChatModel(Protocol):
    async def structured(
        self,
        *,
        messages: list[dict[str, str]],
        response_type: type[StructuredResultT],
        purpose: str,
    ) -> StructuredResultT: ...


class EmbeddingModel(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class ModelRuntimeProbe(Protocol):
    async def diagnose(self) -> ModelRuntimeDiagnostics: ...
