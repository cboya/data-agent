"""Validated decision proposed by the requirement-understanding model."""

from enum import StrEnum
from typing import Self

from pydantic import model_validator

from data_agent.contracts.base import ContractModel, ContractVersion, NonEmptyString
from data_agent.contracts.requirement import RequirementPatch


class DialogueAction(StrEnum):
    ASK_CLARIFICATION = "ASK_CLARIFICATION"
    READY = "READY"
    CANNOT_RESOLVE = "CANNOT_RESOLVE"


class DialogueDecision(ContractModel):
    version: ContractVersion
    patch: RequirementPatch
    action: DialogueAction
    question: str | None = None
    reason: NonEmptyString

    @model_validator(mode="after")
    def action_matches_question(self) -> Self:
        if self.action is DialogueAction.ASK_CLARIFICATION and (
            self.question is None or not self.question.strip()
        ):
            raise ValueError("ASK_CLARIFICATION requires a non-empty question")
        if self.action is DialogueAction.READY and self.question is not None:
            raise ValueError("READY requires question to be None")
        return self
