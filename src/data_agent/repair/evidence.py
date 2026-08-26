"""Internal M13 failure identity and bounded repair provenance."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from data_agent.contracts.base import NonEmptyString
from data_agent.verification.evidence import VerificationEvidenceIdentity

REPAIR_FAILURE_FINGERPRINT_VERSION = "repair-failure-fingerprint-v0.1"
REPAIR_POLICY_VERSION = "repair-policy-v0.1"
REPAIR_TRACE_VERSION = "repair-trace-v0.1"


class RepairStage(StrEnum):
    SQL_GUARD = "SQL_GUARD"
    EXPLAIN = "EXPLAIN"
    RUNTIME = "RUNTIME"
    VERIFICATION = "VERIFICATION"


class RepairCategory(StrEnum):
    FORMULATION = "FORMULATION"
    POLICY = "POLICY"
    COST = "COST"
    INTEGRITY = "INTEGRITY"
    CAPABILITY = "CAPABILITY"
    AVAILABILITY = "AVAILABILITY"
    TIMEOUT = "TIMEOUT"
    RESULT = "RESULT"
    TRUNCATION = "TRUNCATION"
    COVERAGE = "COVERAGE"


class RepairOutcomeKind(StrEnum):
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    EXHAUSTED = "EXHAUSTED"
    MODEL_FAILED = "MODEL_FAILED"
    POLICY_FAILED = "POLICY_FAILED"
    ADMISSION_FAILED = "ADMISSION_FAILED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    SUCCEEDED = "SUCCEEDED"


class _RepairModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class RepairFailure(_RepairModel):
    version: Literal["v0.1"] = "v0.1"
    stage: RepairStage
    category: RepairCategory
    code: NonEmptyString
    provider_errno: int | None = Field(default=None, ge=1)
    provider_sqlstate: str | None = Field(default=None, min_length=2, max_length=16)
    detail: str | None = Field(default=None, min_length=1, max_length=512)
    query_plan_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    planner_context_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    guarded_query_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    execution_id: str | None = Field(default=None, min_length=1, max_length=128)
    failed_checks: tuple[NonEmptyString, ...] = ()
    coverage_gaps: tuple[NonEmptyString, ...] = ()

    @model_validator(mode="after")
    def evidence_is_bounded_and_unambiguous(self) -> Self:
        if len(self.failed_checks) != len(set(self.failed_checks)):
            raise ValueError("repair failed-check names must be unique")
        if len(self.coverage_gaps) != len(set(self.coverage_gaps)):
            raise ValueError("repair coverage-gap names must be unique")
        if self.failed_checks and self.coverage_gaps:
            raise ValueError("repair failure cannot mix failed checks and coverage gaps")
        return self


def repair_failure_fingerprint(failure: RepairFailure) -> str:
    payload = {
        "fingerprint_version": REPAIR_FAILURE_FINGERPRINT_VERSION,
        "failure": failure.model_dump(mode="json"),
    }
    canonical = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class RepairTrace(_RepairModel):
    version: Literal["repair-trace-v0.1"] = "repair-trace-v0.1"
    repair_policy_version: Literal["repair-policy-v0.1"] = "repair-policy-v0.1"
    prompt_version: NonEmptyString
    attempt: int = Field(ge=0)
    max_attempts: int = Field(ge=0)
    eligible: bool
    failure_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    original_query_plan_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    replacement_query_plan_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    planner_context_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_fingerprint: str | None = None
    runtime_version: str | None = None
    outcome: RepairOutcomeKind
    final_verification_evidence: VerificationEvidenceIdentity | None = None

    @model_validator(mode="after")
    def outcome_matches_evidence(self) -> Self:
        if self.attempt > self.max_attempts:
            raise ValueError("repair trace attempt exceeds configured maximum")
        if self.outcome is RepairOutcomeKind.SUCCEEDED:
            if (
                self.replacement_query_plan_fingerprint is None
                or self.final_verification_evidence is None
            ):
                raise ValueError("successful repair requires replacement and verification evidence")
        elif self.final_verification_evidence is not None:
            raise ValueError("failed repair cannot carry successful verification evidence")
        if not self.eligible and self.attempt != 0:
            raise ValueError("ineligible repair cannot consume an attempt")
        return self
