"""Deterministic lifecycle policy for one inbound-message Run."""

from data_agent.contracts.run import Run, RunStatus


class InvalidRunTransitionError(ValueError):
    """Raised when a caller attempts a transition outside the frozen graph."""


TERMINAL_RUN_STATUSES = frozenset(
    {
        RunStatus.CLARIFYING,
        RunStatus.COMPLETED,
        RunStatus.POLICY_DENIED,
        RunStatus.QUERY_TOO_EXPENSIVE,
        RunStatus.REPAIR_EXHAUSTED,
        RunStatus.FAILED,
    }
)

_ALLOWED_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.RECEIVED: frozenset({RunStatus.UNDERSTANDING}),
    RunStatus.UNDERSTANDING: frozenset(
        {RunStatus.CLARIFYING, RunStatus.RETRIEVING, RunStatus.FAILED}
    ),
    RunStatus.RETRIEVING: frozenset({RunStatus.PLANNING, RunStatus.FAILED}),
    RunStatus.PLANNING: frozenset({RunStatus.VALIDATING, RunStatus.FAILED}),
    RunStatus.VALIDATING: frozenset(
        {
            RunStatus.EXECUTING,
            RunStatus.POLICY_DENIED,
            RunStatus.QUERY_TOO_EXPENSIVE,
            RunStatus.FAILED,
        }
    ),
    RunStatus.EXECUTING: frozenset(
        {
            RunStatus.VERIFYING,
            RunStatus.VALIDATING,
            RunStatus.REPAIR_EXHAUSTED,
            RunStatus.FAILED,
        }
    ),
    RunStatus.VERIFYING: frozenset(
        {
            RunStatus.SYNTHESIZING,
            RunStatus.VALIDATING,
            RunStatus.REPAIR_EXHAUSTED,
            RunStatus.FAILED,
        }
    ),
    RunStatus.SYNTHESIZING: frozenset({RunStatus.COMPLETED, RunStatus.FAILED}),
}


class RunStateMachine:
    """Validate initial, persisted, and requested Run lifecycle states."""

    @staticmethod
    def require_initial(run: Run) -> None:
        if run.status is not RunStatus.RECEIVED:
            raise InvalidRunTransitionError("a new Run must start in RECEIVED")
        if run.completed_at is not None:
            raise InvalidRunTransitionError("a new Run cannot already be completed")
        if run.repair_count != 0:
            raise InvalidRunTransitionError("a new Run must start with repair_count 0")
        if run.error_code is not None:
            raise InvalidRunTransitionError("a new Run cannot already have an error_code")

    @staticmethod
    def require_consistent(run: Run) -> None:
        is_terminal = run.status in TERMINAL_RUN_STATUSES
        if is_terminal and run.completed_at is None:
            raise InvalidRunTransitionError("a terminal Run must have completed_at")
        if not is_terminal and run.completed_at is not None:
            raise InvalidRunTransitionError("a non-terminal Run cannot have completed_at")

    @staticmethod
    def transition(current: RunStatus, target: RunStatus) -> RunStatus:
        if current in TERMINAL_RUN_STATUSES:
            raise InvalidRunTransitionError(f"terminal Run status {current} has no transitions")
        if target not in _ALLOWED_TRANSITIONS.get(current, frozenset()):
            raise InvalidRunTransitionError(f"illegal Run transition: {current} -> {target}")
        return target
