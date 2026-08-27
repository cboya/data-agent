from typing import cast

from data_agent.contracts.dialogue import DialogueAction, DialogueProposal
from data_agent.contracts.requirement import PatchOp
from data_agent.dialogue.policy import BlockingReasonCode
from data_agent.dialogue.readiness_evaluation import load_readiness_eval_suite
from data_agent.dialogue.service import DialogueEngine
from data_agent.model_runtime.ports import ChatModel


def _engine() -> DialogueEngine:
    return DialogueEngine(chat_model=cast(ChatModel, object()))


def _case(case_id: str):  # type: ignore[no-untyped-def]
    return next(case for case in load_readiness_eval_suite().cases if case.id == case_id)


def test_optional_time_candidate_does_not_invent_or_clear_scope() -> None:
    turn = _case("agg-paid-order-channel").turns[0]

    outcome = _engine().resolve_proposal(
        requirement=turn.initial_requirement_state,
        proposal=turn.provider_proposal,
        latest_user_message=turn.latest_user_message,
    )

    assert outcome.decision.action is DialogueAction.READY
    assert outcome.requirement.time_range is None
    assert outcome.decision.patch.time_range.op is PatchOp.NO_CHANGE
    assert outcome.blocking is not None
    assert [item.reason_code for item in outcome.blocking.assessments] == [
        BlockingReasonCode.OPTIONAL_TIME_ABSENT
    ]


def test_resolved_metric_candidate_preserves_the_confirmed_fact() -> None:
    turn = _case("agg-units-category").turns[0]

    outcome = _engine().resolve_proposal(
        requirement=turn.initial_requirement_state,
        proposal=turn.provider_proposal,
        latest_user_message=turn.latest_user_message,
    )

    assert outcome.decision.action is DialogueAction.READY
    assert [(str(item.term), str(item.resolved_name)) for item in outcome.requirement.metrics] == [
        ("销售件数", "unit_sales")
    ]
    assert outcome.blocking is not None
    assert outcome.blocking.assessments[0].reason_code is BlockingReasonCode.ALREADY_RESOLVED


def test_model_explanation_text_cannot_change_readiness() -> None:
    turn = _case("explicit-time-ambiguity").turns[0]
    payload = turn.provider_proposal.model_dump(mode="json")
    payload["resolution"]["reason"] = "opposite free-form claim"
    payload["resolution"]["unresolved_replace"][0]["reason"] = "not authoritative"
    changed = DialogueProposal.model_validate(payload)

    original = _engine().resolve_proposal(
        requirement=turn.initial_requirement_state,
        proposal=turn.provider_proposal,
        latest_user_message=turn.latest_user_message,
    )
    modified = _engine().resolve_proposal(
        requirement=turn.initial_requirement_state,
        proposal=changed,
        latest_user_message=turn.latest_user_message,
    )

    assert original.decision.action is DialogueAction.ASK_CLARIFICATION
    assert modified.decision.action is original.decision.action
    assert modified.requirement.metrics == original.requirement.metrics
    assert modified.requirement.dimensions == original.requirement.dimensions
    assert modified.requirement.time_range == original.requirement.time_range
    assert modified.requirement.grain == original.requirement.grain
    assert [item.field for item in modified.requirement.unresolved] == [
        item.field for item in original.requirement.unresolved
    ]
    assert modified.blocking is not None
    assert original.blocking is not None
    assert modified.blocking.assessments == original.blocking.assessments
    assert [item.subject_term for item in modified.blocking.blocking_candidates] == [
        item.subject_term for item in original.blocking.blocking_candidates
    ]


def test_unattributed_new_blocker_is_stale_not_readiness_authority() -> None:
    turn = _case("explicit-time-ambiguity").turns[0]

    outcome = _engine().resolve_proposal(
        requirement=turn.initial_requirement_state,
        proposal=turn.provider_proposal,
        latest_user_message="Show paid amount for a fixed period.",
    )

    assert outcome.decision.action is DialogueAction.READY
    assert outcome.blocking is not None
    assert outcome.blocking.assessments[0].reason_code is BlockingReasonCode.STALE_BLOCKER
