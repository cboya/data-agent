"""Strict curated semantic loading and deterministic generated-metadata merge."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal, Self

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from data_agent.catalog.introspection import (
    GENERATED_CATALOG_ROOT,
    GeneratedSchemaMetadata,
)
from data_agent.contracts.base import NonEmptyString
from data_agent.contracts.catalog import (
    Cardinality,
    CatalogColumn,
    CatalogDocument,
    Relationship,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SEMANTIC_CATALOG_ROOT = REPOSITORY_ROOT / "catalog" / "semantic"
TABLES_SEMANTICS_PATH = SEMANTIC_CATALOG_ROOT / "tables.yaml"
RELATIONSHIPS_SEMANTICS_PATH = SEMANTIC_CATALOG_ROOT / "relationships.yaml"
ASSEMBLED_CATALOG_PATH = GENERATED_CATALOG_ROOT / "catalog.json"


class SemanticCatalogError(RuntimeError):
    """Curated semantics or their generated merge failed closed."""


class _UniqueKeySafeLoader(yaml.SafeLoader):  # type: ignore[misc]
    """Safe YAML loader that rejects duplicate mapping keys instead of overwriting them."""

    def construct_mapping(self, node: Any, deep: bool = False) -> dict[Any, Any]:
        self.flatten_mapping(node)
        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in mapping
            except TypeError as error:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found an unhashable mapping key",
                    key_node.start_mark,
                ) from error
            if duplicate:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found duplicate key: {key}",
                    key_node.start_mark,
                )
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


class _SemanticModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _ColumnOverlay(_SemanticModel):
    description: NonEmptyString | None = None
    aliases: tuple[NonEmptyString, ...] = ()

    @model_validator(mode="after")
    def contains_semantics(self) -> Self:
        if self.description is None and not self.aliases:
            raise ValueError("curated column semantics cannot be empty")
        return self


class _TableOverlay(_SemanticModel):
    aliases: tuple[NonEmptyString, ...] = ()
    description: NonEmptyString
    business_rules: tuple[NonEmptyString, ...] = ()
    column_semantics: dict[NonEmptyString, _ColumnOverlay] = Field(default_factory=dict)
    typical_use_cases: tuple[NonEmptyString, ...] = ()


class _TablesFile(_SemanticModel):
    version: Literal["v0.1"]
    tables: dict[NonEmptyString, _TableOverlay] = Field(min_length=1)


class _RelationshipOverlay(_SemanticModel):
    from_table: NonEmptyString
    from_column: NonEmptyString
    to_table: NonEmptyString
    to_column: NonEmptyString
    cardinality: Cardinality
    description: NonEmptyString


class _RelationshipsFile(_SemanticModel):
    version: Literal["v0.1"]
    relationships: tuple[_RelationshipOverlay, ...]


class CuratedColumnSemantics(_SemanticModel):
    column: NonEmptyString
    description: NonEmptyString | None
    aliases: tuple[NonEmptyString, ...]


class CuratedTableSemantics(_SemanticModel):
    table: NonEmptyString
    aliases: tuple[NonEmptyString, ...]
    description: NonEmptyString
    business_rules: tuple[NonEmptyString, ...]
    columns: tuple[CuratedColumnSemantics, ...]
    typical_use_cases: tuple[NonEmptyString, ...]


class CuratedRelationshipSemantics(_RelationshipOverlay):
    pass


def _canonical_payload(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_payload(payload).encode("utf-8")).hexdigest()


def _relationship_key(
    relationship: CuratedRelationshipSemantics | Relationship,
) -> tuple[str, str, str, str]:
    return (
        str(relationship.from_table),
        str(relationship.from_column),
        str(relationship.to_table),
        str(relationship.to_column),
    )


class CuratedSemanticCatalog(_SemanticModel):
    version: Literal["v0.1"] = "v0.1"
    tables: tuple[CuratedTableSemantics, ...] = Field(min_length=1)
    relationships: tuple[CuratedRelationshipSemantics, ...]
    semantic_revision: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def build(cls, tables_file: _TablesFile, relationships_file: _RelationshipsFile) -> Self:
        tables = tuple(
            CuratedTableSemantics(
                table=table,
                aliases=overlay.aliases,
                description=overlay.description,
                business_rules=overlay.business_rules,
                columns=tuple(
                    CuratedColumnSemantics(
                        column=column,
                        description=column_overlay.description,
                        aliases=column_overlay.aliases,
                    )
                    for column, column_overlay in sorted(overlay.column_semantics.items())
                ),
                typical_use_cases=overlay.typical_use_cases,
            )
            for table, overlay in sorted(tables_file.tables.items())
        )
        relationships = tuple(
            CuratedRelationshipSemantics.model_validate(relationship.model_dump())
            for relationship in sorted(
                relationships_file.relationships,
                key=lambda relationship: (
                    str(relationship.from_table),
                    str(relationship.from_column),
                    str(relationship.to_table),
                    str(relationship.to_column),
                ),
            )
        )
        payload: dict[str, Any] = {
            "version": "v0.1",
            "tables": [table.model_dump(mode="json") for table in tables],
            "relationships": [
                relationship.model_dump(mode="json") for relationship in relationships
            ],
        }
        return cls(**payload, semantic_revision=_fingerprint(payload))

    @model_validator(mode="after")
    def normalized_semantics_are_ordered_and_untampered(self) -> Self:
        table_names = [str(table.table) for table in self.tables]
        if table_names != sorted(table_names) or len(table_names) != len(set(table_names)):
            raise ValueError("curated tables must have unique sorted names")
        for table in self.tables:
            column_names = [str(column.column) for column in table.columns]
            if column_names != sorted(column_names) or len(column_names) != len(set(column_names)):
                raise ValueError("curated columns must have unique sorted names")
        relationship_keys = [_relationship_key(relationship) for relationship in self.relationships]
        if relationship_keys != sorted(relationship_keys) or len(relationship_keys) != len(
            set(relationship_keys)
        ):
            raise ValueError("curated relationships must have unique sorted endpoints")
        payload = self.model_dump(mode="json", exclude={"semantic_revision"})
        if self.semantic_revision != _fingerprint(payload):
            raise ValueError("semantic revision does not match canonical curated semantics")
        return self


def _load_yaml(path: Path) -> object:
    try:
        return yaml.load(
            path.read_text(encoding="utf-8"),
            Loader=_UniqueKeySafeLoader,
        )
    except (OSError, yaml.YAMLError) as error:
        raise SemanticCatalogError(f"curated semantic file is unreadable: {path.name}") from error


def load_curated_semantics(
    *,
    tables_path: Path = TABLES_SEMANTICS_PATH,
    relationships_path: Path = RELATIONSHIPS_SEMANTICS_PATH,
) -> CuratedSemanticCatalog:
    """Safely parse and normalize both repository-curated semantic sources."""
    try:
        tables_file = _TablesFile.model_validate(_load_yaml(tables_path))
        relationships_file = _RelationshipsFile.model_validate(_load_yaml(relationships_path))
        return CuratedSemanticCatalog.build(tables_file, relationships_file)
    except ValidationError as error:
        raise SemanticCatalogError("curated semantic files failed validation") from error


def _generated_connectivity(
    generated: GeneratedSchemaMetadata,
) -> set[tuple[str, str, str, str]]:
    connectivity: set[tuple[str, str, str, str]] = set()
    for table in generated.tables:
        for foreign_key in table.foreign_keys:
            connectivity.update(
                (table.name, column, foreign_key.referenced_table, referenced_column)
                for column, referenced_column in zip(
                    foreign_key.columns,
                    foreign_key.referenced_columns,
                    strict=True,
                )
            )
    return connectivity


class AssembledSemanticCatalog(_SemanticModel):
    version: Literal["v0.1"] = "v0.1"
    generated_metadata_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    documents: tuple[CatalogDocument, ...] = Field(min_length=1)
    relationships: tuple[Relationship, ...]
    catalog_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def build(
        cls,
        *,
        generated_metadata_fingerprint: str,
        semantic_revision: str,
        documents: tuple[CatalogDocument, ...],
        relationships: tuple[Relationship, ...],
    ) -> Self:
        payload: dict[str, Any] = {
            "version": "v0.1",
            "generated_metadata_fingerprint": generated_metadata_fingerprint,
            "semantic_revision": semantic_revision,
            "documents": [document.model_dump(mode="json") for document in documents],
            "relationships": [
                relationship.model_dump(mode="json") for relationship in relationships
            ],
        }
        return cls(**payload, catalog_fingerprint=_fingerprint(payload))

    @model_validator(mode="after")
    def assembled_catalog_is_consistent_and_untampered(self) -> Self:
        table_names = [str(document.table) for document in self.documents]
        if table_names != sorted(table_names) or len(table_names) != len(set(table_names)):
            raise ValueError("assembled catalog documents must have unique sorted tables")
        document_columns = {
            str(document.table): {str(column.name) for column in document.columns}
            for document in self.documents
        }
        for document in self.documents:
            if document.generated_metadata_fingerprint != self.generated_metadata_fingerprint:
                raise ValueError("catalog document has the wrong generated metadata fingerprint")
            if document.semantic_revision != self.semantic_revision:
                raise ValueError("catalog document has the wrong semantic revision")
        relationship_keys = [_relationship_key(relationship) for relationship in self.relationships]
        if relationship_keys != sorted(relationship_keys) or len(relationship_keys) != len(
            set(relationship_keys)
        ):
            raise ValueError("assembled relationships must have unique sorted endpoints")
        for relationship in self.relationships:
            if not relationship.curated:
                raise ValueError("assembled relationship cardinality must be curated")
            from_columns = document_columns.get(str(relationship.from_table))
            to_columns = document_columns.get(str(relationship.to_table))
            if from_columns is None or to_columns is None:
                raise ValueError("assembled relationship references an unknown table")
            if (
                str(relationship.from_column) not in from_columns
                or str(relationship.to_column) not in to_columns
            ):
                raise ValueError("assembled relationship references an unknown column")
        payload = self.model_dump(mode="json", exclude={"catalog_fingerprint"})
        if self.catalog_fingerprint != _fingerprint(payload):
            raise ValueError("assembled catalog fingerprint does not match canonical content")
        return self


def assemble_semantic_catalog(
    generated: GeneratedSchemaMetadata,
    curated: CuratedSemanticCatalog,
) -> AssembledSemanticCatalog:
    """Merge trusted generated facts with validated repository-curated semantic authority."""
    generated_tables = {table.name: table for table in generated.tables}
    curated_tables = {str(table.table): table for table in curated.tables}
    if generated_tables.keys() != curated_tables.keys():
        missing = sorted(generated_tables.keys() - curated_tables.keys())
        unexpected = sorted(curated_tables.keys() - generated_tables.keys())
        raise SemanticCatalogError(
            f"curated table coverage mismatch: missing={missing}, unexpected={unexpected}"
        )

    documents: list[CatalogDocument] = []
    for table_name in sorted(generated_tables):
        generated_table = generated_tables[table_name]
        table_semantics = curated_tables[table_name]
        column_semantics = {str(column.column): column for column in table_semantics.columns}
        generated_column_names = {column.name for column in generated_table.columns}
        unknown_columns = sorted(column_semantics.keys() - generated_column_names)
        if unknown_columns:
            raise SemanticCatalogError(
                f"curated column references are invalid for {table_name}: {unknown_columns}"
            )
        columns: list[CatalogColumn] = []
        for generated_column in generated_table.columns:
            overlay = column_semantics.get(generated_column.name)
            description = (
                overlay.description
                if overlay is not None and overlay.description is not None
                else generated_column.comment
            )
            columns.append(
                CatalogColumn(
                    name=generated_column.name,
                    data_type=generated_column.data_type,
                    description=description,
                    aliases=list(overlay.aliases) if overlay is not None else [],
                    nullable=generated_column.nullable,
                    primary_key=generated_column.primary_key,
                )
            )
        documents.append(
            CatalogDocument(
                version="v0.1",
                table=table_name,
                aliases=list(table_semantics.aliases),
                description=table_semantics.description,
                business_rules=list(table_semantics.business_rules),
                columns=columns,
                typical_use_cases=list(table_semantics.typical_use_cases),
                generated_metadata_fingerprint=generated.fingerprint,
                semantic_revision=curated.semantic_revision,
            )
        )

    connectivity = _generated_connectivity(generated)
    document_columns = {
        str(document.table): {str(column.name) for column in document.columns}
        for document in documents
    }
    relationships: list[Relationship] = []
    for relationship in curated.relationships:
        key = _relationship_key(relationship)
        from_columns = document_columns.get(key[0])
        to_columns = document_columns.get(key[2])
        if from_columns is None or to_columns is None:
            raise SemanticCatalogError("curated relationship references an unknown table")
        if key[1] not in from_columns or key[3] not in to_columns:
            raise SemanticCatalogError("curated relationship references an unknown column")
        if key not in connectivity:
            raise SemanticCatalogError(
                "curated relationship lacks generated foreign-key connectivity evidence"
            )
        relationships.append(
            Relationship(
                version="v0.1",
                from_table=relationship.from_table,
                from_column=relationship.from_column,
                to_table=relationship.to_table,
                to_column=relationship.to_column,
                cardinality=relationship.cardinality,
                description=relationship.description,
                curated=True,
            )
        )

    try:
        return AssembledSemanticCatalog.build(
            generated_metadata_fingerprint=generated.fingerprint,
            semantic_revision=curated.semantic_revision,
            documents=tuple(documents),
            relationships=tuple(relationships),
        )
    except ValidationError as error:
        raise SemanticCatalogError("assembled semantic catalog failed validation") from error


def _ensure_generated_path(output_path: Path, generated_root: Path) -> None:
    resolved_output = output_path.resolve()
    resolved_root = generated_root.resolve()
    if resolved_root.name != "generated" or resolved_root.parent.name != "catalog":
        raise SemanticCatalogError("generated catalog root must be catalog/generated")
    if not resolved_output.is_relative_to(resolved_root) or resolved_output == resolved_root:
        raise SemanticCatalogError("assembled catalog output must stay beneath catalog/generated")


def write_assembled_catalog(
    catalog: AssembledSemanticCatalog,
    *,
    output_path: Path = ASSEMBLED_CATALOG_PATH,
    generated_root: Path = GENERATED_CATALOG_ROOT,
) -> Path:
    """Atomically write the deterministic generated-plus-curated assembly."""
    _ensure_generated_path(output_path, generated_root)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = (
        json.dumps(
            catalog.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    temporary_path = output_path.with_name(f".{output_path.name}.tmp")
    try:
        temporary_path.write_text(serialized, encoding="utf-8")
        temporary_path.replace(output_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return output_path


def load_assembled_catalog(
    path: Path = ASSEMBLED_CATALOG_PATH,
) -> AssembledSemanticCatalog:
    """Load assembled output and reject content that no longer matches its fingerprint."""
    try:
        return AssembledSemanticCatalog.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise SemanticCatalogError(
            "assembled catalog is missing, invalid, or fingerprint-drifted"
        ) from error


def build_semantic_catalog(
    generated: GeneratedSchemaMetadata,
    *,
    tables_path: Path = TABLES_SEMANTICS_PATH,
    relationships_path: Path = RELATIONSHIPS_SEMANTICS_PATH,
    output_path: Path = ASSEMBLED_CATALOG_PATH,
    generated_root: Path = GENERATED_CATALOG_ROOT,
) -> AssembledSemanticCatalog:
    """Load curated authority, merge with generated facts, and persist rebuildable output."""
    curated = load_curated_semantics(
        tables_path=tables_path,
        relationships_path=relationships_path,
    )
    assembled = assemble_semantic_catalog(generated, curated)
    write_assembled_catalog(
        assembled,
        output_path=output_path,
        generated_root=generated_root,
    )
    return assembled
