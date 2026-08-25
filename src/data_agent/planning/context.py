"""Deterministic bounded semantic context construction for M9 planning."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from data_agent.catalog.semantic import AssembledSemanticCatalog
from data_agent.contracts.base import NonEmptyString
from data_agent.contracts.catalog import CatalogDocument, Relationship
from data_agent.contracts.requirement import RequirementState, RequirementStatus
from data_agent.contracts.retrieval import RetrievalResult
from data_agent.planning.errors import PlannerInputError
from data_agent.planning.prompt import PLANNER_SYSTEM_PROMPT


class _PlannerModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class PlannerCatalogIdentity(_PlannerModel):
    catalog_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    generated_schema_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    retrieval_index_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class PlannerContext(_PlannerModel):
    version: Literal["v0.1"] = "v0.1"
    requirement: RequirementState
    allowed_tables: tuple[NonEmptyString, ...] = Field(min_length=1)
    documents: tuple[CatalogDocument, ...] = Field(min_length=1)
    relationships: tuple[Relationship, ...]
    identity: PlannerCatalogIdentity

    @model_validator(mode="after")
    def context_is_one_ready_exact_slice(self) -> Self:
        if self.requirement.status is not RequirementStatus.READY:
            raise ValueError("planner context requires READY RequirementState")
        document_tables = tuple(str(document.table) for document in self.documents)
        allowed_tables = tuple(str(table) for table in self.allowed_tables)
        if document_tables != allowed_tables:
            raise ValueError("planner documents must exactly follow allowed tables")
        if len(allowed_tables) != len(set(allowed_tables)):
            raise ValueError("planner allowed tables must be unique")
        allowed = set(allowed_tables)
        for relationship in self.relationships:
            if (
                str(relationship.from_table) not in allowed
                or str(relationship.to_table) not in allowed
            ):
                raise ValueError("planner relationship endpoint is outside allowed tables")
        return self


def _relationship_key(relationship: Relationship) -> tuple[str, str, str, str]:
    return (
        str(relationship.from_table),
        str(relationship.from_column),
        str(relationship.to_table),
        str(relationship.to_column),
    )


class PlannerContextBuilder:
    """Project an exact M7 schema slice; fail instead of truncating or widening it."""

    def __init__(
        self,
        *,
        max_tables: int = 8,
        max_context_characters: int = 64_000,
    ) -> None:
        if max_tables < 1 or max_context_characters < 1:
            raise ValueError("planner context bounds must be positive")
        self._max_tables = max_tables
        self._max_context_characters = max_context_characters

    def build(
        self,
        *,
        requirement: RequirementState,
        retrieval: RetrievalResult,
        catalog: AssembledSemanticCatalog,
        documents: Sequence[CatalogDocument],
        expected_retrieval_index_fingerprint: str,
    ) -> PlannerContext:
        if requirement.status is not RequirementStatus.READY:
            raise PlannerInputError("query planning requires READY RequirementState")
        allowed_tables = tuple(str(hit.table) for hit in retrieval.hits)
        if not allowed_tables:
            raise PlannerInputError("planner retrieval result must contain at least one hit")
        if len(allowed_tables) != len(set(allowed_tables)):
            raise PlannerInputError("planner retrieval hit tables must be unique")
        if len(allowed_tables) > self._max_tables:
            raise PlannerInputError("planner retrieval result exceeds the table bound")
        if retrieval.index_fingerprint != expected_retrieval_index_fingerprint:
            raise PlannerInputError("planner retrieval index identity is stale or inconsistent")

        authority_documents = {str(document.table): document for document in catalog.documents}
        provided_documents = {str(document.table): document for document in documents}
        if len(provided_documents) != len(documents):
            raise PlannerInputError("planner catalog documents must have unique tables")
        if set(provided_documents) != set(allowed_tables):
            missing = sorted(set(allowed_tables) - set(provided_documents))
            extra = sorted(set(provided_documents) - set(allowed_tables))
            raise PlannerInputError(
                f"planner catalog slice mismatch: missing={missing}, extra={extra}"
            )
        ordered_documents: list[CatalogDocument] = []
        document_columns: dict[str, set[str]] = {}
        for table in allowed_tables:
            provided = provided_documents[table]
            authoritative = authority_documents.get(table)
            if authoritative is None:
                raise PlannerInputError(f"retrieval hit has no authoritative catalog: {table}")
            if provided != authoritative:
                raise PlannerInputError(
                    f"planner catalog document is not current authority: {table}"
                )
            if (
                provided.generated_metadata_fingerprint != catalog.generated_metadata_fingerprint
                or provided.semantic_revision != catalog.semantic_revision
            ):
                raise PlannerInputError(f"planner catalog document identity mismatch: {table}")
            ordered_documents.append(provided)
            document_columns[table] = {str(column.name) for column in provided.columns}

        authority_relationships = {
            _relationship_key(relationship): relationship for relationship in catalog.relationships
        }
        relationship_keys = [
            _relationship_key(relationship) for relationship in retrieval.relationships
        ]
        if len(relationship_keys) != len(set(relationship_keys)):
            raise PlannerInputError("planner retrieval relationships must be unique")
        allowed = set(allowed_tables)
        ordered_relationships: list[Relationship] = []
        for relationship in sorted(retrieval.relationships, key=_relationship_key):
            key = _relationship_key(relationship)
            if key[0] not in allowed or key[2] not in allowed:
                raise PlannerInputError("planner relationship endpoint is outside retrieval hits")
            if authority_relationships.get(key) != relationship:
                raise PlannerInputError("planner relationship is not current M6 authority")
            if key[1] not in document_columns[key[0]] or key[3] not in document_columns[key[2]]:
                raise PlannerInputError("planner relationship column is outside catalog documents")
            ordered_relationships.append(relationship)

        context = PlannerContext(
            requirement=requirement,
            allowed_tables=allowed_tables,
            documents=tuple(ordered_documents),
            relationships=tuple(ordered_relationships),
            identity=PlannerCatalogIdentity(
                catalog_fingerprint=catalog.catalog_fingerprint,
                generated_schema_fingerprint=catalog.generated_metadata_fingerprint,
                semantic_revision=catalog.semantic_revision,
                retrieval_index_fingerprint=retrieval.index_fingerprint,
            ),
        )
        self._assert_size(context)
        return context

    def messages(self, context: PlannerContext) -> list[dict[str, str]]:
        payload = json.dumps(
            context.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        if len(PLANNER_SYSTEM_PROMPT) + len(payload) > self._max_context_characters:
            raise PlannerInputError("planner context exceeds the configured character bound")
        return [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": payload},
        ]

    def _assert_size(self, context: PlannerContext) -> None:
        self.messages(context)
