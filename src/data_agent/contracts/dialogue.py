"""Validated decision proposed by the dialogue model."""

from collections.abc import Sequence
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from data_agent.contracts.base import ContractModel, ContractVersion, NonEmptyString
from data_agent.contracts.requirement import (
    Ambiguity,
    DimensionRequirement,
    MetricRequirement,
    PatchOp,
    RequirementPatch,
    ScalarPatch,
    TimeRange,
)


class DialogueAction(StrEnum):
    ASK_CLARIFICATION = "ASK_CLARIFICATION"
    READY = "READY"
    CANNOT_RESOLVE = "CANNOT_RESOLVE"


class DialogueRequirementPatch(RequirementPatch):
    """Model-facing patch that must explicitly rebuild the ambiguity set."""

    unresolved_replace: list[Ambiguity]


class DialogueGrainMutation(StrEnum):
    """Provider wire value normalized into a scalar grain patch by the Harness."""

    NO_CHANGE = "NO_CHANGE"
    CLEAR = "CLEAR"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"


class DialogueComparisonMutation(StrEnum):
    """Provider wire value normalized into a scalar comparison patch by the Harness."""

    NO_CHANGE = "NO_CHANGE"
    CLEAR = "CLEAR"
    PREVIOUS_PERIOD = "previous_period"
    PERIOD_OVER_PERIOD = "period_over_period"
    WEEK_OVER_WEEK = "week_over_week"
    MONTH_OVER_MONTH = "month_over_month"
    YEAR_OVER_YEAR = "year_over_year"


class DialoguePatchProposal(RequirementPatch):
    """Provider-facing mutation grammar before ambiguity resolution is normalized."""

    time_range: ScalarPatch[TimeRange]
    grain: DialogueGrainMutation  # type: ignore[assignment]
    comparison: DialogueComparisonMutation  # type: ignore[assignment]
    metrics_upsert: list[MetricRequirement]
    metrics_remove: list[NonEmptyString]
    dimensions_upsert: list[DimensionRequirement]
    dimensions_remove: list[NonEmptyString]
    unresolved_replace: None = None


def _normalized_grain_patch(value: DialogueGrainMutation) -> dict[str, object]:
    if value is DialogueGrainMutation.NO_CHANGE:
        return {"op": PatchOp.NO_CHANGE, "value": None}
    if value is DialogueGrainMutation.CLEAR:
        return {"op": PatchOp.CLEAR, "value": None}
    return {"op": PatchOp.SET, "value": value.value}


def _proposal_grain(patch: RequirementPatch) -> DialogueGrainMutation:
    if patch.grain.op is PatchOp.NO_CHANGE:
        return DialogueGrainMutation.NO_CHANGE
    if patch.grain.op is PatchOp.CLEAR:
        return DialogueGrainMutation.CLEAR
    return DialogueGrainMutation(str(patch.grain.value))


def _normalized_comparison_patch(value: DialogueComparisonMutation) -> dict[str, object]:
    if value is DialogueComparisonMutation.NO_CHANGE:
        return {"op": PatchOp.NO_CHANGE, "value": None}
    if value is DialogueComparisonMutation.CLEAR:
        return {"op": PatchOp.CLEAR, "value": None}
    return {"op": PatchOp.SET, "value": value.value}


def _proposal_comparison(patch: RequirementPatch) -> DialogueComparisonMutation:
    if patch.comparison.op is PatchOp.NO_CHANGE:
        return DialogueComparisonMutation.NO_CHANGE
    if patch.comparison.op is PatchOp.CLEAR:
        return DialogueComparisonMutation.CLEAR
    return DialogueComparisonMutation(str(patch.comparison.value))


class BlockingAmbiguity(Ambiguity):
    field: Literal["metric", "time_range", "grain", "dimension", "filter", "comparison"]
    subject_term: NonEmptyString
    blocking: Literal[True] = True


class NonBlockingAmbiguity(Ambiguity):
    field: Literal["display_format", "sort", "limit", "presentation", "comparison"]
    blocking: Literal[False] = False


class AskClarificationResolution(ContractModel):
    action: Literal[DialogueAction.ASK_CLARIFICATION]
    unresolved_replace: list[BlockingAmbiguity] = Field(min_length=1)
    question: Annotated[NonEmptyString, StringConstraints(max_length=240)]
    reason: NonEmptyString


class ReadyResolution(ContractModel):
    action: Literal[DialogueAction.READY]
    unresolved_replace: list[NonBlockingAmbiguity]
    question: None
    reason: NonEmptyString


class CannotResolveResolution(ContractModel):
    action: Literal[DialogueAction.CANNOT_RESOLVE]
    unresolved_replace: list[BlockingAmbiguity] = Field(min_length=1)
    question: None
    reason: NonEmptyString


type DialogueResolution = Annotated[
    AskClarificationResolution | ReadyResolution | CannotResolveResolution,
    Field(discriminator="action"),
]


