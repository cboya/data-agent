"""In-memory control UoW and stage doubles for full M8-M14 orchestration tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from data_agent.contracts.message import Message
from data_agent.contracts.requirement import RequirementStatus
from data_agent.contracts.run import Run, RunStatus
from data_agent.contracts.session import Session, SessionStatus
from data_agent.conversation.models import (
    ConversationResponse,
    RunView,
    SessionView,
)
from data_agent.conversation.service import ConversationOrchestrator
from data_agent.persistence.errors import RecordNotFoundError
from data_agent.persistence.ports import (
    DialogueTurnSnapshot,
    StoredDialogueTurn,
    StoredMessage,
    StoredRunCompletion,
    StoredRunDialogueTurn,
    StoredSession,
)
from data_agent.planning.service import PlanningTrace
from data_agent.retrieval.service import RetrievalTrace
from data_agent.trace.model import TraceEvent, TraceEventDraft
from data_agent.trace.policy import TraceCompletenessPolicy
from tests.planning.factories import retrieval_result
from tests.repair.factories import MemoryRunRepository
from tests.verification.factories import ready_requirement

NOW = datetime(2026, 8, 26, 14, tzinfo=UTC)


def active_session() -> Session:
    requirement = ready_requirement().model_copy(update={"status": RequirementStatus.INCOMPLETE})
    return Session(
        id="session-m14",
        status=SessionStatus.ACTIVE,
        requirement=requirement,
        created_at=NOW,
        updated_at=NOW,
    )


class MemoryConversationUnitOfWork:
    def __init__(
        self,
        *,
        runs: MemoryRunRepository,
        traces: MemoryTraceRepository,
        session: Session | None = None,
    ) -> None:
        self.runs = runs
        self.traces = traces
        self.session = StoredSession(session=session or active_session(), revision=0)
        self.messages: list[StoredMessage] = []
        self.completion_count = 0

    def load(self, session_id: str) -> DialogueTurnSnapshot:
        assert session_id == self.session.session.id
        assistants = [value for value in self.messages if value.message.role.value == "assistant"]
        return DialogueTurnSnapshot(
            session=self.session,
            last_assistant=assistants[-1] if assistants else None,
        )

    def commit(
        self,
        *,
        session: Session,
        expected_revision: int,
        user_message: Message,
        assistant_message: Message | None,
    ) -> StoredDialogueTurn:
        if expected_revision != self.session.revision:
            raise RuntimeError("stale test session")
        stored_user = self._append(user_message)
        stored_assistant = self._append(assistant_message) if assistant_message else None
        self.session = StoredSession(session=session, revision=expected_revision + 1)
        return StoredDialogueTurn(
            session=self.session,
            user_message=stored_user,
            assistant_message=stored_assistant,
        )

    def commit_dialogue_with_run(
        self,
        *,
        session: Session,
        expected_revision: int,
        user_message: Message,
        assistant_message: Message | None,
        run_id: str,
        target: RunStatus,
        trace_events: tuple[TraceEventDraft, ...],
    ) -> StoredRunDialogueTurn:
        turn = self.commit(
            session=session,
            expected_revision=expected_revision,
            user_message=user_message,
            assistant_message=assistant_message,
        )
        run = self.runs.transition(run_id, target, transitioned_at=NOW)
        self.traces.append_many(trace_events)
        if target in {RunStatus.CLARIFYING, RunStatus.FAILED}:
            TraceCompletenessPolicy().validate(run, tuple(self.traces.list_for_run(run_id)))
        return StoredRunDialogueTurn(turn=turn, run=run)

    def complete_run_with_message(
        self,
        *,
        run_id: str,
        assistant_message: Message,
        completed_at: datetime,
        trace_events: tuple[TraceEventDraft, ...],
    ) -> StoredRunCompletion:
        stored = self._append(assistant_message)
        run = self.runs.transition(run_id, RunStatus.COMPLETED, transitioned_at=completed_at)
        self.traces.append_many(trace_events)
        TraceCompletenessPolicy().validate(run, tuple(self.traces.list_for_run(run_id)))
        self.completion_count += 1
        return StoredRunCompletion(assistant_message=stored, run=run)

    def terminate_run_with_trace(
        self,
        *,
        run_id: str,
        target: RunStatus,
        completed_at: datetime,
        error_code: str,
        trace_events: tuple[TraceEventDraft, ...],
    ) -> Run:
        run = self.runs.transition(
            run_id,
            target,
            transitioned_at=completed_at,
            error_code=error_code,
        )
        self.traces.append_many(trace_events)
        TraceCompletenessPolicy().validate(run, tuple(self.traces.list_for_run(run_id)))
        return run

    def _append(self, message: Message) -> StoredMessage:
        stored = StoredMessage(message=message, sequence=len(self.messages) + 1)
        self.messages.append(stored)
        return stored


@dataclass
class RecordingRetriever:
    trace: RetrievalTrace
    error: Exception | None = None
    calls: int = 0

    async def retrieve(self, query: str) -> RetrievalTrace:
        assert query
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.trace


def retrieval_trace() -> RetrievalTrace:
    result = retrieval_result(
        tables=("fact_order", "dim_user", "dim_region"),
        index_fingerprint="4" * 64,
    )
    return RetrievalTrace(
        result=result,
        fused_candidates=tuple(result.hits),
        seed_hits=tuple(result.hits),
        graph_expansions=(),
    )


class MemoryTraceRepository:
    def __init__(self) -> None:
        self.events: dict[str, list[TraceEvent]] = {}

    def append(self, draft: TraceEventDraft) -> TraceEvent:
        return self.append_many((draft,))[0]

    def append_many(self, drafts: tuple[TraceEventDraft, ...]) -> tuple[TraceEvent, ...]:
        inserted: list[TraceEvent] = []
        for draft in drafts:
            values = self.events.setdefault(str(draft.run_id), [])
            event = TraceEvent.model_validate(
                {**draft.model_dump(mode="python"), "sequence": len(values) + 1}
            )
            values.append(event)
            inserted.append(event)
        return tuple(inserted)

    def list_for_run(self, run_id: str) -> list[TraceEvent]:
        return list(self.events.get(run_id, ()))


@dataclass
class RecordingPlanner:
    trace: PlanningTrace
    calls: int = 0

    async def plan(self, **_: object) -> PlanningTrace:
        self.calls += 1
        return self.trace


class MemoryConversationApplication:
    def __init__(
        self,
        *,
        orchestrator: ConversationOrchestrator,
        unit_of_work: MemoryConversationUnitOfWork,
        runs: MemoryRunRepository,
    ) -> None:
        self._orchestrator = orchestrator
        self._uow = unit_of_work
        self._runs = runs

    def create_session(self) -> SessionView:
        return self.get_session(str(self._uow.session.session.id))

    def get_session(self, session_id: str) -> SessionView:
        if session_id != self._uow.session.session.id:
            raise RecordNotFoundError(f"Session {session_id} does not exist")
        return SessionView.from_session(
            self._uow.session.session,
            revision=self._uow.session.revision,
        )

    def get_run(self, run_id: str) -> RunView:
        if run_id != self._runs.run.id:
            raise RecordNotFoundError(f"Run {run_id} does not exist")
        return RunView.from_run(self._runs.run)

    async def process_message(self, *, session_id: str, content: str) -> ConversationResponse:
        return await self._orchestrator.process_message(
            session_id=session_id,
            content=content,
        )
