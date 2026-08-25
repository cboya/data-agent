"""Public exports for the architecture's binding domain contracts."""

from data_agent.contracts.artifact import Artifact, ArtifactType
from data_agent.contracts.catalog import (
    Cardinality,
    CatalogColumn,
    CatalogDocument,
    Relationship,
)
from data_agent.contracts.dialogue import DialogueAction, DialogueDecision
from data_agent.contracts.execution import (
    ExecutionResult,
    ExplainResult,
    ExplainTableAccess,
    GuardStatus,
    SQLGuardResult,
)
from data_agent.contracts.message import Message, MessageRole
from data_agent.contracts.query import ExpectedColumn, QueryPlan
from data_agent.contracts.requirement import (
    Ambiguity,
    ClearScalarPatch,
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
from data_agent.contracts.retrieval import RetrievalHit, RetrievalResult
from data_agent.contracts.run import Run, RunStatus
from data_agent.contracts.session import Session, SessionStatus
from data_agent.contracts.verification import CheckResult, VerificationResult

__all__ = [
    "Ambiguity",
    "Artifact",
    "ArtifactType",
    "Cardinality",
    "CatalogColumn",
    "CatalogDocument",
    "CheckResult",
    "ClearScalarPatch",
    "DialogueAction",
    "DialogueDecision",
    "DimensionRequirement",
    "ExecutionResult",
    "ExpectedColumn",
    "ExplainResult",
    "ExplainTableAccess",
    "FilterRequirement",
    "GuardStatus",
    "Message",
    "MessageRole",
    "MetricRequirement",
    "NoChangeScalarPatch",
    "PatchOp",
    "QueryPlan",
    "Relationship",
    "RequirementPatch",
    "RequirementState",
    "RequirementStatus",
    "ResolutionStatus",
    "RetrievalHit",
    "RetrievalResult",
    "Run",
    "RunStatus",
    "SQLGuardResult",
    "ScalarPatch",
    "Session",
    "SessionStatus",
    "SetScalarPatch",
    "TimeRange",
    "VerificationResult",
]
