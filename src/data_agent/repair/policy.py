"""Default-deny typed M13 repair eligibility."""

from __future__ import annotations

from dataclasses import dataclass

from data_agent.contracts.run import RunStatus
from data_agent.repair.evidence import RepairCategory, RepairFailure, RepairStage

_REPAIRABLE_MYSQL_CODES = frozenset({1052, 1054})
_REPAIRABLE_EXACT_CHECKS = frozenset(
    {
        "actual_columns_match_expected",
        "required_metrics_present",
        "required_dimensions_present",
        "grain_period_present",
        "governed_relationship_joins",
        "grouping_keys_unique",
    }
)
_REPAIRABLE_CHECK_PREFIXES = ("metric_source:", "dimension_source:")


@dataclass(frozen=True)
class RepairEligibilityDecision:
    eligible: bool
    reason: str
    terminal_status: RunStatus | None


def _repairable_verification_check(name: str) -> bool:
    return name in _REPAIRABLE_EXACT_CHECKS or name.startswith(_REPAIRABLE_CHECK_PREFIXES)


class RepairEligibilityPolicy:
    """Classify authority from stable fields only; diagnostic detail is ignored."""

    def evaluate(self, failure: RepairFailure) -> RepairEligibilityDecision:
        eligible = (
            (
                failure.stage is RepairStage.SQL_GUARD
                and failure.category is RepairCategory.FORMULATION
                and failure.code == "SQL_PARSE_ERROR"
            )
            or (
                failure.stage in {RepairStage.EXPLAIN, RepairStage.RUNTIME}
                and failure.category is RepairCategory.FORMULATION
                and failure.provider_errno in _REPAIRABLE_MYSQL_CODES
            )
            or (
                failure.stage is RepairStage.VERIFICATION
                and failure.category is RepairCategory.FORMULATION
                and bool(failure.failed_checks)
                and all(_repairable_verification_check(str(name)) for name in failure.failed_checks)
            )
        )
        if eligible:
            return RepairEligibilityDecision(True, "TYPED_ALLOWLIST_MATCH", None)
        if failure.category is RepairCategory.COVERAGE:
            return RepairEligibilityDecision(False, "COVERAGE_IS_NOT_A_FAILURE", None)
        if failure.category is RepairCategory.COST:
            return RepairEligibilityDecision(
                False, "COST_REJECTION_IS_TERMINAL", RunStatus.QUERY_TOO_EXPENSIVE
            )
        if failure.category is RepairCategory.POLICY:
            return RepairEligibilityDecision(
                False, "POLICY_REJECTION_IS_TERMINAL", RunStatus.POLICY_DENIED
            )
        return RepairEligibilityDecision(False, "NOT_IN_TYPED_ALLOWLIST", RunStatus.FAILED)
