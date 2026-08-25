"""Infrastructure-neutral repository contracts for durable control state."""

from dataclasses import dataclass
from typing import Protocol

from data_agent.contracts.artifact import Artifact
from data_agent.contracts.base import AwareDateTime
from data_agent.contracts.message import Message
from data_agent.contracts.run import Run, RunStatus
from data_agent.contracts.session import Session


@dataclass(frozen=True)
class StoredSession:
    session: Session
    revision: int

    def __post_init__(self) -> None:
        if self.revision < 0:
            raise ValueError("Session revision cannot be negative")


@dataclass(frozen=True)
class StoredMessage:
    message: Message
    sequence: int

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("Message sequence must be positive")


class SessionRepository(Protocol):
    def create(self, session: Session) -> StoredSession: ...

    def get(self, session_id: str) -> StoredSession: ...

    def update(self, session: Session, *, expected_revision: int) -> StoredSession: ...


class MessageRepository(Protocol):
    def append(self, message: Message) -> StoredMessage: ...

    def list_for_session(self, session_id: str) -> list[StoredMessage]: ...


class RunRepository(Protocol):
    def create(self, run: Run) -> Run: ...

    def get(self, run_id: str) -> Run: ...

    def transition(
        self,
        run_id: str,
        target: RunStatus,
        *,
        transitioned_at: AwareDateTime,
        error_code: str | None = None,
    ) -> Run: ...


class ArtifactRepository(Protocol):
    def append(self, artifact: Artifact) -> Artifact: ...

    def list_for_run(self, run_id: str) -> list[Artifact]: ...
