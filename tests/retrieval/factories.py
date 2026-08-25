"""Focused deterministic M7 fixtures."""

from __future__ import annotations

import hashlib
from typing import ClassVar

from data_agent.catalog.semantic import AssembledSemanticCatalog
from data_agent.contracts.catalog import (
    Cardinality,
    CatalogColumn,
    CatalogDocument,
    Relationship,
)
from data_agent.model_runtime.ports import ModelFingerprint

GENERATED_FINGERPRINT = "a" * 64
SEMANTIC_REVISION = "b" * 64


def embedding_fingerprint(*, digest: str = "embedding-digest") -> ModelFingerprint:
    return ModelFingerprint(
        provider="test",
        model="bilingual-embedding",
        digest=digest,
        capabilities=("embedding",),
        metadata=(("dimensions", "4"),),
    )


def _document(
    table: str,
    *,
    aliases: list[str],
    description: str,
    columns: list[tuple[str, str]],
    use_cases: list[str],
) -> CatalogDocument:
    return CatalogDocument(
        version="v0.1",
        table=table,
        aliases=aliases,
        description=description,
        business_rules=[f"{table} governed rule"],
        columns=[
            CatalogColumn(
                name=name,
                data_type="bigint",
                description=column_description,
            )
            for name, column_description in columns
        ],
        typical_use_cases=use_cases,
        generated_metadata_fingerprint=GENERATED_FINGERPRINT,
        semantic_revision=SEMANTIC_REVISION,
    )


def catalog(*, include_relationships: bool = True) -> AssembledSemanticCatalog:
    documents = (
        _document(
            "dim_channel",
            aliases=["渠道", "channel"],
            description="Channel dimension",
            columns=[("id", "Channel identifier")],
            use_cases=["channel analysis"],
        ),
        _document(
            "dim_region",
            aliases=["地区", "region"],
            description="Region dimension",
            columns=[("id", "Region identifier")],
            use_cases=["regional analysis"],
        ),
        _document(
            "dim_user",
            aliases=["用户", "user"],
            description="User dimension",
            columns=[("id", "User identifier"), ("region_id", "User region")],
            use_cases=["user analysis"],
        ),
        _document(
            "fact_order",
            aliases=["订单", "order"],
            description="Order facts and paid amount",
            columns=[
                ("id", "Order identifier"),
                ("channel_id", "Order channel"),
                ("user_id", "Ordering user"),
            ],
            use_cases=["order count", "paid amount"],
        ),
    )
    relationships = (
        (
            Relationship(
                version="v0.1",
                from_table="dim_user",
                from_column="region_id",
                to_table="dim_region",
                to_column="id",
                cardinality=Cardinality.MANY_TO_ONE,
                description="User region",
                curated=True,
            ),
            Relationship(
                version="v0.1",
                from_table="fact_order",
                from_column="channel_id",
                to_table="dim_channel",
                to_column="id",
                cardinality=Cardinality.MANY_TO_ONE,
                description="Order channel",
                curated=True,
            ),
            Relationship(
                version="v0.1",
                from_table="fact_order",
                from_column="user_id",
                to_table="dim_user",
                to_column="id",
                cardinality=Cardinality.MANY_TO_ONE,
                description="Ordering user",
                curated=True,
            ),
        )
        if include_relationships
        else ()
    )
    return AssembledSemanticCatalog.build(
        generated_metadata_fingerprint=GENERATED_FINGERPRINT,
        semantic_revision=SEMANTIC_REVISION,
        documents=documents,
        relationships=relationships,
    )


class DeterministicEmbeddingModel:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            vectors.append([value / 255 + 0.01 for value in digest[:4]])
        return vectors


class TableAwareEmbeddingModel:
    _TABLE_VECTORS: ClassVar[dict[str, list[float]]] = {
        "dim_channel": [0.0, 0.0, 0.0, 1.0],
        "dim_region": [0.0, 0.0, 1.0, 0.0],
        "dim_user": [0.0, 1.0, 0.0, 0.0],
        "fact_order": [1.0, 0.0, 0.0, 0.0],
    }

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            if text.startswith("Table: "):
                table = text.splitlines()[0].removeprefix("Table: ")
                vectors.append(list(self._TABLE_VECTORS[table]))
            elif "order" in text.casefold() or "订单" in text:
                vectors.append([1.0, 0.0, 0.0, 0.0])
            elif "region" in text.casefold() or "地区" in text:
                vectors.append([0.0, 0.0, 1.0, 0.0])
            else:
                vectors.append([0.0, 1.0, 0.0, 0.0])
        return vectors
