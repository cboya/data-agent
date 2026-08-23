"""Generated-plus-curated catalog and relationship contracts."""

from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from data_agent.contracts.base import ContractModel, ContractVersion, NonEmptyString


class CatalogColumn(ContractModel):
    name: NonEmptyString
    data_type: NonEmptyString
    description: NonEmptyString | None = None
    aliases: list[NonEmptyString] = Field(default_factory=list)
    nullable: bool | None = None
    primary_key: bool = False


class CatalogDocument(ContractModel):
    version: ContractVersion
    table: NonEmptyString
    aliases: list[NonEmptyString] = Field(default_factory=list)
    description: NonEmptyString
    business_rules: list[NonEmptyString] = Field(default_factory=list)
    columns: list[CatalogColumn] = Field(min_length=1)
    typical_use_cases: list[NonEmptyString] = Field(default_factory=list)
    generated_metadata_fingerprint: NonEmptyString
    semantic_revision: NonEmptyString

    @model_validator(mode="after")
    def column_names_are_unique(self) -> Self:
        names = [column.name for column in self.columns]
        if len(names) != len(set(names)):
            raise ValueError("catalog column names must be unique")
        return self


class Cardinality(StrEnum):
    ONE_TO_ONE = "ONE_TO_ONE"
    ONE_TO_MANY = "ONE_TO_MANY"
    MANY_TO_ONE = "MANY_TO_ONE"
    MANY_TO_MANY = "MANY_TO_MANY"


class Relationship(ContractModel):
    version: ContractVersion
    from_table: NonEmptyString
    from_column: NonEmptyString
    to_table: NonEmptyString
    to_column: NonEmptyString
    cardinality: Cardinality
    description: NonEmptyString
    curated: bool
