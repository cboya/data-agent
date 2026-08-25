"""Provider-neutral hybrid retrieval and bounded M6 relationship expansion."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from data_agent.catalog.semantic import AssembledSemanticCatalog
from data_agent.contracts.catalog import Relationship
from data_agent.contracts.retrieval import RetrievalHit, RetrievalResult
from data_agent.model_runtime.ports import EmbeddingModel, ModelFingerprint
from data_agent.retrieval.errors import RetrievalIndexStaleError, RetrievalQueryError
from data_agent.retrieval.index import (
    EmbeddingModelIdentity,
    RetrievalIndex,
    assert_index_documents,
)
from data_agent.retrieval.ranking import lexical_rank, reciprocal_rank_fusion, semantic_rank


def relationship_key(relationship: Relationship) -> tuple[str, str, str, str]:
    return (
        str(relationship.from_table),
        str(relationship.from_column),
        str(relationship.to_table),
        str(relationship.to_column),
    )


def relationship_id(relationship: Relationship) -> str:
    key = relationship_key(relationship)
    return f"{key[0]}.{key[1]}->{key[2]}.{key[3]}"


@dataclass(frozen=True)
class GraphExpansionTrace:
    table: str
    seed_table: str
    hop: int
    relationship_path: tuple[str, ...]


@dataclass(frozen=True)
class RetrievalTrace:
    result: RetrievalResult
    fused_candidates: tuple[RetrievalHit, ...]
    graph_expansions: tuple[GraphExpansionTrace, ...]


@dataclass(frozen=True)
class _TraversalState:
    seed_table: str
    table: str
    hop: int
    path: tuple[Relationship, ...]


class HybridRetriever:
    """Search one bound index and expand only its validated M6 relationship graph."""

    def __init__(
        self,
        *,
        index: RetrievalIndex,
        catalog: AssembledSemanticCatalog,
        embedding_model: EmbeddingModel,
        embedding_fingerprint: ModelFingerprint,
        model_runtime_version: str,
        lexical_top_k: int = 10,
        semantic_top_k: int = 10,
        seed_table_limit: int = 4,
        max_relationship_hops: int = 1,
        max_total_tables: int = 8,
        rrf_k: float = 60.0,
    ) -> None:
        if index.identity.catalog_fingerprint != catalog.catalog_fingerprint:
            raise RetrievalIndexStaleError("retriever index does not match assembled catalog")
        if index.identity.generated_schema_fingerprint != catalog.generated_metadata_fingerprint:
            raise RetrievalIndexStaleError("retriever index does not match generated schema")
        if index.identity.semantic_revision != catalog.semantic_revision:
            raise RetrievalIndexStaleError("retriever index does not match semantic revision")
        if index.identity.embedding_model != EmbeddingModelIdentity.from_fingerprint(
            embedding_fingerprint
        ):
            raise RetrievalIndexStaleError(
                "query embedding identity does not match retrieval index"
            )
        if index.identity.model_runtime_version != model_runtime_version:
            raise RetrievalIndexStaleError("query model runtime does not match retrieval index")
        assert_index_documents(index, catalog)
        if min(lexical_top_k, semantic_top_k, seed_table_limit, max_total_tables) < 1:
            raise ValueError("retrieval rank and table bounds must be positive")
        if seed_table_limit > max_total_tables:
            raise ValueError("retrieval seed bound cannot exceed total table bound")
        if not 0 <= max_relationship_hops <= 3:
            raise ValueError("relationship hop bound must be between zero and three")

        self._index = index
        self._catalog = catalog
        self._embedding_model = embedding_model
        self._lexical_top_k = lexical_top_k
        self._semantic_top_k = semantic_top_k
        self._seed_table_limit = seed_table_limit
        self._max_relationship_hops = max_relationship_hops
        self._max_total_tables = max_total_tables
        self._rrf_k = rrf_k

    async def retrieve(self, query: str) -> RetrievalTrace:
        if not query.strip():
            raise RetrievalQueryError("retrieval query cannot be blank")
        query_vectors = await self._embedding_model.embed([query])
        if len(query_vectors) != 1:
            raise RetrievalQueryError("embedding model returned the wrong query vector count")

        documents = tuple(entry.document for entry in self._index.entries)
        lexical = lexical_rank(query, documents, limit=self._lexical_top_k)
        semantic = semantic_rank(
            query_vectors[0],
            self._index,
            limit=self._semantic_top_k,
        )
        fused = reciprocal_rank_fusion(lexical, semantic, rrf_k=self._rrf_k)
        if not fused:
            raise RetrievalQueryError("hybrid retrieval produced no candidate table")
        fused_hits = tuple(
            RetrievalHit(
                table=candidate.table,
                lexical_rank=candidate.lexical_rank,
                semantic_rank=candidate.semantic_rank,
                fused_score=candidate.fused_score,
                rerank_score=None,
                reason="RRF lexical+semantic fusion",
                source="SEED",
            )
            for candidate in fused
        )
        seed_hits = list(fused_hits[: self._seed_table_limit])
        graph_hits, graph_traces = self._expand_graph(seed_hits)
        hits = [*seed_hits, *graph_hits]
        selected_tables = {str(hit.table) for hit in hits}
        relationships = sorted(
            (
                relationship
                for relationship in self._catalog.relationships
                if str(relationship.from_table) in selected_tables
                and str(relationship.to_table) in selected_tables
            ),
            key=relationship_key,
        )
        result = RetrievalResult(
            version="v0.1",
            query=query,
            hits=hits,
            relationships=relationships,
            index_fingerprint=self._index.fingerprint,
        )
        return RetrievalTrace(
            result=result,
            fused_candidates=fused_hits,
            graph_expansions=tuple(graph_traces),
        )

    def _adjacency(self) -> dict[str, tuple[tuple[str, Relationship], ...]]:
        mutable: dict[str, list[tuple[str, Relationship]]] = {}
        for relationship in sorted(self._catalog.relationships, key=relationship_key):
            from_table = str(relationship.from_table)
            to_table = str(relationship.to_table)
            mutable.setdefault(from_table, []).append((to_table, relationship))
            mutable.setdefault(to_table, []).append((from_table, relationship))
        return {
            table: tuple(
                sorted(
                    neighbors,
                    key=lambda item: (item[0], relationship_key(item[1])),
                )
            )
            for table, neighbors in mutable.items()
        }

    def _expand_graph(
        self,
        seed_hits: list[RetrievalHit],
    ) -> tuple[list[RetrievalHit], list[GraphExpansionTrace]]:
        if self._max_relationship_hops == 0 or len(seed_hits) >= self._max_total_tables:
            return [], []
        adjacency = self._adjacency()
        selected = {str(hit.table) for hit in seed_hits}
        queue: deque[_TraversalState] = deque(
            _TraversalState(
                seed_table=str(hit.table),
                table=str(hit.table),
                hop=0,
                path=(),
            )
            for hit in seed_hits
        )
        visited = {(state.seed_table, state.table) for state in queue}
        graph_hits: list[RetrievalHit] = []
        traces: list[GraphExpansionTrace] = []

        while queue and len(selected) < self._max_total_tables:
            state = queue.popleft()
            if state.hop >= self._max_relationship_hops:
                continue
            for neighbor, relationship in adjacency.get(state.table, ()):
                visit_key = (state.seed_table, neighbor)
                if visit_key in visited:
                    continue
                visited.add(visit_key)
                path = (*state.path, relationship)
                hop = state.hop + 1
                queue.append(
                    _TraversalState(
                        seed_table=state.seed_table,
                        table=neighbor,
                        hop=hop,
                        path=path,
                    )
                )
                if neighbor in selected:
                    continue
                path_ids = tuple(relationship_id(item) for item in path)
                selected.add(neighbor)
                traces.append(
                    GraphExpansionTrace(
                        table=neighbor,
                        seed_table=state.seed_table,
                        hop=hop,
                        relationship_path=path_ids,
                    )
                )
                graph_hits.append(
                    RetrievalHit(
                        table=neighbor,
                        lexical_rank=None,
                        semantic_rank=None,
                        fused_score=0.0,
                        rerank_score=None,
                        reason=(f"seed={state.seed_table}; hop={hop}; path={' | '.join(path_ids)}"),
                        source="GRAPH_EXPANSION",
                    )
                )
                if len(selected) >= self._max_total_tables:
                    break
        return graph_hits, traces
