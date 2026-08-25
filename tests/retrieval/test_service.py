import asyncio

import pytest

from data_agent.retrieval.errors import RetrievalIndexStaleError
from data_agent.retrieval.index import build_retrieval_index
from data_agent.retrieval.service import HybridRetriever
from tests.retrieval.factories import (
    GENERATED_FINGERPRINT,
    SEMANTIC_REVISION,
    TableAwareEmbeddingModel,
    catalog,
    embedding_fingerprint,
)


def _retriever(*, relationships: bool = True, hops: int = 2, total: int = 4) -> HybridRetriever:
    assembled = catalog(include_relationships=relationships)
    model = TableAwareEmbeddingModel()
    index = asyncio.run(
        build_retrieval_index(
            assembled,
            current_generated_schema_fingerprint=GENERATED_FINGERPRINT,
            current_semantic_revision=SEMANTIC_REVISION,
            embedding_model=model,
            embedding_fingerprint=embedding_fingerprint(),
            model_runtime_version="test-runtime",
            embedding_batch_size=4,
        )
    )
    return HybridRetriever(
        index=index,
        catalog=assembled,
        embedding_model=model,
        embedding_fingerprint=embedding_fingerprint(),
        model_runtime_version="test-runtime",
        lexical_top_k=4,
        semantic_top_k=4,
        seed_table_limit=1,
        max_relationship_hops=hops,
        max_total_tables=total,
    )


def test_hybrid_retrieval_preserves_seed_ranks_and_graph_provenance() -> None:
    trace = asyncio.run(_retriever().retrieve("order paid amount"))

    assert trace.result.hits[0].table == "fact_order"
    assert trace.result.hits[0].source == "SEED"
    assert trace.result.hits[0].lexical_rank == 1
    assert trace.result.hits[0].semantic_rank == 1
    graph_hits = [hit for hit in trace.result.hits if hit.source == "GRAPH_EXPANSION"]
    assert graph_hits
    assert all(hit.lexical_rank is None and hit.semantic_rank is None for hit in graph_hits)
    assert all(hit.fused_score == 0 for hit in graph_hits)
    assert all("seed=fact_order" in str(hit.reason) for hit in graph_hits)
    assert trace.result.index_fingerprint


def test_relationship_expansion_is_deterministic_and_bounded() -> None:
    retriever = _retriever(hops=1, total=3)

    first = asyncio.run(retriever.retrieve("order"))
    second = asyncio.run(retriever.retrieve("order"))

    assert first == second
    assert len(first.result.hits) == 3
    assert all(expansion.hop == 1 for expansion in first.graph_expansions)
    assert "dim_region" not in {str(hit.table) for hit in first.result.hits}


def test_graph_expansion_uses_only_m6_relationships() -> None:
    trace = asyncio.run(_retriever(relationships=False).retrieve("order"))

    assert [str(hit.table) for hit in trace.result.hits] == ["fact_order"]
    assert trace.result.relationships == []
    assert trace.graph_expansions == ()


def test_query_embedding_identity_must_match_index_identity() -> None:
    assembled = catalog()
    model = TableAwareEmbeddingModel()
    index = asyncio.run(
        build_retrieval_index(
            assembled,
            current_generated_schema_fingerprint=GENERATED_FINGERPRINT,
            current_semantic_revision=SEMANTIC_REVISION,
            embedding_model=model,
            embedding_fingerprint=embedding_fingerprint(),
            model_runtime_version="test-runtime",
            embedding_batch_size=4,
        )
    )

    with pytest.raises(RetrievalIndexStaleError, match="query embedding identity"):
        HybridRetriever(
            index=index,
            catalog=assembled,
            embedding_model=model,
            embedding_fingerprint=embedding_fingerprint(digest="drifted"),
            model_runtime_version="test-runtime",
        )
