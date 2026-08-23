"""Hybrid retrieval output contracts."""

from typing import Literal

from pydantic import Field

from data_agent.contracts.base import ContractModel, ContractVersion, NonEmptyString
from data_agent.contracts.catalog import Relationship


class RetrievalHit(ContractModel):
    table: NonEmptyString
    lexical_rank: int | None = Field(default=None, ge=1)
    semantic_rank: int | None = Field(default=None, ge=1)
    fused_score: float
    rerank_score: float | None = None
    reason: NonEmptyString | None = None
    source: Literal["SEED", "GRAPH_EXPANSION"]


class RetrievalResult(ContractModel):
    version: ContractVersion
    query: NonEmptyString
    hits: list[RetrievalHit]
    relationships: list[Relationship]
    index_fingerprint: NonEmptyString
