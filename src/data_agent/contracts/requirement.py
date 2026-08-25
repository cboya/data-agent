"""Canonical analytics requirement contracts and patch operations."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from data_agent.contracts.base import (
    AwareDateTime,
    ContractModel,
    ContractVersion,
    NonEmptyString,
    _require_timezone_aware,
)


class RequirementStatus(StrEnum):
    INCOMPLETE = "INCOMPLETE"
    CLARIFYING = "CLARIFYING"
    READY = "READY"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ResolutionStatus(StrEnum):
    UNRESOLVED = "UNRESOLVED"
    INFERRED = "INFERRED"
    CONFIRMED = "CONFIRMED"


class MetricRequirement(ContractModel):
    term: NonEmptyString
    resolved_name: NonEmptyString | None = None
    definition: NonEmptyString | None = None
    status: ResolutionStatus


class DimensionRequirement(ContractModel):
    term: NonEmptyString
    resolved_name: NonEmptyString | None = None
    status: ResolutionStatus


class FilterRequirement(ContractModel):
    field_term: NonEmptyString
    operator: NonEmptyString
    value: Any


class TimeRange(ContractModel):
    kind: Literal["RELATIVE", "ABSOLUTE"]
    value: NonEmptyString
    start: AwareDateTime | date | None = None
    end: AwareDateTime | date | None = None

    @field_validator("start", "end", mode="before")
    @classmethod
    def reject_naive_datetime(cls, value: object) -> object:
        if isinstance(value, datetime):
            _require_timezone_aware(value)
        return value

    @model_validator(mode="after")
    def validate_order(self) -> Self:
        if self.start is None or self.end is None:
            return self

        def comparable(value: datetime | date) -> datetime:
            if isinstance(value, datetime):
                return value.astimezone(UTC)
            return datetime.combine(value, time.min, tzinfo=UTC)

        if comparable(self.end) < comparable(self.start):
            raise ValueError("time range end must not precede start")
        return self


class Ambiguity(ContractModel):
    field: NonEmptyString
    reason: NonEmptyString
    options: list[NonEmptyString] = Field(default_factory=list)
    blocking: bool = True


class RequirementState(ContractModel):
    version: ContractVersion
    goal: NonEmptyString | None = None
    metrics: list[MetricRequirement] = Field(default_factory=list)
    dimensions: list[DimensionRequirement] = Field(default_factory=list)
    filters: list[FilterRequirement] = Field(default_factory=list)
    time_range: TimeRange | None = None
    grain: NonEmptyString | None = None
    comparison: NonEmptyString | None = None
    sort: NonEmptyString | None = None
    limit: int | None = Field(default=None, gt=0)
    confirmed_terms: dict[NonEmptyString, NonEmptyString] = Field(default_factory=dict)
    assumptions: list[NonEmptyString] = Field(default_factory=list)
    unresolved: list[Ambiguity] = Field(default_factory=list)
    status: RequirementStatus

    @model_validator(mode="after")
    def ready_has_no_blocking_ambiguity(self) -> Self:
        if self.status is RequirementStatus.READY and any(
            ambiguity.blocking for ambiguity in self.unresolved
        ):
            raise ValueError("READY requirement cannot contain a blocking ambiguity")
        return self


class PatchOp(StrEnum):
    NO_CHANGE = "NO_CHANGE"
    SET = "SET"
    CLEAR = "CLEAR"


class NoChangeScalarPatch(ContractModel):
    """Leave the current scalar value unchanged."""

    op: Literal[PatchOp.NO_CHANGE]
    value: None = None


class ClearScalarPatch(ContractModel):
    """Remove the current scalar value; use this for cancellation or explicit clearing."""

    op: Literal[PatchOp.CLEAR]
    value: None = None


class SetScalarPatch[PatchValueT](ContractModel):
    """Assign a concrete value; never use sentinel values such as CLEAR or null."""

    op: Literal[PatchOp.SET]
    value: PatchValueT = Field(
        description="Concrete assigned value; never the strings CLEAR, null, or NO_CHANGE"
    )


type ScalarPatch[PatchValueT] = Annotated[
    NoChangeScalarPatch | ClearScalarPatch | SetScalarPatch[PatchValueT],
    Field(discriminator="op"),
]


PositiveLimit = Annotated[int, Field(gt=0)]


def _requirement_identity(value: MetricRequirement | DimensionRequirement) -> str:
    return str(value.resolved_name or value.term)


class RequirementPatch(ContractModel):
    version: Literal["v0.2"]
    goal: ScalarPatch[NonEmptyString] = Field(
        default_factory=lambda: NoChangeScalarPatch(op=PatchOp.NO_CHANGE)
    )
    time_range: ScalarPatch[TimeRange] = Field(
        default_factory=lambda: NoChangeScalarPatch(op=PatchOp.NO_CHANGE)
    )
    grain: ScalarPatch[NonEmptyString] = Field(
        default_factory=lambda: NoChangeScalarPatch(op=PatchOp.NO_CHANGE)
    )
    comparison: ScalarPatch[NonEmptyString] = Field(
        default_factory=lambda: NoChangeScalarPatch(op=PatchOp.NO_CHANGE)
    )
    sort: ScalarPatch[NonEmptyString] = Field(
        default_factory=lambda: NoChangeScalarPatch(op=PatchOp.NO_CHANGE)
    )
    limit: ScalarPatch[PositiveLimit] = Field(
        default_factory=lambda: NoChangeScalarPatch(op=PatchOp.NO_CHANGE)
    )
    metrics_upsert: list[MetricRequirement] = Field(default_factory=list)
    metrics_remove: list[NonEmptyString] = Field(default_factory=list)
    dimensions_upsert: list[DimensionRequirement] = Field(default_factory=list)
    dimensions_remove: list[NonEmptyString] = Field(default_factory=list)
    filters_replace: list[FilterRequirement] | None = None
    confirmed_terms_upsert: dict[NonEmptyString, NonEmptyString] = Field(default_factory=dict)
    assumptions_add: list[NonEmptyString] = Field(default_factory=list)
    unresolved_replace: list[Ambiguity] | None = None

    @model_validator(mode="after")
    def collection_operations_are_unambiguous(self) -> Self:
        self._validate_collection_operations(
            kind="metric",
            remove=[str(value) for value in self.metrics_remove],
            upsert=[_requirement_identity(value) for value in self.metrics_upsert],
        )
        self._validate_collection_operations(
            kind="dimension",
            remove=[str(value) for value in self.dimensions_remove],
            upsert=[_requirement_identity(value) for value in self.dimensions_upsert],
        )
        return self

    @staticmethod
    def _validate_collection_operations(
        *,
        kind: str,
        remove: list[str],
        upsert: list[str],
    ) -> None:
        if len(remove) != len(set(remove)):
            raise ValueError(f"{kind} remove identities must be unique")
        if len(upsert) != len(set(upsert)):
            raise ValueError(f"{kind} upsert identities must be unique")
        overlap = set(remove) & set(upsert)
        if overlap:
            raise ValueError(f"{kind} identity cannot be removed and upserted together")
