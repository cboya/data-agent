import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from data_agent.catalog.introspection import (
    CatalogOutputError,
    GeneratedColumnMetadata,
    GeneratedForeignKeyMetadata,
    GeneratedSchemaMetadata,
    GeneratedTableMetadata,
    load_generated_schema,
    reset_generated_catalog,
    write_generated_schema,
)


def _schema() -> GeneratedSchemaMetadata:
    return GeneratedSchemaMetadata.build(
        schema="analytics",
        tables=(
            GeneratedTableMetadata(
                name="dim_example",
                comment=None,
                columns=(
                    GeneratedColumnMetadata(
                        ordinal_position=1,
                        name="id",
                        data_type="bigint unsigned",
                        nullable=False,
                        primary_key=True,
                        comment=None,
                    ),
                ),
                foreign_keys=(),
            ),
            GeneratedTableMetadata(
                name="fact_example",
                comment="Example fact",
                columns=(
                    GeneratedColumnMetadata(
                        ordinal_position=1,
                        name="id",
                        data_type="bigint unsigned",
                        nullable=False,
                        primary_key=True,
                        comment=None,
                    ),
                    GeneratedColumnMetadata(
                        ordinal_position=2,
                        name="dimension_id",
                        data_type="bigint unsigned",
                        nullable=False,
                        primary_key=False,
                        comment="Dimension reference",
                    ),
                ),
                foreign_keys=(
                    GeneratedForeignKeyMetadata(
                        constraint_name="fk_example_dimension",
                        columns=("dimension_id",),
                        referenced_table="dim_example",
                        referenced_columns=("id",),
                    ),
                ),
            ),
        ),
    )


def test_generated_schema_fingerprint_is_canonical_and_revalidated() -> None:
    schema = _schema()

    assert len(schema.fingerprint) == 64
    assert schema.fingerprint == _schema().fingerprint

    tampered = schema.model_dump(mode="json")
    tampered["tables"][1]["comment"] = "changed after fingerprinting"
    with pytest.raises(ValidationError, match="fingerprint"):
        GeneratedSchemaMetadata.model_validate(tampered)


def test_generated_schema_requires_sorted_complete_internal_metadata() -> None:
    schema = _schema()
    reversed_tables = tuple(reversed(schema.tables))

    with pytest.raises(ValidationError, match="sorted"):
        GeneratedSchemaMetadata.build(schema="analytics", tables=reversed_tables)

    invalid_reference = schema.tables[1].model_copy(
        update={
            "foreign_keys": (
                GeneratedForeignKeyMetadata(
                    constraint_name="fk_outside",
                    columns=("dimension_id",),
                    referenced_table="control_table",
                    referenced_columns=("id",),
                ),
            )
        }
    )
    with pytest.raises(ValidationError, match="unknown table"):
        GeneratedSchemaMetadata.build(
            schema="analytics",
            tables=(schema.tables[0], invalid_reference),
        )


def test_generated_schema_write_is_deterministic_and_generated_only(tmp_path: Path) -> None:
    schema = _schema()
    generated_root = tmp_path / "catalog" / "generated"
    output_path = generated_root / "schema.json"

    write_generated_schema(
        schema,
        output_path=output_path,
        generated_root=generated_root,
    )
    first = output_path.read_bytes()
    write_generated_schema(
        schema,
        output_path=output_path,
        generated_root=generated_root,
    )

    assert output_path.read_bytes() == first
    assert load_generated_schema(output_path) == schema
    payload = json.loads(first)
    assert payload["fingerprint"] == schema.fingerprint
    assert "aliases" not in payload["tables"][0]
    assert "business_rules" not in payload["tables"][0]

    semantic_path = tmp_path / "catalog" / "semantic" / "schema.json"
    with pytest.raises(CatalogOutputError, match="catalog/generated"):
        write_generated_schema(
            schema,
            output_path=semantic_path,
            generated_root=generated_root,
        )
    assert not semantic_path.exists()


def test_generated_catalog_reset_never_removes_semantic_files(tmp_path: Path) -> None:
    generated_root = tmp_path / "catalog" / "generated"
    semantic_root = tmp_path / "catalog" / "semantic"
    generated_root.mkdir(parents=True)
    semantic_root.mkdir(parents=True)
    (generated_root / "schema.json").write_text("generated", encoding="utf-8")
    semantic_file = semantic_root / "tables.yaml"
    semantic_file.write_text("curated", encoding="utf-8")

    reset_generated_catalog(generated_root=generated_root)

    assert not generated_root.exists()
    assert semantic_file.read_text(encoding="utf-8") == "curated"
