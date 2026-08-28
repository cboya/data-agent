"""Deterministic M8 dialogue fixtures and provider-neutral test doubles."""

from __future__ import annotations

import json
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
        payload = proposal.model_dump(mode="json")
        latest_user_message = str(json.loads(messages[-1]["content"])["latest_user_message"])
        first_blocking: dict[str, object] | None = None
        for ambiguity in payload["resolution"]["unresolved_replace"]:
            if ambiguity["blocking"]:
                if first_blocking is None:
                    first_blocking = ambiguity
                ambiguity["subject_term"] = latest_user_message
                if len(ambiguity["options"]) < 2:
                    ambiguity["options"] = ["interpretation_a", "interpretation_b"]
                if ambiguity["field"] in {"metric", "dimension"}:
                    collection = (
                        payload["patch"]["metrics_upsert"]
                        if ambiguity["field"] == "metric"
                        else payload["patch"]["dimensions_upsert"]
                    )
                    item = {
                        "term": latest_user_message,
                        "resolved_name": None,
                        "status": "UNRESOLVED",
                    }
                    if ambiguity["field"] == "metric":
                        item["definition"] = None
                    collection.append(item)
        payload["question_target"] = (
            {
                "field": first_blocking["field"],
                "subject_term": latest_user_message,
            }
            if decision.action.value == "ASK_CLARIFICATION" and first_blocking is not None
            else None
        )
        return response_type.model_validate(payload)


class FixedProposalModel:
    def __init__(self, *proposals: DialogueProposal) -> None:
        self._proposals = list(proposals)
        self.calls: list[tuple[list[dict[str, str]], type[BaseModel], str]] = []

    async def structured[StructuredResultT: BaseModel](
        self,
        *,
        messages: list[dict[str, str]],
        response_type: type[StructuredResultT],
        purpose: str,
    ) -> StructuredResultT:
        self.calls.append((messages, response_type, purpose))
        if not self._proposals:
            raise AssertionError("fixed proposal model has no remaining proposal")
        proposal = self._proposals.pop(0)
        return response_type.model_validate(proposal.model_dump(mode="json"))


def model_dump(value: BaseModel) -> dict[str, Any]:
    return value.model_dump(mode="python")
