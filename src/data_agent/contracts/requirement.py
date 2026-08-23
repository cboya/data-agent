"""Canonical analytics requirement contracts and patch operations."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from enum import StrEnum
from typing import Any, Literal, Self

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


class RequirementPatch(ContractModel):
    goal_replace: NonEmptyString | None = None
    metrics_upsert: list[MetricRequirement] = Field(default_factory=list)
    dimensions_upsert: list[DimensionRequirement] = Field(default_factory=list)
    filters_replace: list[FilterRequirement] | None = None
    time_range_replace: TimeRange | None = None
    grain_replace: NonEmptyString | None = None
    comparison_replace: NonEmptyString | None = None
    sort_replace: NonEmptyString | None = None
    limit_replace: int | None = Field(default=None, gt=0)
    confirmed_terms_upsert: dict[NonEmptyString, NonEmptyString] = Field(default_factory=dict)
    assumptions_add: list[NonEmptyString] = Field(default_factory=list)
    unresolved_replace: list[Ambiguity] | None = None
