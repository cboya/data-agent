import asyncio
import json
from pathlib import Path

import pytest

from data_agent.retrieval.errors import RetrievalIndexError, RetrievalIndexStaleError
from data_agent.retrieval.index import (
    RetrievalIndex,
    RetrievalIndexEntry,
    build_retrieval_index,
    load_retrieval_index,
    write_retrieval_index,
)
from tests.retrieval.factories import (
    GENERATED_FINGERPRINT,
    SEMANTIC_REVISION,
    DeterministicEmbeddingModel,
    catalog,
    embedding_fingerprint,
)


async def _build() -> RetrievalIndex:
    return await build_retrieval_index(
        catalog(),
        current_generated_schema_fingerprint=GENERATED_FINGERPRINT,
        current_semantic_revision=SEMANTIC_REVISION,
        embedding_model=DeterministicEmbeddingModel(),
        embedding_fingerprint=embedding_fingerprint(),
        model_runtime_version="test-runtime",
        embedding_batch_size=2,
    )


def test_index_identity_and_artifact_bytes_are_deterministic(tmp_path: Path) -> None:
    first = asyncio.run(_build())
    second = asyncio.run(_build())
    generated_root = tmp_path / "catalog" / "generated"
    output_path = generated_root / "index" / "retrieval.json"

    write_retrieval_index(first, output_path=output_path, generated_root=generated_root)
    first_bytes = output_path.read_bytes()
    write_retrieval_index(second, output_path=output_path, generated_root=generated_root)

    assert first == second
    assert output_path.read_bytes() == first_bytes
    assert first.identity.catalog_fingerprint == catalog().catalog_fingerprint
    assert first.identity.generated_schema_fingerprint == GENERATED_FINGERPRINT
    assert first.identity.semantic_revision == SEMANTIC_REVISION
    assert first.identity.embedding_model.fingerprint == embedding_fingerprint().value
    assert first.identity.model_runtime_version == "test-runtime"
    assert first.identity.index_format_version == "retrieval-index-v0.1"
    assert first.identity.document_builder_version == "retrieval-document-v0.1"


def test_load_rejects_tampered_index_content(tmp_path: Path) -> None:
    index = asyncio.run(_build())
    generated_root = tmp_path / "catalog" / "generated"
    output_path = generated_root / "index" / "retrieval.json"
    write_retrieval_index(index, output_path=output_path, generated_root=generated_root)
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    payload["entries"][0]["document"]["text"] = "tampered"
    output_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RetrievalIndexError, match="fingerprint"):
        load_retrieval_index(
            catalog=catalog(),
            current_generated_schema_fingerprint=GENERATED_FINGERPRINT,
            current_semantic_revision=SEMANTIC_REVISION,
            embedding_fingerprint=embedding_fingerprint(),
            model_runtime_version="test-runtime",
            path=output_path,
        )


def test_load_rejects_rehashed_documents_that_do_not_match_current_projection(
    tmp_path: Path,
) -> None:
    index = asyncio.run(_build())
    first = index.entries[0]
    drifted_document = first.document.model_copy(update={"text": "rehashed but stale"})
    drifted = RetrievalIndex.build(
        identity=index.identity,
        entries=(
            RetrievalIndexEntry(document=drifted_document, embedding=first.embedding),
            *index.entries[1:],
        ),
    )
    generated_root = tmp_path / "catalog" / "generated"
    output_path = generated_root / "index" / "retrieval.json"
    write_retrieval_index(drifted, output_path=output_path, generated_root=generated_root)

    with pytest.raises(RetrievalIndexStaleError, match="catalog projections"):
        load_retrieval_index(
            catalog=catalog(),
            current_generated_schema_fingerprint=GENERATED_FINGERPRINT,
            current_semantic_revision=SEMANTIC_REVISION,
            embedding_fingerprint=embedding_fingerprint(),
            model_runtime_version="test-runtime",
            path=output_path,
        )


@pytest.mark.parametrize(
    ("generated_fingerprint", "semantic_revision", "model_digest", "runtime_version"),
    [
        ("c" * 64, SEMANTIC_REVISION, "embedding-digest", "test-runtime"),
        (GENERATED_FINGERPRINT, "c" * 64, "embedding-digest", "test-runtime"),
        (GENERATED_FINGERPRINT, SEMANTIC_REVISION, "other-digest", "test-runtime"),
        (GENERATED_FINGERPRINT, SEMANTIC_REVISION, "embedding-digest", "other-runtime"),
    ],
)
def test_index_identity_drift_fails_closed(
    tmp_path: Path,
    generated_fingerprint: str,
    semantic_revision: str,
    model_digest: str,
    runtime_version: str,
) -> None:
    index = asyncio.run(_build())
    generated_root = tmp_path / "catalog" / "generated"
    output_path = generated_root / "index" / "retrieval.json"
    write_retrieval_index(index, output_path=output_path, generated_root=generated_root)

    with pytest.raises(RetrievalIndexStaleError):
        load_retrieval_index(
            catalog=catalog(),
            current_generated_schema_fingerprint=generated_fingerprint,
            current_semantic_revision=semantic_revision,
            embedding_fingerprint=embedding_fingerprint(digest=model_digest),
            model_runtime_version=runtime_version,
            path=output_path,
        )


def test_build_rejects_stale_assembled_catalog_before_embedding() -> None:
    with pytest.raises(RetrievalIndexStaleError, match="generated schema"):
        asyncio.run(
            build_retrieval_index(
                catalog(),
                current_generated_schema_fingerprint="c" * 64,
                current_semantic_revision=SEMANTIC_REVISION,
                embedding_model=DeterministicEmbeddingModel(),
                embedding_fingerprint=embedding_fingerprint(),
                model_runtime_version="test-runtime",
                embedding_batch_size=2,
            )
        )
