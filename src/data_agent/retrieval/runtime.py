"""Ollama composition for current-authority index build, load, and standalone eval."""

from __future__ import annotations

from dataclasses import dataclass

from data_agent.catalog.introspection import GeneratedSchemaMetadata, load_generated_schema
from data_agent.catalog.semantic import (
    AssembledSemanticCatalog,
    CuratedSemanticCatalog,
    assemble_semantic_catalog,
    load_assembled_catalog,
    load_curated_semantics,
)
from data_agent.config import Settings
from data_agent.model_runtime.ollama import (
    OllamaEmbeddingModel,
    OllamaStartupDiagnostics,
)
from data_agent.model_runtime.ports import ModelRuntimeDiagnostics
from data_agent.retrieval.errors import RetrievalIndexStaleError
from data_agent.retrieval.evaluation import (
    RetrievalEvalReport,
    load_retrieval_eval_suite,
    run_retrieval_evaluation,
    write_retrieval_eval_report,
)
from data_agent.retrieval.index import (
    RetrievalIndex,
    build_retrieval_index,
    load_retrieval_index,
    write_retrieval_index,
)
from data_agent.retrieval.service import HybridRetriever


@dataclass(frozen=True)
class CurrentCatalogAuthority:
    generated: GeneratedSchemaMetadata
    curated: CuratedSemanticCatalog
    assembled: AssembledSemanticCatalog


@dataclass(frozen=True)
class CurrentRetrievalRuntime:
    authority: CurrentCatalogAuthority
    diagnostics: ModelRuntimeDiagnostics
    index: RetrievalIndex
    retriever: HybridRetriever


def load_current_catalog_authority() -> CurrentCatalogAuthority:
    """Reject an internally valid catalog that is stale relative to current source authority."""
    generated = load_generated_schema()
    curated = load_curated_semantics()
    assembled = load_assembled_catalog()
    fresh = assemble_semantic_catalog(generated, curated)
    if assembled != fresh:
        raise RetrievalIndexStaleError(
            "assembled catalog is stale relative to current generated and curated authority"
        )
    return CurrentCatalogAuthority(
        generated=generated,
        curated=curated,
        assembled=assembled,
    )


async def rebuild_current_retrieval_index(settings: Settings) -> RetrievalIndex:
    authority = load_current_catalog_authority()
    diagnostics = await OllamaStartupDiagnostics(settings).diagnose()
    embedding_model = OllamaEmbeddingModel(
        settings,
        fingerprint=diagnostics.embedding,
    )
    index = await build_retrieval_index(
        authority.assembled,
        current_generated_schema_fingerprint=authority.generated.fingerprint,
        current_semantic_revision=authority.curated.semantic_revision,
        embedding_model=embedding_model,
        embedding_fingerprint=diagnostics.embedding,
        model_runtime_version=diagnostics.runtime_version,
        embedding_batch_size=settings.ollama_max_embedding_batch,
    )
    write_retrieval_index(index)
    return index


async def load_current_retrieval_runtime(settings: Settings) -> CurrentRetrievalRuntime:
    authority = load_current_catalog_authority()
    diagnostics = await OllamaStartupDiagnostics(settings).diagnose()
    index = load_retrieval_index(
        catalog=authority.assembled,
        current_generated_schema_fingerprint=authority.generated.fingerprint,
        current_semantic_revision=authority.curated.semantic_revision,
        embedding_fingerprint=diagnostics.embedding,
        model_runtime_version=diagnostics.runtime_version,
    )
    embedding_model = OllamaEmbeddingModel(
        settings,
        fingerprint=diagnostics.embedding,
    )
    retriever = HybridRetriever(
        index=index,
        catalog=authority.assembled,
        embedding_model=embedding_model,
        embedding_fingerprint=diagnostics.embedding,
        model_runtime_version=diagnostics.runtime_version,
        lexical_top_k=settings.retrieval_lexical_top_k,
        semantic_top_k=settings.retrieval_semantic_top_k,
        seed_table_limit=settings.retrieval_seed_tables,
        max_relationship_hops=settings.max_relationship_hops,
        max_total_tables=settings.max_retrieved_tables,
        rrf_k=settings.retrieval_rrf_k,
    )
    return CurrentRetrievalRuntime(
        authority=authority,
        diagnostics=diagnostics,
        index=index,
        retriever=retriever,
    )


async def evaluate_current_retrieval(settings: Settings) -> RetrievalEvalReport:
    runtime = await load_current_retrieval_runtime(settings)
    report = await run_retrieval_evaluation(
        runtime.retriever,
        index=runtime.index,
        suite=load_retrieval_eval_suite(),
    )
    write_retrieval_eval_report(report)
    return report
