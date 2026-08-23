"""Run data contract; transition behavior is owned by M3."""

from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from data_agent.contracts.base import AwareDateTime, ContractModel, NonEmptyString


class RunStatus(StrEnum):
    RECEIVED = "RECEIVED"
    UNDERSTANDING = "UNDERSTANDING"
    CLARIFYING = "CLARIFYING"
    RETRIEVING = "RETRIEVING"
    PLANNING = "PLANNING"
    VALIDATING = "VALIDATING"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    SYNTHESIZING = "SYNTHESIZING"
    COMPLETED = "COMPLETED"
    POLICY_DENIED = "POLICY_DENIED"
    QUERY_TOO_EXPENSIVE = "QUERY_TOO_EXPENSIVE"
    REPAIR_EXHAUSTED = "REPAIR_EXHAUSTED"
    FAILED = "FAILED"


class Run(ContractModel):
    id: NonEmptyString
    session_id: NonEmptyString
    status: RunStatus
    repair_count: int = Field(default=0, ge=0)
    started_at: AwareDateTime
    completed_at: AwareDateTime | None = None
    error_code: NonEmptyString | None = None

    @model_validator(mode="after")
    def timestamps_are_ordered(self) -> Self:
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("completed_at must not precede started_at")
        return self
