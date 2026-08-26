"""Provider-facing M13 grammar normalized into public QueryPlan v0.1."""

from typing import Literal

from pydantic import Field

from data_agent.contracts.base import ContractModel, NonEmptyString
from data_agent.contracts.query import ExpectedColumn, QueryPlan


class RepairPlanProposal(ContractModel):
    """Narrow provider schema where M12-required output shape cannot be omitted."""

    version: Literal["v0.1"] = "v0.1"
    intent: NonEmptyString
    tables: list[NonEmptyString] = Field(min_length=1)
    assumptions: list[NonEmptyString] = Field(default_factory=list)
    sql: NonEmptyString
    expected_columns: list[ExpectedColumn] = Field(min_length=1)
    explanation: NonEmptyString | None = None

    def to_query_plan(self) -> QueryPlan:
        return QueryPlan.model_validate(self.model_dump(mode="json"))
