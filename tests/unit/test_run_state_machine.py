from datetime import UTC, datetime

import pytest

from data_agent.contracts.run import Run, RunStatus
from data_agent.run_state import (
    TERMINAL_RUN_STATUSES,
    InvalidRunTransitionError,
    RunStateMachine,
)


def _run(**overrides: object) -> Run:
    values: dict[str, object] = {
        "id": "run_state_test",
        "session_id": "session_state_test",
        "status": RunStatus.RECEIVED,
        "repair_count": 0,
        "started_at": datetime(2026, 8, 25, 12, 0, tzinfo=UTC),
        "completed_at": None,
        "error_code": None,
    }
    values.update(overrides)
    return Run.model_validate(values)


def test_new_run_must_start_received() -> None:
    RunStateMachine.require_initial(_run())

    with pytest.raises(InvalidRunTransitionError, match="must start in RECEIVED"):
        RunStateMachine.require_initial(_run(status=RunStatus.UNDERSTANDING))

    with pytest.raises(InvalidRunTransitionError, match="cannot already have an error_code"):
        RunStateMachine.require_initial(_run(error_code="PREEXISTING_ERROR"))


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (RunStatus.RECEIVED, RunStatus.UNDERSTANDING),
        (RunStatus.UNDERSTANDING, RunStatus.CLARIFYING),
        (RunStatus.UNDERSTANDING, RunStatus.RETRIEVING),
        (RunStatus.RETRIEVING, RunStatus.PLANNING),
        (RunStatus.PLANNING, RunStatus.VALIDATING),
        (RunStatus.VALIDATING, RunStatus.EXECUTING),
        (RunStatus.EXECUTING, RunStatus.VERIFYING),
        (RunStatus.EXECUTING, RunStatus.VALIDATING),
        (RunStatus.VERIFYING, RunStatus.SYNTHESIZING),
        (RunStatus.VERIFYING, RunStatus.VALIDATING),
        (RunStatus.SYNTHESIZING, RunStatus.COMPLETED),
    ],
)
def test_legal_transitions_are_explicit(current: RunStatus, target: RunStatus) -> None:
    assert RunStateMachine.transition(current, target) is target


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (RunStatus.RECEIVED, RunStatus.COMPLETED),
        (RunStatus.RETRIEVING, RunStatus.EXECUTING),
        (RunStatus.PLANNING, RunStatus.RETRIEVING),
        (RunStatus.SYNTHESIZING, RunStatus.VERIFYING),
    ],
)
def test_illegal_transitions_fail_closed(current: RunStatus, target: RunStatus) -> None:
    with pytest.raises(InvalidRunTransitionError, match="illegal Run transition"):
        RunStateMachine.transition(current, target)


@pytest.mark.parametrize("terminal", sorted(TERMINAL_RUN_STATUSES, key=str))
def test_terminal_runs_cannot_resume(terminal: RunStatus) -> None:
    with pytest.raises(InvalidRunTransitionError, match="has no transitions"):
        RunStateMachine.transition(terminal, RunStatus.UNDERSTANDING)


def test_clarifying_is_terminal_for_current_run() -> None:
    completed_at = datetime(2026, 8, 25, 12, 1, tzinfo=UTC)
    clarifying = _run(status=RunStatus.CLARIFYING, completed_at=completed_at)

    RunStateMachine.require_consistent(clarifying)
    with pytest.raises(InvalidRunTransitionError, match="has no transitions"):
        RunStateMachine.transition(RunStatus.CLARIFYING, RunStatus.UNDERSTANDING)


def test_terminal_run_requires_completed_at() -> None:
    with pytest.raises(InvalidRunTransitionError, match="must have completed_at"):
        RunStateMachine.require_consistent(_run(status=RunStatus.FAILED))
