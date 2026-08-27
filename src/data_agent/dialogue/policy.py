"""Harness-owned validation of model-proposed dialogue actions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from data_agent.contracts.dialogue import (
    BlockingAmbiguity,
    DialogueAction,
    DialogueComparisonMutation,
    DialogueDecision,
    DialogueGrainMutation,
    DialogueProposal,
)
from data_agent.contracts.requirement import (
    PatchOp,
    RequirementState,
    RequirementStatus,
    ResolutionStatus,
)
from data_agent.dialogue.errors import DialoguePolicyError


@dataclass(frozen=True)
class DialogueOutcome:
    decision: DialogueDecision
    requirement: RequirementState
    blocking: BlockingPolicyResult | None = None


class BlockingDisposition(StrEnum):
    BLOCKING = "BLOCKING"
    NONBLOCKING = "NONBLOCKING"
    INVALID_CANDIDATE = "INVALID_CANDIDATE"


class BlockingReasonCode(StrEnum):
    UNRESOLVED_METRIC = "UNRESOLVED_METRIC"
    UNRESOLVED_DIMENSION = "UNRESOLVED_DIMENSION"
    EXPLICIT_TIME_AMBIGUITY = "EXPLICIT_TIME_AMBIGUITY"
    EXPLICIT_GRAIN_AMBIGUITY = "EXPLICIT_GRAIN_AMBIGUITY"
    UNRESOLVED_FILTER = "UNRESOLVED_FILTER"
    UNRESOLVED_COMPARISON = "UNRESOLVED_COMPARISON"
    OPTIONAL_TIME_ABSENT = "OPTIONAL_TIME_ABSENT"
    OPTIONAL_GRAIN_ABSENT = "OPTIONAL_GRAIN_ABSENT"
    ALREADY_RESOLVED = "ALREADY_RESOLVED"
    STALE_BLOCKER = "STALE_BLOCKER"
    NON_MATERIAL = "NON_MATERIAL"


@dataclass(frozen=True)
class BlockingCandidateAssessment:
    index: int
    field: str
    subject_term: str
    disposition: BlockingDisposition
    reason_code: BlockingReasonCode


@dataclass(frozen=True)
class BlockingPolicyResult:
    assessments: tuple[BlockingCandidateAssessment, ...]
    blocking_candidates: tuple[BlockingAmbiguity, ...]

    @property
    def has_blocking(self) -> bool:
        return bool(self.blocking_candidates)


def _subject_key(value: str) -> str:
    return " ".join(value.casefold().split())


def _distinct_options(candidate: BlockingAmbiguity) -> set[str]:
    return {_subject_key(str(value)) for value in candidate.options}


def _has_current_blocker(requirement: RequirementState, field: str) -> bool:
    return any(item.blocking and str(item.field) == field for item in requirement.unresolved)


class BlockingAmbiguityPolicy:
    """Classify model candidates from structured state, never from explanation prose."""

    def evaluate(
        self,
        *,
        requirement: RequirementState,
        merged: RequirementState,
        proposal: DialogueProposal,
        latest_user_message: str,
    ) -> BlockingPolicyResult:
        assessments: list[BlockingCandidateAssessment] = []
        blocking_candidates: list[BlockingAmbiguity] = []
        latest_key = _subject_key(latest_user_message)
        candidates = [item for item in proposal.resolution.unresolved_replace if item.blocking]
        for index, candidate in enumerate(candidates):
            disposition, reason_code = self._classify(
                requirement=requirement,
                merged=merged,
                proposal=proposal,
                candidate=candidate,
                latest_key=latest_key,
            )
            assessments.append(
                BlockingCandidateAssessment(
                    index=index,
                    field=str(candidate.field),
                    subject_term=str(candidate.subject_term),
                    disposition=disposition,
                    reason_code=reason_code,
                )
            )
            if disposition is BlockingDisposition.BLOCKING:
                blocking_candidates.append(candidate)
        return BlockingPolicyResult(
            assessments=tuple(assessments),
            blocking_candidates=tuple(blocking_candidates),
        )

    def _classify(
        self,
        *,
        requirement: RequirementState,
        merged: RequirementState,
        proposal: DialogueProposal,
        candidate: BlockingAmbiguity,
        latest_key: str,
    ) -> tuple[BlockingDisposition, BlockingReasonCode]:
        field = str(candidate.field)
        subject = _subject_key(str(candidate.subject_term))
        carried = _has_current_blocker(requirement, field)
        if subject not in latest_key and not carried:
            return BlockingDisposition.INVALID_CANDIDATE, BlockingReasonCode.STALE_BLOCKER

        if field == "time_range":
            if (
                proposal.patch.time_range.op is not PatchOp.NO_CHANGE
                or merged.time_range is not None
            ):
                return BlockingDisposition.NONBLOCKING, BlockingReasonCode.ALREADY_RESOLVED
            if carried or len(_distinct_options(candidate)) >= 2:
                return (
                    BlockingDisposition.BLOCKING,
                    BlockingReasonCode.EXPLICIT_TIME_AMBIGUITY,
                )
            return BlockingDisposition.NONBLOCKING, BlockingReasonCode.OPTIONAL_TIME_ABSENT

        if field == "grain":
            if (
                proposal.patch.grain is not DialogueGrainMutation.NO_CHANGE
                or merged.grain is not None
            ):
                return BlockingDisposition.NONBLOCKING, BlockingReasonCode.ALREADY_RESOLVED
            if carried or len(_distinct_options(candidate)) >= 2:
                return (
                    BlockingDisposition.BLOCKING,
                    BlockingReasonCode.EXPLICIT_GRAIN_AMBIGUITY,
                )
            return BlockingDisposition.NONBLOCKING, BlockingReasonCode.OPTIONAL_GRAIN_ABSENT

        if field in {"metric", "dimension"}:
            items = merged.metrics if field == "metric" else merged.dimensions
            matched = [
                item
                for item in items
                if subject
                in {
                    _subject_key(str(item.term)),
                    _subject_key(str(item.resolved_name or "")),
                }
            ]
            if any(
                item.resolved_name is not None and item.status is not ResolutionStatus.UNRESOLVED
                for item in matched
            ):
                return BlockingDisposition.NONBLOCKING, BlockingReasonCode.ALREADY_RESOLVED
            if any(item.status is ResolutionStatus.UNRESOLVED for item in matched):
                return (
                    BlockingDisposition.BLOCKING,
                    BlockingReasonCode.UNRESOLVED_METRIC
                    if field == "metric"
                    else BlockingReasonCode.UNRESOLVED_DIMENSION,
                )
            if carried or len(_distinct_options(candidate)) >= 2:
                return (
                    BlockingDisposition.BLOCKING,
                    BlockingReasonCode.UNRESOLVED_METRIC
                    if field == "metric"
                    else BlockingReasonCode.UNRESOLVED_DIMENSION,
                )
            return BlockingDisposition.NONBLOCKING, BlockingReasonCode.NON_MATERIAL

        if field == "comparison":
            if (
                proposal.patch.comparison is not DialogueComparisonMutation.NO_CHANGE
                or merged.comparison is not None
            ):
                return BlockingDisposition.NONBLOCKING, BlockingReasonCode.ALREADY_RESOLVED
            return BlockingDisposition.BLOCKING, BlockingReasonCode.UNRESOLVED_COMPARISON

        if field == "filter":
            return BlockingDisposition.BLOCKING, BlockingReasonCode.UNRESOLVED_FILTER

        return BlockingDisposition.NONBLOCKING, BlockingReasonCode.NON_MATERIAL


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
