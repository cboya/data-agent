"""Deterministic M9 policy over declared QueryPlan scope, never SQL text."""

from data_agent.contracts.query import QueryPlan
from data_agent.planning.context import PlannerContext
from data_agent.planning.errors import PlannerPolicyError


class PlannerPolicy:
    def __init__(self, *, max_assumptions: int = 8, max_expected_columns: int = 32) -> None:
        if max_assumptions < 0 or max_expected_columns < 1:
            raise ValueError("planner policy bounds are invalid")
        self._max_assumptions = max_assumptions
        self._max_expected_columns = max_expected_columns

    def validate(self, plan: QueryPlan, *, context: PlannerContext) -> QueryPlan:
        tables = [str(table) for table in plan.tables]
        if not tables:
            raise PlannerPolicyError("QueryPlan must declare at least one table")
        if len(tables) != len(set(tables)):
            raise PlannerPolicyError("QueryPlan declared tables must be unique")
        unauthorized = sorted(set(tables) - {str(table) for table in context.allowed_tables})
        if unauthorized:
            raise PlannerPolicyError(
                f"QueryPlan declared tables escape planner context: {unauthorized}"
            )
        if len(plan.assumptions) > self._max_assumptions:
            raise PlannerPolicyError("QueryPlan assumptions exceed the planner bound")
        if len(plan.expected_columns) > self._max_expected_columns:
            raise PlannerPolicyError("QueryPlan expected columns exceed the planner bound")
        column_names = [str(column.name) for column in plan.expected_columns]
        if len(column_names) != len(set(column_names)):
            raise PlannerPolicyError("QueryPlan expected column names must be unique")
        return plan
