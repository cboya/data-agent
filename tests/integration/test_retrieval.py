import asyncio

import pytest

from data_agent.catalog.introspection import introspect_analytics_schema
from data_agent.catalog.semantic import assemble_semantic_catalog, load_curated_semantics
from data_agent.config import Settings
from data_agent.retrieval.index import build_retrieval_index
from data_agent.retrieval.service import HybridRetriever
from tests.retrieval.factories import DeterministicEmbeddingModel, embedding_fingerprint


@pytest.mark.integration
def test_m6_catalog_builds_searchable_m7_index_without_raw_fk_expansion(
    settings: Settings,
) -> None:
    generated = introspect_analytics_schema(settings)
    curated = load_curated_semantics()
    catalog = assemble_semantic_catalog(generated, curated)
    embedding_model = DeterministicEmbeddingModel()
    index = asyncio.run(
        build_retrieval_index(
            catalog,
            current_generated_schema_fingerprint=generated.fingerprint,
            current_semantic_revision=curated.semantic_revision,
            embedding_model=embedding_model,
            embedding_fingerprint=embedding_fingerprint(),
            model_runtime_version="integration-test-runtime",
            embedding_batch_size=4,
        )
    )
    retriever = HybridRetriever(
        index=index,
        catalog=catalog,
        embedding_model=embedding_model,
        embedding_fingerprint=embedding_fingerprint(),
        model_runtime_version="integration-test-runtime",
        seed_table_limit=3,
        max_relationship_hops=2,
        max_total_tables=10,
    )

    trace = asyncio.run(retriever.retrieve("fact_order paid_amount 实际支付金额"))

    assert len(index.entries) == 10
    assert trace.result.hits[0].table == "fact_order"
    assert all(relationship.curated for relationship in trace.result.relationships)
    assert all(
        hit.lexical_rank is None and hit.semantic_rank is None
        for hit in trace.result.hits
        if hit.source == "GRAPH_EXPANSION"
    )