class DialogueProposal(ContractModel):
    """Ollama-compatible structured response normalized into DialogueDecision."""

    version: ContractVersion
    patch: DialoguePatchProposal
    resolution: DialogueResolution

    @staticmethod
    def _subject_key(value: str) -> str:
        return " ".join(value.casefold().split())

    def _normalize_collection_blockers(
        self,
        patch_payload: dict[str, object],
        blocking: Sequence[BlockingAmbiguity],
    ) -> None:
        metric_subjects = {
            self._subject_key(str(item.subject_term)) for item in blocking if item.field == "metric"
        }
        dimension_subjects = {
            self._subject_key(str(item.subject_term))
            for item in blocking
            if item.field == "dimension"
        }
        if metric_subjects:
            patch_payload["metrics_upsert"] = [
                item.model_dump(mode="json")
                for item in self.patch.metrics_upsert
                if self._subject_key(str(item.term)) not in metric_subjects
            ]
            unattributed_removes = [
                str(value)
                for value in self.patch.metrics_remove
                if self._subject_key(str(value)) not in metric_subjects
            ]
            if unattributed_removes:
                raise ValueError(
                    "metric blocker cannot safely attribute remove identities: "
                    f"{unattributed_removes}"
                )
            patch_payload["metrics_remove"] = []
        if dimension_subjects:
            patch_payload["dimensions_upsert"] = [
                item.model_dump(mode="json")
                for item in self.patch.dimensions_upsert
                if self._subject_key(str(item.term)) not in dimension_subjects
            ]
            unattributed_removes = [
                str(value)
                for value in self.patch.dimensions_remove
                if self._subject_key(str(value)) not in dimension_subjects
            ]
            if unattributed_removes:
                raise ValueError(
                    "dimension blocker cannot safely attribute remove identities: "
                    f"{unattributed_removes}"
                )
            patch_payload["dimensions_remove"] = []
        if (
            any(item.field == "filter" for item in blocking)
            and self.patch.filters_replace is not None
        ):
            raise ValueError("filter blocker cannot safely normalize whole-list filter replacement")

    def to_requirement_patch(
        self,
        *,
        blocking: Sequence[BlockingAmbiguity],
    ) -> RequirementPatch:
        """Normalize provider mutations while suppressing only proven blockers."""

        patch_payload = self.patch.model_dump(mode="json")
        blocking_fields = {str(item.field) for item in blocking}
        if "time_range" in blocking_fields:
            patch_payload["time_range"] = {"op": PatchOp.NO_CHANGE, "value": None}
        if "grain" in blocking_fields:
            patch_payload["grain"] = DialogueGrainMutation.NO_CHANGE
        if "comparison" in blocking_fields:
            patch_payload["comparison"] = DialogueComparisonMutation.NO_CHANGE
        self._normalize_collection_blockers(patch_payload, blocking)
        public_ambiguities = [
            Ambiguity.model_validate(item.model_dump(mode="json", exclude={"subject_term"}))
            for item in [
                *blocking,
                *(item for item in self.resolution.unresolved_replace if not item.blocking),
            ]
        ]
        return RequirementPatch.model_validate(
            {
                **patch_payload,
                "grain": _normalized_grain_patch(DialogueGrainMutation(patch_payload["grain"])),
                "comparison": _normalized_comparison_patch(
                    DialogueComparisonMutation(patch_payload["comparison"])
                ),
                "unresolved_replace": public_ambiguities,
            }
        )

    def to_candidate_patch(self) -> RequirementPatch:
        """Normalize all proposed facts before readiness policy classifies blockers."""

        return self.to_requirement_patch(blocking=())

    def to_decision(self) -> "DialogueDecision":
        """Conservatively normalize every provider blocker for compatibility callers."""

        blocking = tuple(item for item in self.resolution.unresolved_replace if item.blocking)
        patch = self.to_requirement_patch(blocking=blocking)
        return DialogueDecision.model_validate(
            {
                "version": self.version,
                "patch": patch.model_dump(mode="json"),
                "action": self.resolution.action,
                "question": self.resolution.question,
                "reason": self.resolution.reason,
            }
        )

    @classmethod
    def from_decision(cls, decision: "DialogueDecision") -> "DialogueProposal":
        patch_payload = {
            **decision.patch.model_dump(mode="json"),
            "grain": _proposal_grain(decision.patch),
            "comparison": _proposal_comparison(decision.patch),
            "unresolved_replace": None,
        }
        unresolved_payload = decision.patch.model_dump(mode="json")["unresolved_replace"]
        for item in unresolved_payload:
            if item["blocking"]:
                item["subject_term"] = item["field"]
        resolution_payload = {
            "action": decision.action,
            "unresolved_replace": unresolved_payload,
            "question": decision.question,
            "reason": decision.reason,
        }
        return cls.model_validate(
            {
                "version": decision.version,
                "patch": patch_payload,
                "resolution": resolution_payload,
            }
        )


class DialogueDecision(ContractModel):
    version: ContractVersion
    patch: DialogueRequirementPatch
    action: DialogueAction
    question: Annotated[NonEmptyString, StringConstraints(max_length=240)] | None
    reason: NonEmptyString

    @model_validator(mode="after")
    def action_matches_question_and_blockers(self) -> Self:
        blocking = [item for item in self.patch.unresolved_replace if item.blocking]
        if self.action is DialogueAction.ASK_CLARIFICATION:
            if self.question is None:
                raise ValueError("ASK_CLARIFICATION requires a question")
            if not blocking:
                raise ValueError("ASK_CLARIFICATION requires a blocking ambiguity")
        elif self.action is DialogueAction.READY:
            if self.question is not None:
                raise ValueError("READY cannot carry a question")
            if blocking:
                raise ValueError("READY cannot carry a blocking ambiguity")
        elif self.question is not None:
            raise ValueError("CANNOT_RESOLVE cannot carry a question")
        return self
