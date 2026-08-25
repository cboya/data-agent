import json
from pathlib import Path

import pytest

from data_agent.catalog.introspection import (
    GeneratedColumnMetadata,
    GeneratedForeignKeyMetadata,
    GeneratedSchemaMetadata,
    GeneratedTableMetadata,
)
from data_agent.catalog.semantic import (
    AssembledSemanticCatalog,
    SemanticCatalogError,
    assemble_semantic_catalog,
    load_assembled_catalog,
    load_curated_semantics,
    write_assembled_catalog,
)
from data_agent.contracts.catalog import Cardinality


def _generated() -> GeneratedSchemaMetadata:
    return GeneratedSchemaMetadata.build(
        schema="analytics",
        tables=(
            GeneratedTableMetadata(
                name="dim_parent",
                comment="Generated parent comment",
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
                name="fact_child",
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
                    GeneratedColumnMetadata(
                        ordinal_position=2,
                        name="parent_id",
                        data_type="bigint unsigned",
                        nullable=False,
                        primary_key=False,
                        comment="Generated FK comment",
                    ),
                ),
                foreign_keys=(
                    GeneratedForeignKeyMetadata(
                        constraint_name="fk_child_parent",
                        columns=("parent_id",),
                        referenced_table="dim_parent",
                        referenced_columns=("id",),
                    ),
                ),
            ),
        ),
    )


