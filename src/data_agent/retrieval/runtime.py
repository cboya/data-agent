"""Provider-neutral composition for current-authority retrieval runtime and eval."""

from __future__ import annotations

from dataclasses import dataclass

from data_agent.analytics import active_analytics_source
from data_agent.catalog.introspection import GeneratedSchemaMetadata, load_generated_schema
from data_agent.catalog.semantic import (
    AssembledSemanticCatalog,
    CuratedSemanticCatalog,
    assemble_semantic_catalog,
    load_assembled_catalog,
    load_curated_semantics,
)
from data_agent.catalog.workspace import active_catalog_workspace
from data_agent.config import Settings
from data_agent.model_runtime.composition import start_model_runtime
from data_agent.model_runtime.ports import ChatModel, ModelRuntimeDiagnostics
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
    chat_model: ChatModel


def load_current_catalog_authority(settings: Settings) -> CurrentCatalogAuthority:
    """Reject an internally valid catalog that is stale relative to current source authority."""
    profile = active_analytics_source(settings)
    workspace = active_catalog_workspace(settings)
    generated = load_generated_schema(workspace.generated_schema_path)
    if generated.schema_name != profile.database:
        raise RetrievalIndexStaleError(
            "generated catalog database does not match current analytics source profile"
        )
    generated_tables = tuple(table.name for table in generated.tables)
    if generated_tables != profile.allowed_tables:
        raise RetrievalIndexStaleError(
            "generated catalog allowed-table surface does not match "
            "current analytics source profile"
        )
    curated = load_curated_semantics(
        tables_path=workspace.tables_semantics_path,
        relationships_path=workspace.relationships_semantics_path,
    )
    assembled = load_assembled_catalog(workspace.assembled_catalog_path)
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
    workspace = active_catalog_workspace(settings)
    authority = load_current_catalog_authority(settings)
    runtime = await start_model_runtime(settings)
    diagnostics = runtime.diagnostics
    index = await build_retrieval_index(
        authority.assembled,
        current_generated_schema_fingerprint=authority.generated.fingerprint,
        current_semantic_revision=authority.curated.semantic_revision,
        embedding_model=runtime.embedding_model,
        embedding_fingerprint=diagnostics.embedding,
        model_runtime_version=diagnostics.runtime_version,
        embedding_batch_size=runtime.embedding_batch_size,
    )
    write_retrieval_index(
        index,
        output_path=workspace.retrieval_index_path,
        generated_root=workspace.generated_root,
    )
    return index


async def load_current_retrieval_runtime(settings: Settings) -> CurrentRetrievalRuntime:
    workspace = active_catalog_workspace(settings)
    authority = load_current_catalog_authority(settings)
    runtime = await start_model_runtime(settings)
    diagnostics = runtime.diagnostics
    index = load_retrieval_index(
        catalog=authority.assembled,
        current_generated_schema_fingerprint=authority.generated.fingerprint,
        current_semantic_revision=authority.curated.semantic_revision,
        embedding_fingerprint=diagnostics.embedding,
        model_runtime_version=diagnostics.runtime_version,
        path=workspace.retrieval_index_path,
    )
    retriever = HybridRetriever(
        index=index,
        catalog=authority.assembled,
        embedding_model=runtime.embedding_model,
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
        chat_model=runtime.chat_model,
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
