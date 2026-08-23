"""Typed query-planning contracts."""

from pydantic import Field

from data_agent.contracts.base import ContractModel, ContractVersion, NonEmptyString


class ExpectedColumn(ContractModel):
    name: NonEmptyString
    semantic_role: NonEmptyString | None = None


class QueryPlan(ContractModel):
    version: ContractVersion
    intent: NonEmptyString
    tables: list[NonEmptyString] = Field(min_length=1)
    assumptions: list[NonEmptyString] = Field(default_factory=list)
    sql: NonEmptyString
    expected_columns: list[ExpectedColumn] = Field(default_factory=list)
    explanation: NonEmptyString | None = None
