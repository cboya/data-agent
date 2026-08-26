"""Integrity-checked M9→M10→M11 evidence context for M12."""

from __future__ import annotations

from dataclasses import dataclass, field

from data_agent.contracts.execution import ExecutionResult
from data_agent.planning.service import PlanningTrace
from data_agent.query_runtime.evidence import (
    EXECUTION_METADATA_VERSION,
    RESULT_FINGERPRINT_VERSION,
    ExecutionMetadata,
    ExecutionOutcome,
    execution_result_fingerprint,
)
from data_agent.sql_guard.capability import GuardedQuery, query_plan_fingerprint
from data_agent.verification.errors import VerificationIntegrityError

_CONTEXT_TOKEN = object()


@dataclass(frozen=True)
class VerificationContext:
    """One coherent evidence chain; construct through ``build_verification_context``."""

    planning_trace: PlanningTrace
    guarded_query: GuardedQuery
    execution_metadata: ExecutionMetadata
    execution_result: ExecutionResult
    _token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        self.verify_integrity()

    def verify_integrity(self) -> None:
        if self._token is not _CONTEXT_TOKEN:
            raise VerificationIntegrityError(
                "VerificationContext can only be built from validated pipeline evidence"
            )
        if not isinstance(self.planning_trace, PlanningTrace):
            raise VerificationIntegrityError("planning evidence must be a PlanningTrace")
        if not isinstance(self.guarded_query, GuardedQuery):
            raise VerificationIntegrityError("query evidence must be a GuardedQuery")
        if not isinstance(self.execution_metadata, ExecutionMetadata):
            raise VerificationIntegrityError("execution metadata has an invalid type")
        if not isinstance(self.execution_result, ExecutionResult):
            raise VerificationIntegrityError("execution result has an invalid type")

        try:
            self.guarded_query.verify_integrity()
        except (AttributeError, TypeError, ValueError) as error:
            raise VerificationIntegrityError("GuardedQuery integrity validation failed") from error

        metadata = self.execution_metadata
        query = self.guarded_query
        if metadata.version != EXECUTION_METADATA_VERSION:
            raise VerificationIntegrityError("execution metadata version is stale or unsupported")
        if metadata.outcome is not ExecutionOutcome.SUCCEEDED:
            raise VerificationIntegrityError("verification requires successful execution evidence")
        if metadata.error_code is not None or metadata.error_detail is not None:
            raise VerificationIntegrityError(
                "successful execution evidence cannot contain an error"
            )

        plan_fingerprint = query_plan_fingerprint(self.planning_trace.plan)
        if plan_fingerprint != query.query_plan_fingerprint:
            raise VerificationIntegrityError("PlanningTrace plan does not match GuardedQuery")
        context_tables = tuple(str(table) for table in self.planning_trace.context.allowed_tables)
        if self.planning_trace.allowed_tables != context_tables:
            raise VerificationIntegrityError("PlanningTrace allowed-table evidence is inconsistent")
        if (
            self.planning_trace.retrieval_index_fingerprint
            != self.planning_trace.context.identity.retrieval_index_fingerprint
        ):
            raise VerificationIntegrityError("PlanningTrace retrieval identity is inconsistent")
        plan_tables = [str(table) for table in self.planning_trace.plan.tables]
        if len(plan_tables) != len(set(plan_tables)) or not set(plan_tables).issubset(
            context_tables
        ):
            raise VerificationIntegrityError("PlanningTrace plan escapes its bounded table context")
        physical_table_names = {table.name for table in query.physical_tables}
        if not physical_table_names.issubset(plan_tables):
            raise VerificationIntegrityError("GuardedQuery physical tables escape QueryPlan")
        if (
            set(str(table) for table in query.guard_result.referenced_tables)
            != physical_table_names
        ):
            raise VerificationIntegrityError(
                "GuardedQuery table evidence is internally inconsistent"
            )
        if metadata.query_plan_fingerprint != query.query_plan_fingerprint:
            raise VerificationIntegrityError("execution metadata plan identity does not match")
        if metadata.guarded_query_fingerprint != query.capability_fingerprint:
            raise VerificationIntegrityError(
                "execution metadata capability identity does not match"
            )
        if metadata.sql_digest != query.sql_digest:
            raise VerificationIntegrityError("execution metadata SQL identity does not match")
        if metadata.guard_policy_version != query.guard_policy_version:
            raise VerificationIntegrityError(
                "execution metadata guard policy identity does not match"
            )
        if metadata.explain_policy_version != query.explain_policy_version:
            raise VerificationIntegrityError(
                "execution metadata EXPLAIN policy identity does not match"
            )
        if not (
            query.execution_namespace == metadata.execution_namespace == metadata.database_schema
        ):
            raise VerificationIntegrityError("execution namespace evidence does not match")
        physical_tables = tuple(table.qualified_name for table in query.physical_tables)
        if metadata.physical_tables != physical_tables:
            raise VerificationIntegrityError("execution metadata physical tables do not match")
        if metadata.result_fingerprint_version != RESULT_FINGERPRINT_VERSION:
            raise VerificationIntegrityError("execution result fingerprint version is unsupported")
        try:
            actual_result_fingerprint = execution_result_fingerprint(self.execution_result)
        except (TypeError, ValueError) as error:
            raise VerificationIntegrityError("execution result cannot be fingerprinted") from error
        if metadata.result_fingerprint != actual_result_fingerprint:
            raise VerificationIntegrityError("ExecutionResult fingerprint does not match metadata")


def build_verification_context(
    *,
    planning_trace: PlanningTrace,
    guarded_query: GuardedQuery,
    execution_metadata: ExecutionMetadata,
    execution_result: ExecutionResult,
) -> VerificationContext:
    """Validate and issue the only input accepted by the deterministic verifier."""

    return VerificationContext(
        planning_trace=planning_trace,
        guarded_query=guarded_query,
        execution_metadata=execution_metadata,
        execution_result=execution_result,
        _token=_CONTEXT_TOKEN,
    )
