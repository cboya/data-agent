"""Deterministic BM25, cosine ranking, and Reciprocal Rank Fusion."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from data_agent.retrieval.document import RetrievalDocument, tokenize
from data_agent.retrieval.errors import RetrievalQueryError
from data_agent.retrieval.index import RetrievalIndex

BM25_K1 = 1.2
BM25_B = 0.75
RRF_K = 60.0


@dataclass(frozen=True)
class RankedTable:
    table: str
    score: float


@dataclass(frozen=True)
class FusedTable:
    table: str
    lexical_rank: int | None
    semantic_rank: int | None
    fused_score: float


def lexical_rank(
    query: str,
    documents: tuple[RetrievalDocument, ...],
    *,
    limit: int,
) -> tuple[RankedTable, ...]:
    """Rank documents with deterministic repository-local BM25."""
    if limit < 1:
        raise RetrievalQueryError("lexical rank limit must be positive")
    query_terms = tuple(dict.fromkeys(tokenize(query)))
    if not query_terms:
        raise RetrievalQueryError("retrieval query produced no searchable lexical terms")
    if not documents:
        raise RetrievalQueryError("lexical retrieval requires at least one document")

    document_frequencies = {
        term: sum(term in document.tokens for document in documents) for term in query_terms
    }
    average_length = sum(len(document.tokens) for document in documents) / len(documents)
    total_documents = len(documents)
    ranked: list[RankedTable] = []
    for document in documents:
        frequencies = Counter(document.tokens)
        length_normalization = 1 - BM25_B + BM25_B * len(document.tokens) / average_length
        score = 0.0
        for term in query_terms:
            frequency = frequencies[term]
            if frequency == 0:
                continue
            document_frequency = document_frequencies[term]
            inverse_document_frequency = math.log(
                1 + (total_documents - document_frequency + 0.5) / (document_frequency + 0.5)
            )
            score += inverse_document_frequency * (
                frequency * (BM25_K1 + 1) / (frequency + BM25_K1 * length_normalization)
            )
        if score > 0:
            ranked.append(RankedTable(table=document.table, score=score))
    ranked.sort(key=lambda item: (-item.score, item.table))
    return tuple(ranked[:limit])


def _validated_query_vector(
    query_vector: list[float],
    *,
    expected_dimensions: int,
) -> tuple[float, ...]:
    if len(query_vector) != expected_dimensions:
        raise RetrievalQueryError("query embedding dimension does not match the retrieval index")
    if any(isinstance(value, bool) or not isinstance(value, int | float) for value in query_vector):
        raise RetrievalQueryError("query embedding contains a non-numeric value")
    values = tuple(float(value) for value in query_vector)
    if any(not math.isfinite(value) for value in values):
        raise RetrievalQueryError("query embedding contains a non-finite value")
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0:
        raise RetrievalQueryError("query embedding cannot be a zero vector")
    return values


def semantic_rank(
    query_vector: list[float],
    index: RetrievalIndex,
    *,
    limit: int,
) -> tuple[RankedTable, ...]:
    """Rank every indexed document by in-process cosine similarity."""
    if limit < 1:
        raise RetrievalQueryError("semantic rank limit must be positive")
    expected_dimensions = len(index.entries[0].embedding)
    query = _validated_query_vector(
        query_vector,
        expected_dimensions=expected_dimensions,
    )
    query_norm = math.sqrt(sum(value * value for value in query))
    ranked: list[RankedTable] = []
    for entry in index.entries:
        document_norm = math.sqrt(sum(value * value for value in entry.embedding))
        similarity = sum(
            query_value * document_value
            for query_value, document_value in zip(query, entry.embedding, strict=True)
        ) / (query_norm * document_norm)
        ranked.append(RankedTable(table=entry.document.table, score=similarity))
    ranked.sort(key=lambda item: (-item.score, item.table))
    return tuple(ranked[:limit])


def reciprocal_rank_fusion(
    lexical: tuple[RankedTable, ...],
    semantic: tuple[RankedTable, ...],
    *,
    rrf_k: float = RRF_K,
) -> tuple[FusedTable, ...]:
    """Fuse independent rank lists without normalizing incomparable score scales."""
    if not math.isfinite(rrf_k) or rrf_k <= 0:
        raise RetrievalQueryError("RRF k must be a finite positive value")
    lexical_ranks = {item.table: rank for rank, item in enumerate(lexical, start=1)}
    semantic_ranks = {item.table: rank for rank, item in enumerate(semantic, start=1)}
    tables = sorted(lexical_ranks.keys() | semantic_ranks.keys())
    fused = [
        FusedTable(
            table=table,
            lexical_rank=lexical_ranks.get(table),
            semantic_rank=semantic_ranks.get(table),
            fused_score=sum(
                1 / (rrf_k + rank)
                for rank in (lexical_ranks.get(table), semantic_ranks.get(table))
                if rank is not None
            ),
        )
        for table in tables
    ]
    fused.sort(key=lambda item: (-item.fused_score, item.table))
    return tuple(fused)
