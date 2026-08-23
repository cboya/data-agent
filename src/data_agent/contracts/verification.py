"""Post-execution verification contracts."""

from typing import Literal, Self

from pydantic import model_validator

from data_agent.contracts.base import ContractModel, ContractVersion, NonEmptyString


class CheckResult(ContractModel):
    name: NonEmptyString
    category: Literal["STRUCTURAL", "SEMANTIC", "EMPIRICAL"]
    passed: bool
    detail: NonEmptyString | None = None


class VerificationResult(ContractModel):
    version: ContractVersion
    status: Literal["PASSED", "FAILED"]
    checks: list[CheckResult]

    @model_validator(mode="after")
    def status_matches_checks(self) -> Self:
        failures = [check for check in self.checks if not check.passed]
        if self.status == "PASSED" and failures:
            raise ValueError("PASSED verification cannot contain failed checks")
        if self.status == "FAILED" and not failures:
            raise ValueError("FAILED verification requires at least one failed check")
        return self