def _generated_with_composite_fk() -> GeneratedSchemaMetadata:
    return GeneratedSchemaMetadata.build(
        schema="analytics",
        tables=(
            GeneratedTableMetadata(
                name="dim_parent",
                comment=None,
                columns=(
                    GeneratedColumnMetadata(
                        ordinal_position=1,
                        name="tenant_id",
                        data_type="bigint unsigned",
                        nullable=False,
                        primary_key=True,
                        comment=None,
                    ),
                    GeneratedColumnMetadata(
                        ordinal_position=2,
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
                name="fact_child",
                comment=None,
                columns=(
                    GeneratedColumnMetadata(
                        ordinal_position=1,
                        name="tenant_id",
                        data_type="bigint unsigned",
                        nullable=False,
                        primary_key=False,
                        comment=None,
                    ),
                    GeneratedColumnMetadata(
                        ordinal_position=2,
                        name="parent_id",
                        data_type="bigint unsigned",
                        nullable=False,
                        primary_key=False,
                        comment=None,
                    ),
                ),
                foreign_keys=(
                    GeneratedForeignKeyMetadata(
                        constraint_name="fk_child_parent",
                        columns=("tenant_id", "parent_id"),
                        referenced_table="dim_parent",
                        referenced_columns=("tenant_id", "id"),
                    ),
                ),
            ),
        ),
    )


def _write_semantics(
    root: Path,
    *,
    tables: str | None = None,
    relationships: str | None = None,
) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    tables_path = root / "tables.yaml"
    relationships_path = root / "relationships.yaml"
    tables_path.write_text(
        tables
        or """\
version: v0.1
tables:
  dim_parent:
    aliases: [parent]
    description: Curated parent description
    column_semantics:
      id:
        description: Parent identifier
  fact_child:
    aliases: [child]
    description: Curated child description
    business_rules: [Do not infer relationship cardinality from the FK.]
    column_semantics:
      parent_id:
        description: Curated parent reference
        aliases: [parent key]
    typical_use_cases: [child analysis]
""",
        encoding="utf-8",
    )
    relationships_path.write_text(
        relationships
        or """\
version: v0.1
relationships:
  - from_table: fact_child
    from_column: parent_id
    to_table: dim_parent
    to_column: id
    cardinality: ONE_TO_ONE
    description: Curated cardinality authority
""",
        encoding="utf-8",
    )
    return tables_path, relationships_path


def test_semantic_merge_combines_metadata_and_curated_authority(tmp_path: Path) -> None:
    tables_path, relationships_path = _write_semantics(tmp_path / "catalog" / "semantic")
    curated = load_curated_semantics(
        tables_path=tables_path,
        relationships_path=relationships_path,
    )

    assembled = assemble_semantic_catalog(_generated(), curated)

    assert [document.table for document in assembled.documents] == [
        "dim_parent",
        "fact_child",
    ]
    child = assembled.documents[1]
    assert child.description == "Curated child description"
    assert child.generated_metadata_fingerprint == _generated().fingerprint
    assert child.semantic_revision == assembled.semantic_revision
    parent_id = next(column for column in child.columns if column.name == "parent_id")
    assert parent_id.data_type == "bigint unsigned"
    assert parent_id.nullable is False
    assert parent_id.description == "Curated parent reference"
    assert parent_id.aliases == ["parent key"]
    assert assembled.relationships[0].cardinality is Cardinality.ONE_TO_ONE
    assert assembled.relationships[0].curated is True


@pytest.mark.parametrize(
    ("column_name", "column_overlay", "expected_description"),
    [
        (
            "parent_id",
            "      parent_id:\n        aliases: [curated alias]\n",
            "Generated FK comment",
        ),
        (
            "parent_id",
            """\
      parent_id:
        description: Curated parent reference
        aliases: [curated alias]
""",
            "Curated parent reference",
        ),
        (
            "id",
            "      id:\n        aliases: [curated alias]\n",
            None,
        ),
    ],
)
def test_column_overlay_merges_description_and_aliases_independently(
    tmp_path: Path,
    column_name: str,
    column_overlay: str,
    expected_description: str | None,
) -> None:
    tables_path, relationships_path = _write_semantics(
        tmp_path / "catalog" / "semantic",
        tables=f"""\
version: v0.1
tables:
  dim_parent:
    description: Curated parent description
  fact_child:
    description: Curated child description
    column_semantics:
{column_overlay}""",
    )
    curated = load_curated_semantics(
        tables_path=tables_path,
        relationships_path=relationships_path,
    )

    assembled = assemble_semantic_catalog(_generated(), curated)

    child = next(document for document in assembled.documents if document.table == "fact_child")
    column = next(column for column in child.columns if column.name == column_name)
    assert column.description == expected_description
    assert column.aliases == ["curated alias"]


@pytest.mark.parametrize(
    ("tables", "relationships", "message"),
    [
        (
            """\
version: v0.1
tables:
  dim_parent:
    description: Parent only
""",
            None,
            "coverage",
        ),
        (
            """\
version: v0.1
tables:
  dim_parent:
    description: Parent
  fact_child:
    description: Child
    column_semantics:
      missing_column:
        description: Invalid
""",
            None,
            "column",
        ),
        (
            None,
            """\
version: v0.1
relationships:
  - from_table: fact_child
    from_column: id
    to_table: dim_parent
    to_column: id
    cardinality: MANY_TO_ONE
    description: Existing columns but no FK connectivity
""",
            "connectivity",
        ),
        (
            None,
            """\
version: v0.1
relationships:
  - from_table: fact_child
    from_column: parent_id
    to_table: dim_parent
    to_column: missing_column
    cardinality: MANY_TO_ONE
    description: Missing target column
""",
            "column",
        ),
    ],
)
def test_invalid_curated_references_fail_closed(
    tmp_path: Path,
    tables: str | None,
    relationships: str | None,
    message: str,
) -> None:
    tables_path, relationships_path = _write_semantics(
        tmp_path / "catalog" / "semantic",
        tables=tables,
        relationships=relationships,
    )
    curated = load_curated_semantics(
        tables_path=tables_path,
        relationships_path=relationships_path,
    )

    with pytest.raises(SemanticCatalogError, match=message):
        assemble_semantic_catalog(_generated(), curated)


def test_composite_fk_does_not_authorize_a_partial_curated_relationship(
    tmp_path: Path,
) -> None:
    tables_path, relationships_path = _write_semantics(tmp_path / "catalog" / "semantic")
    curated = load_curated_semantics(
        tables_path=tables_path,
        relationships_path=relationships_path,
    )

    with pytest.raises(SemanticCatalogError, match="connectivity"):
        assemble_semantic_catalog(_generated_with_composite_fk(), curated)


def test_duplicate_yaml_keys_fail_closed(tmp_path: Path) -> None:
    tables_path, relationships_path = _write_semantics(
        tmp_path / "catalog" / "semantic",
        tables="""\
version: v0.1
tables:
  dim_parent:
    description: First definition
  dim_parent:
    description: Silently overriding this would be unsafe
  fact_child:
    description: Child
""",
    )

    with pytest.raises(SemanticCatalogError, match="unreadable"):
        load_curated_semantics(
            tables_path=tables_path,
            relationships_path=relationships_path,
        )


def test_semantic_revision_and_assembled_bytes_are_deterministic(tmp_path: Path) -> None:
    tables_path, relationships_path = _write_semantics(tmp_path / "catalog" / "semantic")
    first_curated = load_curated_semantics(
        tables_path=tables_path,
        relationships_path=relationships_path,
    )
    second_curated = load_curated_semantics(
        tables_path=tables_path,
        relationships_path=relationships_path,
    )
    first = assemble_semantic_catalog(_generated(), first_curated)
    second = assemble_semantic_catalog(_generated(), second_curated)
    generated_root = tmp_path / "catalog" / "generated"
    output_path = generated_root / "catalog.json"

    write_assembled_catalog(first, output_path=output_path, generated_root=generated_root)
    first_bytes = output_path.read_bytes()
    write_assembled_catalog(second, output_path=output_path, generated_root=generated_root)

    assert first_curated.semantic_revision == second_curated.semantic_revision
    assert first == second
    assert output_path.read_bytes() == first_bytes
    assert load_assembled_catalog(output_path) == first

    tampered = json.loads(first_bytes)
    tampered["documents"][0]["description"] = "tampered"
    output_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(SemanticCatalogError, match="fingerprint"):
        load_assembled_catalog(output_path)


def test_generated_fk_without_curated_relationship_does_not_infer_cardinality(
    tmp_path: Path,
) -> None:
    tables_path, relationships_path = _write_semantics(
        tmp_path / "catalog" / "semantic",
        relationships="version: v0.1\nrelationships: []\n",
    )
    curated = load_curated_semantics(
        tables_path=tables_path,
        relationships_path=relationships_path,
    )

    assembled = assemble_semantic_catalog(_generated(), curated)

    assert assembled.relationships == ()
    assert isinstance(assembled, AssembledSemanticCatalog)
