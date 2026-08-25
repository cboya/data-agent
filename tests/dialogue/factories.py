"""Deterministic M8 dialogue fixtures and provider-neutral test doubles."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from data_agent.contracts.dialogue import DialogueDecision, DialogueProposal
from data_agent.contracts.requirement import RequirementState, RequirementStatus


def empty_requirement() -> RequirementState:
    return RequirementState(version="v0.1", status=RequirementStatus.INCOMPLETE)


class FixedDialogueModel:
    def __init__(self, *decisions: DialogueDecision) -> None:
        self._decisions = list(decisions)
        self.calls: list[tuple[list[dict[str, str]], type[BaseModel], str]] = []

    async def structured[StructuredResultT: BaseModel](
        self,
        *,
        messages: list[dict[str, str]],
        response_type: type[StructuredResultT],
        purpose: str,
    ) -> StructuredResultT:
        self.calls.append((messages, response_type, purpose))
        if not self._decisions:
            raise AssertionError("fixed dialogue model has no remaining decision")
        decision = self._decisions.pop(0)
        proposal = DialogueProposal.from_decision(decision)
        return response_type.model_validate(proposal.model_dump(mode="json"))


def model_dump(value: BaseModel) -> dict[str, Any]:
    return value.model_dump(mode="python")
