"""M10 deterministic SQL guard and EXPLAIN admission boundary."""

from data_agent.sql_guard.capability import GuardedQuery, GuardedSQL, PhysicalTable
from data_agent.sql_guard.errors import (
    ExplainProviderError,
    SQLAdmissionError,
    SQLGuardEvaluationError,
)
from data_agent.sql_guard.explain import ExplainPlanProvider, ExplainPolicy, MySQLExplainProvider
from data_agent.sql_guard.guard import SQLGuard, SQLGuardEvaluation, SQLViolation
from data_agent.sql_guard.service import SQLAdmissionOutcome, SQLAdmissionService

__all__ = [
    "ExplainPlanProvider",
    "ExplainPolicy",
    "ExplainProviderError",
    "GuardedQuery",
    "GuardedSQL",
    "MySQLExplainProvider",
    "PhysicalTable",
    "SQLAdmissionError",
    "SQLAdmissionOutcome",
    "SQLAdmissionService",
    "SQLGuard",
    "SQLGuardEvaluation",
    "SQLGuardEvaluationError",
    "SQLViolation",
]
