"""Typed fail-closed M9 planner failures."""


class PlannerError(RuntimeError):
    """Base error for query-planning failures."""


class PlannerInputError(PlannerError):
    """Planner input does not prove one bounded authorized semantic world."""


class PlannerPolicyError(PlannerError):
    """A structured QueryPlan violates deterministic declared-scope policy."""


class PlannerEvaluationError(PlannerError):
    """The standalone planner evaluation cannot be loaded or completed."""
