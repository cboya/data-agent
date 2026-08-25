import asyncio
import json

import pytest

from data_agent.contracts.dialogue import DialogueAction, DialogueDecision, DialogueProposal
from data_agent.contracts.requirement import (
    Ambiguity,
    MetricRequirement,
    PatchOp,
    RequirementPatch,
    RequirementState,
    RequirementStatus,
    ResolutionStatus,
    SetScalarPatch,
    TimeRange,
)
from data_agent.dialogue.context import DialogueContextBuilder
from data_agent.dialogue.errors import DialogueContextError, DialoguePolicyError
from data_agent.dialogue.policy import DialoguePolicy
from data_agent.dialogue.service import DialogueEngine
from tests.dialogue.factories import FixedProposalModel, empty_requirement


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


def _proposal(
    *,
    patch: RequirementPatch,
    action: str,
    unresolved: list[dict[str, object]],
    question: str | None,
) -> DialogueProposal:
    patch_payload = patch.model_dump(mode="json")
    patch_payload.update(
        grain=(str(patch.grain.value) if patch.grain.op is PatchOp.SET else patch.grain.op.value),
        comparison=(
            str(patch.comparison.value)
            if patch.comparison.op is PatchOp.SET
            else patch.comparison.op.value
        ),
        unresolved_replace=None,
    )
    return DialogueProposal.model_validate(
        {
            "version": "v0.1",
            "patch": patch_payload,
            "resolution": {
                "action": action,
                "unresolved_replace": unresolved,
                "question": question,
                "reason": "bounded-context collection continuity regression",
            },
        }
    )


def test_resolved_collection_sibling_survives_bounded_clarification_turns() -> None:
    first_user_message = "最近30天看实际支付金额和销售情况"
    first = _proposal(
        patch=RequirementPatch(
            version="v0.2",
            time_range=SetScalarPatch(
                op=PatchOp.SET,
                value=TimeRange(kind="RELATIVE", value="last_30_days"),
            ),
            metrics_upsert=[
                MetricRequirement(
                    term="实际支付金额",
                    resolved_name="paid_amount",
                    status=ResolutionStatus.CONFIRMED,
                )
            ],
        ),
        action="ASK_CLARIFICATION",
        unresolved=[
            {
                "field": "metric",
                "subject_term": "销售情况",
                "reason": "销售情况可能表示多个指标",
                "options": ["paid_amount", "order_count", "gmv"],
                "blocking": True,
            }
        ],
        question="销售情况是指实际支付金额、订单量还是 GMV?",
    )
    second = _proposal(
        patch=RequirementPatch(
            version="v0.2",
            metrics_upsert=[
                MetricRequirement(
                    term="销售指 GMV",
                    resolved_name="gmv",
                    status=ResolutionStatus.CONFIRMED,
                )
            ],
        ),
        action="READY",
        unresolved=[],
        question=None,
    )
    model = FixedProposalModel(first, second)
    engine = DialogueEngine(chat_model=model)

    first_outcome = asyncio.run(
        engine.understand(
            requirement=empty_requirement(),
            latest_user_message=first_user_message,
        )
    )
    second_outcome = asyncio.run(
        engine.understand(
            requirement=first_outcome.requirement,
            latest_user_message="销售指 GMV",
            last_assistant_clarification=first_outcome.decision.question,
        )
    )

    assert first_outcome.requirement.status is RequirementStatus.CLARIFYING
    assert [str(item.resolved_name) for item in first_outcome.requirement.metrics] == [
        "paid_amount"
    ]
    assert first_outcome.requirement.time_range is not None
    assert first_outcome.requirement.time_range.value == "last_30_days"
    assert second_outcome.requirement.status is RequirementStatus.READY
    assert [str(item.resolved_name) for item in second_outcome.requirement.metrics] == [
        "paid_amount",
        "gmv",
    ]
    assert second_outcome.requirement.time_range is not None
    assert second_outcome.requirement.time_range.value == "last_30_days"

    second_context = json.loads(model.calls[1][0][1]["content"])
    assert second_context["latest_user_message"] == "销售指 GMV"
    assert first_user_message not in model.calls[1][0][1]["content"]
    assert [
        item["resolved_name"] for item in second_context["current_requirement_state"]["metrics"]
    ] == ["paid_amount"]


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
