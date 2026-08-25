from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from data_agent.contracts import (
    Ambiguity,
    ClearScalarPatch,
    DialogueAction,
    DialogueDecision,
    DimensionRequirement,
    FilterRequirement,
    MetricRequirement,
    NoChangeScalarPatch,
    PatchOp,
    RequirementPatch,
    RequirementState,
    RequirementStatus,
    ResolutionStatus,
    ScalarPatch,
    SetScalarPatch,
    TimeRange,
)
from data_agent.contracts.dialogue import DialogueProposal


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
        DialogueDecision.model_validate(
            {
                "version": "v0.1",
                "patch": RequirementPatch(version="v0.2").model_dump(mode="json"),
                "action": action,
                "question": question,
                "reason": "Contract invariant test",
            }
        )


def test_requirement_patch_exposes_operations_not_full_state_replacement() -> None:
    metric = MetricRequirement(
        term="销售额",
        resolved_name="paid_amount",
        status=ResolutionStatus.CONFIRMED,
    )
    patch = RequirementPatch(
        version="v0.2",
        goal=SetScalarPatch(
            op=PatchOp.SET,
            value="Compare paid revenue by region",
        ),
        metrics_upsert=[metric],
        filters_replace=[],
        assumptions_add=["Use successful payment amount"],
        unresolved_replace=[],
    )

    assert patch.metrics_upsert == [metric]
    assert patch.goal.value == "Compare paid revenue by region"
    assert patch.filters_replace == []
    assert patch.unresolved_replace == []
    assert "requirement" not in type(patch).model_fields

    with pytest.raises(ValidationError, match="goal"):
        RequirementPatch(
            version="v0.2",
            goal="Replace the full state",  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"op": "SET"},
        {"op": "CLEAR", "value": "day"},
        {"op": "NO_CHANGE", "value": "day"},
    ],
)
def test_scalar_patch_operations_fail_closed(values: dict[str, object]) -> None:
    from pydantic import TypeAdapter

    with pytest.raises(ValidationError):
        TypeAdapter(ScalarPatch[str]).validate_python(values)


def test_scalar_patch_json_round_trip_preserves_mutation_intent() -> None:
    patch = RequirementPatch(
        version="v0.2",
        grain=ClearScalarPatch(op=PatchOp.CLEAR),
        limit=SetScalarPatch(op=PatchOp.SET, value=25),
    )

    restored = RequirementPatch.model_validate_json(patch.model_dump_json())

    assert restored == patch
    assert restored.goal.op is PatchOp.NO_CHANGE
    assert restored.grain.op is PatchOp.CLEAR
    assert restored.limit.op is PatchOp.SET
    assert isinstance(restored.goal, NoChangeScalarPatch)


def test_metric_correction_operations_reject_conflicting_identity() -> None:
    metric = MetricRequirement(
        term="实际支付金额",
        resolved_name="paid_amount",
        status=ResolutionStatus.CONFIRMED,
    )

    with pytest.raises(ValidationError, match="removed and upserted"):
        RequirementPatch(
            version="v0.2",
            metrics_remove=["paid_amount"],
            metrics_upsert=[metric],
        )


def test_model_proposal_suppresses_only_matching_metric_subject() -> None:
    payload = RequirementPatch(
        version="v0.2",
        time_range=SetScalarPatch(
            op=PatchOp.SET,
            value=TimeRange(kind="RELATIVE", value="last_30_days"),
        ),
        metrics_upsert=[
            MetricRequirement(
                term="paid amount",
                resolved_name="paid_amount",
                status=ResolutionStatus.CONFIRMED,
            ),
            MetricRequirement(
                term="sales",
                resolved_name="gmv",
                status=ResolutionStatus.CONFIRMED,
            ),
        ],
    ).model_dump(mode="json")
    payload.update(
        grain="NO_CHANGE",
        comparison="NO_CHANGE",
        unresolved_replace=None,
    )
    proposal = DialogueProposal.model_validate(
        {
            "version": "v0.1",
            "patch": payload,
            "resolution": {
                "action": "ASK_CLARIFICATION",
                "unresolved_replace": [
                    {
                        "field": "metric",
                        "subject_term": "sales",
                        "reason": "sales is ambiguous",
                        "blocking": True,
                    },
                    {
                        "field": "time_range",
                        "subject_term": "recent",
                        "reason": "recent is ambiguous",
                        "blocking": True,
                    },
                ],
                "question": "Which metric?",
                "reason": "metric and time range are blocking",
            },
        }
    )

    decision = proposal.to_decision()

    assert [str(item.resolved_name) for item in decision.patch.metrics_upsert] == ["paid_amount"]
    assert decision.patch.time_range.op is PatchOp.NO_CHANGE
    assert {str(item.field) for item in decision.patch.unresolved_replace} == {
        "metric",
        "time_range",
    }
    assert all(not hasattr(item, "subject_term") for item in decision.patch.unresolved_replace)


