from pathlib import Path

import pytest

from data_agent.catalog.introspection import introspect_analytics_schema
from data_agent.catalog.semantic import (
    RELATIONSHIPS_SEMANTICS_PATH,
    TABLES_SEMANTICS_PATH,
    assemble_semantic_catalog,
    load_curated_semantics,
    write_assembled_catalog,
)
from data_agent.config import Settings


@pytest.mark.integration
def test_fixture_semantics_assemble_complete_deterministic_catalog(
    settings: Settings,
    tmp_path: Path,
) -> None:
    generated = introspect_analytics_schema(settings)
    curated = load_curated_semantics(
        tables_path=TABLES_SEMANTICS_PATH,
        relationships_path=RELATIONSHIPS_SEMANTICS_PATH,
    )

    assembled = assemble_semantic_catalog(generated, curated)

    assert len(assembled.documents) == 10
    assert len(assembled.relationships) == 10
    assert {document.table for document in assembled.documents} == {
        table.name for table in generated.tables
    }
    assert all(
        document.generated_metadata_fingerprint == generated.fingerprint
        for document in assembled.documents
    )
    assert all(
        document.semantic_revision == curated.semantic_revision for document in assembled.documents
    )
    assert all(relationship.curated for relationship in assembled.relationships)

    order = next(document for document in assembled.documents if document.table == "fact_order")
    paid_amount = next(column for column in order.columns if column.name == "paid_amount")
    assert "业务订单" in order.description
    assert paid_amount.data_type == "decimal(18,2)"
    assert paid_amount.aliases == ["支付金额", "实付金额"]

    generated_root = tmp_path / "catalog" / "generated"
    output_path = generated_root / "catalog.json"
    write_assembled_catalog(
        assembled,
        output_path=output_path,
        generated_root=generated_root,
    )
    first = output_path.read_bytes()
    write_assembled_catalog(
        assemble_semantic_catalog(generated, curated),
        output_path=output_path,
        generated_root=generated_root,
    )
    assert output_path.read_bytes() == first
