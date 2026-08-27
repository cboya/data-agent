"""Internal M12 verification provenance and epistemic coverage."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from data_agent.contracts.base import NonEmptyString
from data_agent.contracts.verification import VerificationResult

VERIFICATION_TRACE_VERSION = "verification-trace-v0.2"
VERIFICATION_POLICY_VERSION = "verification-policy-v0.2"

type VerificationCategory = Literal["STRUCTURAL", "SEMANTIC", "EMPIRICAL"]


class CoverageDisposition(StrEnum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNSUPPORTED = "UNSUPPORTED"


class _VerificationEvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class VerificationCoverageGap(_VerificationEvidenceModel):
    name: NonEmptyString
    category: VerificationCategory
    disposition: CoverageDisposition
    detail: NonEmptyString


class VerificationEvidenceIdentity(_VerificationEvidenceModel):
    query_plan_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    guarded_query_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    execution_id: NonEmptyString
    sql_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    execution_namespace: NonEmptyString
    result_fingerprint_version: NonEmptyString
    result_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class VerificationTrace(_VerificationEvidenceModel):
    version: Literal["verification-trace-v0.2"] = "verification-trace-v0.2"
    verification_policy_version: Literal["verification-policy-v0.2"] = "verification-policy-v0.2"
    evidence: VerificationEvidenceIdentity
    applied_checks: tuple[NonEmptyString, ...]
    coverage_gaps: tuple[VerificationCoverageGap, ...]
    result: VerificationResult

    @model_validator(mode="after")
    def trace_matches_public_result(self) -> Self:
        check_names = tuple(str(check.name) for check in self.result.checks)
        if self.applied_checks != check_names:
            raise ValueError("applied verification checks must match public result order")
        if len(self.applied_checks) != len(set(self.applied_checks)):
            raise ValueError("applied verification check names must be unique")
        gap_keys = [(gap.category, str(gap.name)) for gap in self.coverage_gaps]
        if len(gap_keys) != len(set(gap_keys)):
            raise ValueError("verification coverage gaps must be unique")
        applied_keys = {(check.category, str(check.name)) for check in self.result.checks}
        if applied_keys.intersection(gap_keys):
            raise ValueError("a verification check cannot be applied and a coverage gap")
        return self