def test_model_proposal_preserves_unrelated_dimension_subject() -> None:
    payload = RequirementPatch(
        version="v0.2",
        dimensions_upsert=[
            DimensionRequirement(
                term="Region",
                resolved_name="region",
                status=ResolutionStatus.CONFIRMED,
            ),
            DimensionRequirement(
                term="Location",
                resolved_name="channel",
                status=ResolutionStatus.CONFIRMED,
            ),
        ],
    ).model_dump(mode="json")
    payload.update(grain="NO_CHANGE", comparison="NO_CHANGE", unresolved_replace=None)
    proposal = DialogueProposal.model_validate(
        {
            "version": "v0.1",
            "patch": payload,
            "resolution": {
                "action": "ASK_CLARIFICATION",
                "unresolved_replace": [
                    {
                        "field": "dimension",
                        "subject_term": "  location  ",
                        "reason": "location is ambiguous",
                        "blocking": True,
                    }
                ],
                "question": "Which location dimension?",
                "reason": "one dimension subject is blocking",
            },
        }
    )

    decision = proposal.to_decision()

    assert [str(item.resolved_name) for item in decision.patch.dimensions_upsert] == ["region"]


@pytest.mark.parametrize("blocked_field", ["metric", "dimension"])
def test_collection_blocker_rejects_unattributed_remove(blocked_field: str) -> None:
    payload = RequirementPatch(
        version="v0.2",
        metrics_remove=["paid_amount"] if blocked_field == "metric" else [],
        dimensions_remove=["region"] if blocked_field == "dimension" else [],
    ).model_dump(mode="json")
    payload.update(grain="NO_CHANGE", comparison="NO_CHANGE", unresolved_replace=None)
    proposal = DialogueProposal.model_validate(
        {
            "version": "v0.1",
            "patch": payload,
            "resolution": {
                "action": "ASK_CLARIFICATION",
                "unresolved_replace": [
                    {
                        "field": blocked_field,
                        "subject_term": "sales" if blocked_field == "metric" else "location",
                        "reason": "collection subject is ambiguous",
                        "blocking": True,
                    }
                ],
                "question": "Which one?",
                "reason": "collection subject is blocking",
            },
        }
    )

    with pytest.raises(ValueError, match="cannot safely attribute remove"):
        proposal.to_decision()


def test_filter_blocker_rejects_whole_list_replacement() -> None:
    payload = RequirementPatch(
        version="v0.2",
        filters_replace=[FilterRequirement(field_term="region", operator="=", value="East")],
    ).model_dump(mode="json")
    payload.update(grain="NO_CHANGE", comparison="NO_CHANGE", unresolved_replace=None)
    proposal = DialogueProposal.model_validate(
        {
            "version": "v0.1",
            "patch": payload,
            "resolution": {
                "action": "ASK_CLARIFICATION",
                "unresolved_replace": [
                    {
                        "field": "filter",
                        "subject_term": "region",
                        "reason": "filter value is ambiguous",
                        "blocking": True,
                    }
                ],
                "question": "Which region?",
                "reason": "filter is blocking",
            },
        }
    )

    with pytest.raises(ValueError, match="whole-list filter replacement"):
        proposal.to_decision()


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


def test_model_facing_non_empty_strings_use_ollama_compatible_length_schema() -> None:
    schema = DialogueDecision.model_json_schema()

    def patterns(value: object) -> list[str]:
        if isinstance(value, dict):
            found = [str(value["pattern"])] if "pattern" in value else []
            return found + [item for child in value.values() for item in patterns(child)]
        if isinstance(value, list):
            return [item for child in value for item in patterns(child)]
        return []

    assert patterns(schema) == []
    assert schema["properties"]["reason"]["minLength"] == 1

    with pytest.raises(ValidationError, match="non-whitespace"):
        DialogueDecision.model_validate(
            {
                "version": "v0.1",
                "patch": RequirementPatch(version="v0.2", unresolved_replace=[]).model_dump(
                    mode="json"
                ),
                "action": DialogueAction.READY,
                "question": None,
                "reason": "   ",
            }
        )
