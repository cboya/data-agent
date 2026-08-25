import asyncio

import pytest

from data_agent.retrieval.document import RetrievalDocument
from data_agent.retrieval.errors import RetrievalQueryError
from data_agent.retrieval.index import build_retrieval_index
from data_agent.retrieval.ranking import (
    RankedTable,
    lexical_rank,
    reciprocal_rank_fusion,
    semantic_rank,
)
from tests.retrieval.factories import (
    GENERATED_FINGERPRINT,
    SEMANTIC_REVISION,
    TableAwareEmbeddingModel,
    catalog,
    embedding_fingerprint,
)


def test_bm25_prefers_exact_bilingual_business_terms() -> None:
    documents = (
        RetrievalDocument(
            builder_version="retrieval-document-v0.1",
            table="dim_region",
            text="Table: dim_region 地区 省份 region",
            tokens=("table", "dim_region", "dim", "region", "地区", "地", "区"),
        ),
        RetrievalDocument(
            builder_version="retrieval-document-v0.1",
            table="fact_order",
            text="Table: fact_order 订单 paid amount",
            tokens=("table", "fact_order", "fact", "order", "订单", "paid", "amount"),
        ),
    )

    ranked = lexical_rank("地区 region", documents, limit=2)

    assert [item.table for item in ranked] == ["dim_region"]


def test_rrf_preserves_both_rank_origins_and_deterministic_ties() -> None:
    fused = reciprocal_rank_fusion(
        (
            RankedTable(table="fact_order", score=12.0),
            RankedTable(table="dim_user", score=5.0),
        ),
        (
            RankedTable(table="dim_user", score=0.9),
            RankedTable(table="dim_region", score=0.8),
        ),
    )

    assert [item.table for item in fused] == ["dim_user", "fact_order", "dim_region"]
    assert fused[0].lexical_rank == 2
    assert fused[0].semantic_rank == 1
    assert fused[1].semantic_rank is None


def test_cosine_search_fails_closed_on_query_dimension_mismatch() -> None:
    index = asyncio.run(
        build_retrieval_index(
            catalog(),
            current_generated_schema_fingerprint=GENERATED_FINGERPRINT,
            current_semantic_revision=SEMANTIC_REVISION,
            embedding_model=TableAwareEmbeddingModel(),
            embedding_fingerprint=embedding_fingerprint(),
            model_runtime_version="test-runtime",
            embedding_batch_size=4,
        )
    )

    with pytest.raises(RetrievalQueryError, match="dimension"):
        semantic_rank([1.0, 0.0], index, limit=4)
