from pathlib import Path

import pytest

from data_agent.catalog.introspection import (
    GeneratedSchemaMetadata,
    GeneratedTableMetadata,
    introspect_analytics_schema,
    load_generated_schema,
    write_generated_schema,
)
from data_agent.config import Settings

EXPECTED_TABLES = [
    "dim_category",
    "dim_channel",
    "dim_product",
    "dim_region",
    "dim_user",
    "fact_order",
    "fact_order_item",
    "fact_payment_transaction",
    "fact_refund",
    "fact_user_event",
]


def _table(schema: GeneratedSchemaMetadata, name: str) -> GeneratedTableMetadata:
    return next(table for table in schema.tables if table.name == name)


@pytest.mark.integration
def test_generated_metadata_matches_fixture_and_excludes_control_schema(
    settings: Settings,
) -> None:
    schema = introspect_analytics_schema(settings)

    assert schema.schema_name == settings.mysql_database
    assert [table.name for table in schema.tables] == EXPECTED_TABLES
    assert settings.mysql_control_database not in schema.model_dump_json()

    order = _table(schema, "fact_order")
    assert [column.name for column in order.columns] == [
        "id",
        "user_id",
        "channel_id",
        "status",
        "total_amount",
        "paid_amount",
        "created_at",
        "paid_at",
        "completed_at",
    ]
    paid_amount = next(column for column in order.columns if column.name == "paid_amount")
    assert paid_amount.data_type == "decimal(18,2)"
    assert paid_amount.nullable is True
    assert order.columns[0].primary_key is True
    assert {
        (foreign_key.columns, foreign_key.referenced_table, foreign_key.referenced_columns)
        for foreign_key in order.foreign_keys
    } == {
        (("channel_id",), "dim_channel", ("id",)),
        (("user_id",), "dim_user", ("id",)),
    }


@pytest.mark.integration
def test_rebuild_produces_identical_fingerprint_and_bytes(
    settings: Settings,
    tmp_path: Path,
) -> None:
    first = introspect_analytics_schema(settings)
    second = introspect_analytics_schema(settings)
    generated_root = tmp_path / "catalog" / "generated"
    output_path = generated_root / "schema.json"

    write_generated_schema(first, output_path=output_path, generated_root=generated_root)
    first_bytes = output_path.read_bytes()
    write_generated_schema(second, output_path=output_path, generated_root=generated_root)

    assert second == first
    assert second.fingerprint == first.fingerprint
    assert output_path.read_bytes() == first_bytes
    assert load_generated_schema(output_path) == first
