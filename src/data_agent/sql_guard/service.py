"""M10 two-stage SQL admission orchestration."""

from __future__ import annotations

from dataclasses import dataclass

from data_agent.contracts.execution import ExplainResult
from data_agent.contracts.query import QueryPlan
from data_agent.sql_guard.capability import GuardedQuery, issue_guarded_query
from data_agent.sql_guard.errors import ExplainProviderError
from data_agent.sql_guard.explain import EXPLAIN_POLICY_VERSION, ExplainPlanProvider, ExplainPolicy
from data_agent.sql_guard.guard import SQLGuard, SQLGuardEvaluation


@dataclass(frozen=True)
class SQLAdmissionOutcome:
    guard: SQLGuardEvaluation
    explain_result: ExplainResult | None = None
    guarded_query: GuardedQuery | None = None


class SQLAdmissionService:
    """Issue a GuardedQuery only after deterministic guard and EXPLAIN pass."""

    def __init__(
        self,
        *,
        guard: SQLGuard,
        explain_provider: ExplainPlanProvider,
        explain_policy: ExplainPolicy,
    ) -> None:
        self._guard = guard
        self._explain_provider = explain_provider
        self._explain_policy = explain_policy

    def admit(self, plan: QueryPlan) -> SQLAdmissionOutcome:
        guard = self._guard.evaluate(plan)
        if guard.candidate is None:
            return SQLAdmissionOutcome(guard=guard)
        try:
            raw_explain = self._explain_provider.explain(guard.candidate)
        except ExplainProviderError:
            explain_result = ExplainResult(
                accepted=False,
                accesses=[],
                rejection_reason="EXPLAIN_PROVIDER_FAILURE",
            )
            return SQLAdmissionOutcome(guard=guard, explain_result=explain_result)
        explain_result = self._explain_policy.evaluate(guard.candidate, raw_explain)
        if not explain_result.accepted:
            return SQLAdmissionOutcome(guard=guard, explain_result=explain_result)
        guarded_query = issue_guarded_query(
            guard.candidate,
            explain_result,
            explain_policy_version=EXPLAIN_POLICY_VERSION,
        )
        return SQLAdmissionOutcome(
            guard=guard,
            explain_result=explain_result,
            guarded_query=guarded_query,
        )
