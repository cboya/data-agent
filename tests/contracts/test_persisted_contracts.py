from datetime import UTC, datetime, timedelta

import pytest
from pydantic import BaseModel, ValidationError

from data_agent.contracts import (
    Artifact,
    ArtifactType,
    Message,
    MessageRole,
    RequirementState,
    RequirementStatus,
    Run,
    RunStatus,
    Session,
    SessionStatus,
)

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


def _requirement() -> RequirementState:
    return RequirementState(version="v0.1", status=RequirementStatus.INCOMPLETE)


@pytest.mark.parametrize(
    "contract",
    [
        Session(
            id="session-1",
            status=SessionStatus.ACTIVE,
            requirement=_requirement(),
            created_at=NOW,
            updated_at=NOW,
        ),
        Message(
            id="message-1",
            session_id="session-1",
            role=MessageRole.USER,
            content="最近 30 天的实付金额",
            created_at=NOW,
        ),
        _requirement(),
        Artifact(
            id="artifact-1",
            session_id="session-1",
            run_id="run-1",
            type=ArtifactType.REQUIREMENT_STATE,
            contract_version="v0.1",
            payload={"status": "INCOMPLETE"},
            created_at=NOW,
        ),
        Run(
            id="run-1",
            session_id="session-1",
            status=RunStatus.RECEIVED,
            started_at=NOW,
        ),
    ],
)
def test_persisted_contract_json_round_trip(contract: BaseModel) -> None:
    restored = type(contract).model_validate_json(contract.model_dump_json())
    assert restored == contract


def test_persisted_timestamps_must_be_timezone_aware() -> None:
    with pytest.raises(ValidationError):
        Message(
            id="message-1",
            session_id="session-1",
            role=MessageRole.USER,
            content="hello",
            created_at=datetime(2026, 8, 23, 12, 0),
        )


def test_session_and_run_reject_reversed_timestamps() -> None:
    with pytest.raises(ValidationError, match="updated_at"):
        Session(
            id="session-1",
            status=SessionStatus.ACTIVE,
            requirement=_requirement(),
            created_at=NOW,
            updated_at=NOW - timedelta(seconds=1),
        )

    with pytest.raises(ValidationError, match="completed_at"):
        Run(
            id="run-1",
            session_id="session-1",
            status=RunStatus.FAILED,
            started_at=NOW,
            completed_at=NOW - timedelta(seconds=1),
        )
