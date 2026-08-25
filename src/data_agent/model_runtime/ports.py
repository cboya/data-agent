"""Provider-neutral model capabilities owned by the harness."""

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel

StructuredResultT = TypeVar("StructuredResultT", bound=BaseModel)


@dataclass(frozen=True)
class ModelFingerprint:
    provider: str
    model: str
    digest: str
    capabilities: tuple[str, ...]
    metadata: tuple[tuple[str, str], ...] = ()

    @property
    def value(self) -> str:
        canonical = json.dumps(
            {
                "provider": self.provider,
                "model": self.model,
                "digest": self.digest,
                "capabilities": self.capabilities,
                "metadata": self.metadata,
            },
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
