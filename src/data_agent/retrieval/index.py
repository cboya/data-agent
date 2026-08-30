"""Versioned in-process retrieval index with complete identity and stale protection."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from data_agent.catalog.introspection import GENERATED_CATALOG_ROOT
from data_agent.catalog.semantic import AssembledSemanticCatalog
from data_agent.catalog.workspace import ensure_generated_output_path
from data_agent.model_runtime.ports import (
    EmbeddingModel,
    ModelFingerprint,
    ModelIdentityAssurance,
)
from data_agent.retrieval.document import (
    RETRIEVAL_DOCUMENT_BUILDER_VERSION,
    RetrievalDocument,
    project_catalog_document,
)
from data_agent.retrieval.errors import RetrievalIndexError, RetrievalIndexStaleError

RETRIEVAL_INDEX_FORMAT_VERSION: Literal["retrieval-index-v0.2"] = "retrieval-index-v0.2"
RETRIEVAL_INDEX_ROOT = GENERATED_CATALOG_ROOT / "index"
RETRIEVAL_INDEX_PATH = RETRIEVAL_INDEX_ROOT / "retrieval.json"


def _fingerprint(payload: object) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class _IndexModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class EmbeddingModelIdentity(_IndexModel):
    provider: str = Field(min_length=1, pattern=r"\S")
    model: str = Field(min_length=1, pattern=r"\S")
    digest: str | None
    capabilities: tuple[str, ...] = Field(min_length=1)
    metadata: tuple[tuple[str, str], ...] = ()
    endpoint_identity: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    provider_revision: str | None = Field(default=None, min_length=1, pattern=r"\S")
    identity_assurance: ModelIdentityAssurance = ModelIdentityAssurance.IMMUTABLE_PROVIDER_REVISION
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def from_fingerprint(cls, fingerprint: ModelFingerprint) -> Self:
        return cls(
            provider=fingerprint.provider,
            model=fingerprint.model,
            digest=fingerprint.digest,
            capabilities=fingerprint.capabilities,
            metadata=fingerprint.metadata,
            endpoint_identity=fingerprint.endpoint_identity,
            provider_revision=fingerprint.provider_revision,
            identity_assurance=fingerprint.identity_assurance,
            fingerprint=fingerprint.value,
        )

    @model_validator(mode="after")
    def fingerprint_matches_complete_identity(self) -> Self:
        rebuilt = ModelFingerprint(
            provider=self.provider,
            model=self.model,
            digest=self.digest,
            capabilities=self.capabilities,
            metadata=self.metadata,
            endpoint_identity=self.endpoint_identity,
            provider_revision=self.provider_revision,
            identity_assurance=self.identity_assurance,
        )
        if rebuilt.value != self.fingerprint:
            raise ValueError("embedding model fingerprint does not match complete identity")
        return self


class RetrievalIndexIdentity(_IndexModel):
    catalog_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    generated_schema_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    embedding_model: EmbeddingModelIdentity
    model_runtime_version: str = Field(min_length=1, pattern=r"\S")
    index_format_version: Literal["retrieval-index-v0.2"]
    document_builder_version: Literal["retrieval-document-v0.1"]


class RetrievalIndexEntry(_IndexModel):
    document: RetrievalDocument
    embedding: tuple[float, ...] = Field(min_length=1)


class RetrievalIndex(_IndexModel):
    version: Literal["v0.1"] = "v0.1"
    identity: RetrievalIndexIdentity
    entries: tuple[RetrievalIndexEntry, ...] = Field(min_length=1)
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def build(
        cls,
        *,
        identity: RetrievalIndexIdentity,
        entries: tuple[RetrievalIndexEntry, ...],
    ) -> Self:
        payload = {
            "version": "v0.1",
            "identity": identity.model_dump(mode="json"),
            "entries": [entry.model_dump(mode="json") for entry in entries],
        }
        return cls(
            identity=identity,
            entries=entries,
            fingerprint=_fingerprint(payload),
        )

    @model_validator(mode="after")
    def content_is_canonical_and_untampered(self) -> Self:
        tables = [entry.document.table for entry in self.entries]
        if tables != sorted(tables) or len(tables) != len(set(tables)):
            raise ValueError("retrieval index entries must have unique sorted table names")
        dimensions = {len(entry.embedding) for entry in self.entries}
        if len(dimensions) != 1:
            raise ValueError("retrieval index embeddings must have consistent dimensions")
        for entry in self.entries:
            if entry.document.builder_version != self.identity.document_builder_version:
                raise ValueError("retrieval document builder identity mismatch")
            if any(not math.isfinite(value) for value in entry.embedding):
                raise ValueError("retrieval index embedding contains a non-finite value")
            if math.sqrt(sum(value * value for value in entry.embedding)) == 0:
                raise ValueError("retrieval index embedding cannot be a zero vector")
        payload = self.model_dump(mode="json", exclude={"fingerprint"})
        if self.fingerprint != _fingerprint(payload):
            raise ValueError("retrieval index fingerprint does not match canonical content")
        return self


def assert_catalog_binding(
    catalog: AssembledSemanticCatalog,
    *,
    current_generated_schema_fingerprint: str,
    current_semantic_revision: str,
) -> None:
    if catalog.generated_metadata_fingerprint != current_generated_schema_fingerprint:
        raise RetrievalIndexStaleError(
            "assembled catalog does not match the current generated schema fingerprint"
        )
    if catalog.semantic_revision != current_semantic_revision:
        raise RetrievalIndexStaleError(
            "assembled catalog does not match the current curated semantic revision"
        )


def expected_index_identity(
    catalog: AssembledSemanticCatalog,
    *,
    current_generated_schema_fingerprint: str,
    current_semantic_revision: str,
    embedding_fingerprint: ModelFingerprint,
    model_runtime_version: str,
) -> RetrievalIndexIdentity:
    assert_catalog_binding(
        catalog,
        current_generated_schema_fingerprint=current_generated_schema_fingerprint,
        current_semantic_revision=current_semantic_revision,
    )
    return RetrievalIndexIdentity(
        catalog_fingerprint=catalog.catalog_fingerprint,
        generated_schema_fingerprint=current_generated_schema_fingerprint,
        semantic_revision=current_semantic_revision,
        embedding_model=EmbeddingModelIdentity.from_fingerprint(embedding_fingerprint),
        model_runtime_version=model_runtime_version,
        index_format_version=RETRIEVAL_INDEX_FORMAT_VERSION,
        document_builder_version=RETRIEVAL_DOCUMENT_BUILDER_VERSION,
    )


def _validated_vectors(
    vectors: list[list[float]],
    *,
    expected_count: int,
) -> tuple[tuple[float, ...], ...]:
    if len(vectors) != expected_count:
        raise RetrievalIndexError("embedding model returned the wrong index vector count")
    normalized: list[tuple[float, ...]] = []
    expected_dimensions: int | None = None
    for vector in vectors:
        if not vector:
            raise RetrievalIndexError("embedding model returned an empty index vector")
        if any(isinstance(value, bool) or not isinstance(value, int | float) for value in vector):
            raise RetrievalIndexError("embedding model returned a non-numeric index vector")
        values = tuple(float(value) for value in vector)
        if any(not math.isfinite(value) for value in values):
            raise RetrievalIndexError("embedding model returned a non-finite index vector")
        if math.sqrt(sum(value * value for value in values)) == 0:
            raise RetrievalIndexError("embedding model returned a zero index vector")
        if expected_dimensions is None:
            expected_dimensions = len(values)
        elif len(values) != expected_dimensions:
            raise RetrievalIndexError("embedding model returned inconsistent index dimensions")
        normalized.append(values)
    return tuple(normalized)


async def build_retrieval_index(
    catalog: AssembledSemanticCatalog,
    *,
    current_generated_schema_fingerprint: str,
    current_semantic_revision: str,
    embedding_model: EmbeddingModel,
    embedding_fingerprint: ModelFingerprint,
    model_runtime_version: str,
    embedding_batch_size: int,
) -> RetrievalIndex:
    """Project, embed, and bind a generated index to current catalog/model authority."""
    if embedding_batch_size < 1:
        raise RetrievalIndexError("embedding batch size must be positive")
    identity = expected_index_identity(
        catalog,
        current_generated_schema_fingerprint=current_generated_schema_fingerprint,
        current_semantic_revision=current_semantic_revision,
        embedding_fingerprint=embedding_fingerprint,
        model_runtime_version=model_runtime_version,
    )
    documents = tuple(
        project_catalog_document(document)
        for document in sorted(catalog.documents, key=lambda document: str(document.table))
    )
    vectors: list[list[float]] = []
    for start in range(0, len(documents), embedding_batch_size):
        batch = documents[start : start + embedding_batch_size]
        vectors.extend(await embedding_model.embed([document.text for document in batch]))
    normalized = _validated_vectors(vectors, expected_count=len(documents))
    entries = tuple(
        RetrievalIndexEntry(document=document, embedding=vector)
        for document, vector in zip(documents, normalized, strict=True)
    )
    return RetrievalIndex.build(identity=identity, entries=entries)


def _ensure_index_path(output_path: Path, generated_root: Path) -> None:
    try:
        ensure_generated_output_path(output_path, generated_root)
    except ValueError as error:
        raise RetrievalIndexError(str(error)) from error


def write_retrieval_index(
    index: RetrievalIndex,
    *,
    output_path: Path = RETRIEVAL_INDEX_PATH,
    generated_root: Path = GENERATED_CATALOG_ROOT,
) -> Path:
    _ensure_index_path(output_path, generated_root)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = (
        json.dumps(
            index.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    temporary_path = output_path.with_name(f".{output_path.name}.tmp")
    try:
        temporary_path.write_text(serialized, encoding="utf-8")
        temporary_path.replace(output_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return output_path


def assert_index_documents(
    index: RetrievalIndex,
    catalog: AssembledSemanticCatalog,
) -> None:
    expected = tuple(
        project_catalog_document(document)
        for document in sorted(catalog.documents, key=lambda document: str(document.table))
    )
    actual = tuple(entry.document for entry in index.entries)
    if actual != expected:
        raise RetrievalIndexStaleError(
            "retrieval index documents do not match current catalog projections"
        )


def load_retrieval_index(
    *,
    catalog: AssembledSemanticCatalog,
    current_generated_schema_fingerprint: str,
    current_semantic_revision: str,
    embedding_fingerprint: ModelFingerprint,
    model_runtime_version: str,
    path: Path = RETRIEVAL_INDEX_PATH,
) -> RetrievalIndex:
    """Load an untampered index and reject every mismatch with current authority."""
    expected = expected_index_identity(
        catalog,
        current_generated_schema_fingerprint=current_generated_schema_fingerprint,
        current_semantic_revision=current_semantic_revision,
        embedding_fingerprint=embedding_fingerprint,
        model_runtime_version=model_runtime_version,
    )
    try:
        index = RetrievalIndex.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise RetrievalIndexError(
            "retrieval index is missing, invalid, or fingerprint-drifted"
        ) from error
    if index.identity != expected:
        raise RetrievalIndexStaleError("retrieval index identity does not match current authority")
    assert_index_documents(index, catalog)
    return index
