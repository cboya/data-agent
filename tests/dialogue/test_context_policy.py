import json

import pytest

from data_agent.contracts.dialogue import DialogueAction, DialogueDecision
from data_agent.contracts.requirement import (
    Ambiguity,
    RequirementPatch,
    RequirementState,
    RequirementStatus,
)
from data_agent.dialogue.context import DialogueContextBuilder
from data_agent.dialogue.errors import DialogueContextError, DialoguePolicyError
from data_agent.dialogue.policy import DialoguePolicy
from tests.dialogue.factories import empty_requirement


def _decision(action: DialogueAction, *, question: str | None = None) -> DialogueDecision:
    unresolved = (
        [Ambiguity(field="metric", reason="metric changes the result")]
        if action is not DialogueAction.READY
        else []
    )
    return DialogueDecision.model_validate(
        {
            "version": "v0.1",
            "patch": RequirementPatch(
                version="v0.2",
                unresolved_replace=unresolved,
            ).model_dump(mode="json"),
            "action": action,
            "question": question,
            "reason": "test decision",
        }
    )


def test_context_contains_only_state_last_clarification_and_latest_message() -> None:
    messages = DialogueContextBuilder().build(
        requirement=empty_requirement(),
        last_assistant_clarification="Which metric?",
        latest_user_message="订单量",
    )

    assert [message["role"] for message in messages] == ["system", "user"]
    payload = json.loads(messages[1]["content"])
    assert payload == {
        "current_requirement_state": empty_requirement().model_dump(mode="json"),
        "last_assistant_clarification": "Which metric?",
        "latest_user_message": "订单量",
    }


def test_context_fails_instead_of_silently_truncating_latest_message() -> None:
    with pytest.raises(DialogueContextError, match="exceeds"):
        DialogueContextBuilder(max_user_characters=4).build(
            requirement=empty_requirement(),
            latest_user_message="too long",
        )


def test_policy_accepts_clarification_only_for_blocking_ambiguity() -> None:
    blocking = RequirementState(
        version="v0.1",
        unresolved=[Ambiguity(field="metric", reason="metric changes the result")],
        status=RequirementStatus.INCOMPLETE,
    )
    outcome = DialoguePolicy().apply(
        decision=_decision(DialogueAction.ASK_CLARIFICATION, question="Which metric?"),
        merged=blocking,
    )

    assert outcome.requirement.status is RequirementStatus.CLARIFYING

    with pytest.raises(DialoguePolicyError, match="requires a blocking"):
        DialoguePolicy().apply(
            decision=_decision(DialogueAction.ASK_CLARIFICATION, question="Sort order?"),
            merged=empty_requirement(),
        )


def test_policy_rejects_ready_while_blocking_ambiguity_remains() -> None:
    blocking = RequirementState(
        version="v0.1",
        unresolved=[Ambiguity(field="time_range", reason="time changes the result")],
        status=RequirementStatus.INCOMPLETE,
    )

    with pytest.raises(DialoguePolicyError, match="READY"):
        DialoguePolicy().apply(
            decision=_decision(DialogueAction.READY),
            merged=blocking,
        )

    ready = DialoguePolicy().apply(
        decision=_decision(DialogueAction.READY),
        merged=empty_requirement(),
    )
    assert ready.requirement.status is RequirementStatus.READY
