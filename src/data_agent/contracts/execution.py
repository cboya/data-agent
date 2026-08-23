"""Guard, EXPLAIN, and bounded database execution result contracts."""

from enum import StrEnum
from typing import Any, Self

from pydantic import Field, model_validator

from data_agent.contracts.base import ContractModel, ContractVersion, NonEmptyString


class GuardStatus(StrEnum):
    PASSED = "PASSED"
    REJECTED = "REJECTED"


class SQLGuardResult(ContractModel):
    status: GuardStatus
    referenced_tables: list[NonEmptyString]
    violations: list[NonEmptyString]

    @model_validator(mode="after")
    def status_matches_violations(self) -> Self:
        if self.status is GuardStatus.PASSED and self.violations:
            raise ValueError("PASSED SQL guard cannot contain violations")
        if self.status is GuardStatus.REJECTED and not self.violations:
            raise ValueError("REJECTED SQL guard requires at least one violation")
        return self


class ExplainTableAccess(ContractModel):
    table: NonEmptyString
    access_type: NonEmptyString | None = None
    key: NonEmptyString | None = None
    estimated_rows: int | None = Field(default=None, ge=0)


class ExplainResult(ContractModel):
    accepted: bool
    accesses: list[ExplainTableAccess]
    rejection_reason: NonEmptyString | None = None

    @model_validator(mode="after")
    def accepted_matches_rejection_reason(self) -> Self:
        if self.accepted and self.rejection_reason is not None:
            raise ValueError("accepted EXPLAIN result cannot contain rejection_reason")
        if not self.accepted and self.rejection_reason is None:
            raise ValueError("rejected EXPLAIN result requires rejection_reason")
        return self


class ExecutionResult(ContractModel):
    version: ContractVersion
    columns: list[NonEmptyString]
    rows: list[list[Any]]
    returned_row_count: int = Field(ge=0)
    duration_ms: int = Field(ge=0)
    truncated: bool

    @model_validator(mode="after")
    def result_shape_is_consistent(self) -> Self:
        if self.returned_row_count != len(self.rows):
            raise ValueError("returned_row_count must equal the number of rows")
        column_count = len(self.columns)
        if any(len(row) != column_count for row in self.rows):
            raise ValueError("every result row must match the declared column count")
        return self
