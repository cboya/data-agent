import asyncio
from pathlib import Path

from data_agent.retrieval.evaluation import (
    RetrievalEvalCase,
    RetrievalEvalSuite,
    load_retrieval_eval_suite,
    run_retrieval_evaluation,
    write_retrieval_eval_report,
)
from data_agent.retrieval.index import build_retrieval_index
from data_agent.retrieval.service import HybridRetriever
from tests.retrieval.factories import (
    GENERATED_FINGERPRINT,
    SEMANTIC_REVISION,
    TableAwareEmbeddingModel,
    catalog,
    embedding_fingerprint,
)


def test_frozen_retrieval_suite_is_strict_and_covers_bilingual_paths() -> None:
    suite = load_retrieval_eval_suite()

    assert len(suite.cases) == 24
    assert any("地区" in case.query for case in suite.cases)
    assert any("region" in case.query.casefold() for case in suite.cases)
    assert sum(bool(case.relationship_path) for case in suite.cases) >= 10


def test_standalone_eval_reports_seed_final_and_path_metrics(tmp_path: Path) -> None:
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
    retriever = HybridRetriever(
        index=index,
        catalog=assembled,
        embedding_model=model,
        embedding_fingerprint=embedding_fingerprint(),
        model_runtime_version="test-runtime",
        lexical_top_k=4,
        semantic_top_k=4,
        seed_table_limit=1,
        max_relationship_hops=2,
        max_total_tables=4,
    )
    suite = RetrievalEvalSuite(
        version="v0.1",
        cases=(
            RetrievalEvalCase(
                id="order-region",
                query="order",
                required_tables=("fact_order", "dim_user", "dim_region"),
                relationship_path=(
                    "fact_order.user_id->dim_user.id",
                    "dim_user.region_id->dim_region.id",
                ),
            ),
        ),
    )

    report = asyncio.run(run_retrieval_evaluation(retriever, index=index, suite=suite))
    output_path = tmp_path / "reports" / "retrieval.json"
    write_retrieval_eval_report(report, output_path=output_path)

    assert report.metrics.seed_recall_at_5 == 1 / 3
    assert report.metrics.seed_recall_at_10 == 1 / 3
    assert report.metrics.final_recall_at_5 == 1.0
    assert report.metrics.final_recall_at_10 == 1.0
    assert report.metrics.relationship_path_recovery == 1.0
    assert report.cases[0].seed_tables == ("fact_order",)
    assert report.cases[0].final_tables == (
        "fact_order",
        "dim_channel",
        "dim_user",
        "dim_region",
    )
    assert report.passed is True
    assert output_path.is_file()
