"""Conversation session contract."""

from enum import StrEnum
from typing import Self

from pydantic import model_validator

from data_agent.contracts.base import AwareDateTime, ContractModel, NonEmptyString
from data_agent.contracts.requirement import RequirementState


class SessionStatus(StrEnum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Session(ContractModel):
    id: NonEmptyString
    status: SessionStatus
    requirement: RequirementState
    created_at: AwareDateTime
    updated_at: AwareDateTime

    @model_validator(mode="after")
    def timestamps_are_ordered(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        return self
