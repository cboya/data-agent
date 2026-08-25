"""Harness-owned validation of model-proposed dialogue actions."""

from __future__ import annotations

from dataclasses import dataclass

from data_agent.contracts.dialogue import DialogueAction, DialogueDecision
from data_agent.contracts.requirement import RequirementState, RequirementStatus
from data_agent.dialogue.errors import DialoguePolicyError


@dataclass(frozen=True)
class DialogueOutcome:
    decision: DialogueDecision
    requirement: RequirementState


class DialoguePolicy:
    def apply(
        self,
        *,
        decision: DialogueDecision,
        merged: RequirementState,
    ) -> DialogueOutcome:
        blocking = [value for value in merged.unresolved if value.blocking]
        if decision.action is DialogueAction.ASK_CLARIFICATION:
            if not blocking:
                raise DialoguePolicyError(
                    "ASK_CLARIFICATION requires a blocking ambiguity in merged state"
                )
            status = RequirementStatus.CLARIFYING
        elif decision.action is DialogueAction.READY:
            if blocking:
                raise DialoguePolicyError("READY is forbidden while blocking ambiguity remains")
            status = RequirementStatus.READY
        else:
            if not blocking:
                raise DialoguePolicyError("CANNOT_RESOLVE requires a blocking ambiguity")
            status = RequirementStatus.FAILED

        requirement = RequirementState.model_validate(
            {**merged.model_dump(mode="python"), "status": status}
        )
        return DialogueOutcome(decision=decision, requirement=requirement)
