"""Typed, persisted, bounded M13 replacement-plan repair."""

from data_agent.repair.evidence import (
    RepairCategory,
    RepairFailure,
    RepairOutcomeKind,
    RepairStage,
    RepairTrace,
    repair_failure_fingerprint,
)
from data_agent.repair.failures import (
    failure_from_admission,
    failure_from_coverage,
    failure_from_runtime,
    failure_from_verification,
    failure_from_verification_integrity,
)
from data_agent.repair.policy import RepairEligibilityDecision, RepairEligibilityPolicy
from data_agent.repair.service import BoundedRepairService, RepairPipelineOutcome

__all__ = [
    "BoundedRepairService",
    "RepairCategory",
    "RepairEligibilityDecision",
    "RepairEligibilityPolicy",
    "RepairFailure",
    "RepairOutcomeKind",
    "RepairPipelineOutcome",
    "RepairStage",
    "RepairTrace",
    "failure_from_admission",
    "failure_from_coverage",
    "failure_from_runtime",
    "failure_from_verification",
    "failure_from_verification_integrity",
    "repair_failure_fingerprint",
]
