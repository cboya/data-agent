from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from data_agent.contracts import (
    Ambiguity,
    DialogueAction,
    DialogueDecision,
    MetricRequirement,
    RequirementPatch,
    RequirementState,
    RequirementStatus,
    ResolutionStatus,
    TimeRange,
)


def test_ready_requirement_rejects_blocking_ambiguity() -> None:
    with pytest.raises(ValidationError, match="blocking ambiguity"):
        RequirementState(
            version="v0.1",
            status=RequirementStatus.READY,
            unresolved=[Ambiguity(field="metric", reason="Revenue definition is unresolved")],
        )


def test_ready_requirement_accepts_only_non_blocking_ambiguity() -> None:
    state = RequirementState(
        version="v0.1",
        status=RequirementStatus.READY,
        unresolved=[
            Ambiguity(
                field="display_format",
                reason="Presentation choice does not change the query",
                blocking=False,
            )
        ],
    )

    assert state.status is RequirementStatus.READY


@pytest.mark.parametrize(
    ("action", "question"),
    [
        (DialogueAction.ASK_CLARIFICATION, None),
        (DialogueAction.ASK_CLARIFICATION, "   "),
        (DialogueAction.READY, "Which revenue definition?"),
    ],
)
def test_dialogue_action_and_question_must_be_consistent(
    action: DialogueAction, question: str | None
) -> None:
    with pytest.raises(ValidationError):
        DialogueDecision(
            version="v0.1",
            patch=RequirementPatch(),
            action=action,
            question=question,
            reason="Contract invariant test",
        )


def test_requirement_patch_exposes_operations_not_full_state_replacement() -> None:
    metric = MetricRequirement(
        term="销售额",
        resolved_name="paid_amount",
        status=ResolutionStatus.CONFIRMED,
    )
    patch = RequirementPatch(
        goal_replace="Compare paid revenue by region",
        metrics_upsert=[metric],
        filters_replace=[],
        assumptions_add=["Use successful payment amount"],
        unresolved_replace=[],
    )

    assert patch.metrics_upsert == [metric]
    assert patch.filters_replace == []
    assert patch.unresolved_replace == []
    assert "requirement" not in type(patch).model_fields

    with pytest.raises(ValidationError, match="goal"):
        RequirementPatch(goal="Replace the full state")  # type: ignore[call-arg]


def test_mutable_defaults_are_not_shared() -> None:
    first = RequirementState(version="v0.1", status=RequirementStatus.INCOMPLETE)
    second = RequirementState(version="v0.1", status=RequirementStatus.INCOMPLETE)

    first.assumptions.append("first only")

    assert second.assumptions == []


def test_time_range_rejects_naive_datetime() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        TimeRange(
            kind="ABSOLUTE",
            value="2026-08-01 through 2026-08-23",
            start=datetime(2026, 8, 1),
        )

    accepted = TimeRange(
        kind="ABSOLUTE",
        value="2026-08-01 through 2026-08-23",
        start=datetime(2026, 8, 1, tzinfo=UTC),
    )
    assert isinstance(accepted.start, datetime)
