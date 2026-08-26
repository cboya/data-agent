from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from data_agent.config import Settings
from data_agent.contracts.run import RunStatus
from data_agent.persistence.errors import RepairAttemptsExhaustedError
from data_agent.persistence.mysql.runs import MySQLRunRepository
from data_agent.persistence.mysql.sessions import MySQLSessionRepository
from data_agent.run_state import InvalidRunTransitionError
from tests.persistence.factories import run, session, timestamp

pytestmark = pytest.mark.integration


def test_run_follows_explicit_lifecycle_and_survives_reload(settings: Settings) -> None:
    created_session = MySQLSessionRepository(settings).create(session()).session
    repository = MySQLRunRepository(settings)
    created = repository.create(run(created_session.id))
    path = [
        RunStatus.UNDERSTANDING,
        RunStatus.RETRIEVING,
        RunStatus.PLANNING,
        RunStatus.VALIDATING,
        RunStatus.EXECUTING,
        RunStatus.VERIFYING,
        RunStatus.SYNTHESIZING,
        RunStatus.COMPLETED,
    ]

    current = created
    for offset, target in enumerate(path, start=1):
        current = repository.transition(
            current.id,
            target,
            transitioned_at=timestamp() + timedelta(minutes=offset),
        )

    reloaded = MySQLRunRepository(settings).get(created.id)
    assert current.status is RunStatus.COMPLETED
    assert current.completed_at == timestamp() + timedelta(minutes=len(path))
    assert reloaded == current


def test_invalid_run_transition_is_rejected_without_persisting(settings: Settings) -> None:
    created_session = MySQLSessionRepository(settings).create(session()).session
    repository = MySQLRunRepository(settings)
    created = repository.create(run(created_session.id))

    with pytest.raises(InvalidRunTransitionError, match="illegal Run transition"):
        repository.transition(
            created.id,
            RunStatus.COMPLETED,
            transitioned_at=timestamp() + timedelta(minutes=1),
        )

    assert repository.get(created.id).status is RunStatus.RECEIVED


def test_clarifying_run_is_terminal_and_reply_uses_new_run(settings: Settings) -> None:
    created_session = MySQLSessionRepository(settings).create(session()).session
    repository = MySQLRunRepository(settings)
    first = repository.create(run(created_session.id))
    repository.transition(
        first.id,
        RunStatus.UNDERSTANDING,
        transitioned_at=timestamp() + timedelta(minutes=1),
    )
    clarifying = repository.transition(
        first.id,
        RunStatus.CLARIFYING,
        transitioned_at=timestamp() + timedelta(minutes=2),
    )

    with pytest.raises(InvalidRunTransitionError, match="has no transitions"):
        repository.transition(
            first.id,
            RunStatus.UNDERSTANDING,
            transitioned_at=timestamp() + timedelta(minutes=3),
        )

    reply_run = repository.create(run(created_session.id))
    assert clarifying.completed_at == timestamp() + timedelta(minutes=2)
    assert reply_run.id != first.id
    assert reply_run.status is RunStatus.RECEIVED


def _advance_to_validating(repository: MySQLRunRepository, run_id: str) -> None:
    for offset, status in enumerate(
        (
            RunStatus.UNDERSTANDING,
            RunStatus.RETRIEVING,
            RunStatus.PLANNING,
            RunStatus.VALIDATING,
        ),
        start=1,
    ):
        repository.transition(
            run_id,
            status,
            transitioned_at=timestamp() + timedelta(minutes=offset),
        )


def test_repair_attempt_is_claimed_durably_before_inference(settings: Settings) -> None:
    created_session = MySQLSessionRepository(settings).create(session()).session
    repository = MySQLRunRepository(settings)
    created = repository.create(run(created_session.id))
    _advance_to_validating(repository, created.id)

    claimed = repository.claim_repair(created.id, max_attempts=1)

    assert claimed.status is RunStatus.VALIDATING
    assert claimed.repair_count == 1
    assert repository.get(created.id).repair_count == 1
    with pytest.raises(RepairAttemptsExhaustedError):
        repository.claim_repair(created.id, max_attempts=1)
    assert repository.get(created.id).repair_count == 1


def test_concurrent_repair_claims_cannot_exceed_bound(settings: Settings) -> None:
    created_session = MySQLSessionRepository(settings).create(session()).session
    created = MySQLRunRepository(settings).create(run(created_session.id))
    _advance_to_validating(MySQLRunRepository(settings), created.id)

    def claim() -> str:
        try:
            MySQLRunRepository(settings).claim_repair(created.id, max_attempts=1)
        except RepairAttemptsExhaustedError:
            return "EXHAUSTED"
        return "CLAIMED"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = sorted(executor.map(lambda _: claim(), range(2)))

    assert outcomes == ["CLAIMED", "EXHAUSTED"]
    assert MySQLRunRepository(settings).get(created.id).repair_count == 1
