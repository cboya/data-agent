"""Production M14 composition over frozen M4-M13 adapters and policies."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from data_agent.answer.service import AnswerSynthesizer
from data_agent.config import Settings
from data_agent.contracts.requirement import RequirementState, RequirementStatus
from data_agent.contracts.session import Session, SessionStatus
from data_agent.conversation.models import (
    ConversationResponse,
    RunView,
    SessionView,
)
from data_agent.conversation.service import ConversationOrchestrator
from data_agent.dialogue.service import DialogueEngine, DialogueService
from data_agent.model_runtime.ports import (
    ChatModel,
    EmbeddingModel,
    ModelRuntimeDiagnostics,
)
from data_agent.persistence.mysql.dialogue_turns import MySQLDialogueTurnStore
from data_agent.persistence.mysql.runs import MySQLRunRepository
from data_agent.persistence.mysql.sessions import MySQLSessionRepository
from data_agent.persistence.ports import StoredSession
from data_agent.planning.service import QueryPlanner
from data_agent.query_runtime.runtime import build_readonly_query_runtime
from data_agent.repair.service import BoundedRepairService
from data_agent.retrieval.index import load_retrieval_index
from data_agent.retrieval.runtime import load_current_catalog_authority
from data_agent.retrieval.service import HybridRetriever
from data_agent.sql_guard.runtime import build_sql_admission_service
from data_agent.verification.service import DeterministicVerifier


class ConversationApplicationPort(Protocol):
    def create_session(self) -> SessionView: ...

    def get_session(self, session_id: str) -> SessionView: ...

    def get_run(self, run_id: str) -> RunView: ...

    async def process_message(self, *, session_id: str, content: str) -> ConversationResponse: ...


class ConversationApplication:
    def __init__(
        self,
        *,
        sessions: MySQLSessionRepository,
        runs: MySQLRunRepository,
        orchestrator: ConversationOrchestrator,
    ) -> None:
        self._sessions = sessions
        self._runs = runs
        self._orchestrator = orchestrator

    def create_session(self) -> SessionView:
        now = datetime.now(UTC)
        stored = self._sessions.create(
            Session(
                id=f"session_{uuid4().hex}",
                status=SessionStatus.ACTIVE,
                requirement=RequirementState(version="v0.1", status=RequirementStatus.INCOMPLETE),
                created_at=now,
                updated_at=now,
            )
        )
        return self._session_view(stored)

    def get_session(self, session_id: str) -> SessionView:
        return self._session_view(self._sessions.get(session_id))

    def get_run(self, run_id: str) -> RunView:
        return RunView.from_run(self._runs.get(run_id))

    async def process_message(self, *, session_id: str, content: str) -> ConversationResponse:
        return await self._orchestrator.process_message(session_id=session_id, content=content)

    @staticmethod
    def _session_view(stored: StoredSession) -> SessionView:
        return SessionView.from_session(stored.session, revision=stored.revision)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def build_conversation_application(
    settings: Settings,
    *,
    diagnostics: ModelRuntimeDiagnostics,
    chat_model: ChatModel,
    embedding_model: EmbeddingModel,
) -> ConversationApplication:
    """Build once at startup; stale catalog/index/model identity fails startup closed."""

    authority = load_current_catalog_authority()
    index = load_retrieval_index(
        catalog=authority.assembled,
        current_generated_schema_fingerprint=authority.generated.fingerprint,
        current_semantic_revision=authority.curated.semantic_revision,
        embedding_fingerprint=diagnostics.embedding,
        model_runtime_version=diagnostics.runtime_version,
    )
    retriever = HybridRetriever(
        index=index,
        catalog=authority.assembled,
        embedding_model=embedding_model,
        embedding_fingerprint=diagnostics.embedding,
        model_runtime_version=diagnostics.runtime_version,
        lexical_top_k=settings.retrieval_lexical_top_k,
        semantic_top_k=settings.retrieval_semantic_top_k,
        seed_table_limit=settings.retrieval_seed_tables,
        max_relationship_hops=settings.max_relationship_hops,
        max_total_tables=settings.max_retrieved_tables,
        rrf_k=settings.retrieval_rrf_k,
    )
    runs = MySQLRunRepository(settings)
    uow = MySQLDialogueTurnStore(settings)
    admission = build_sql_admission_service(settings)
    query_runtime = build_readonly_query_runtime(settings)
    verifier = DeterministicVerifier()
    planner = QueryPlanner(
        chat_model=chat_model,
        model_fingerprint=diagnostics.chat.value,
        runtime_version=diagnostics.runtime_version,
    )
    dialogue = DialogueService(
        engine=DialogueEngine(chat_model=chat_model),
        store=uow,
        clock=lambda: datetime.now(UTC),
        id_factory=_id,
    )
    repair = BoundedRepairService(
        chat_model=chat_model,
        run_repository=runs,
        admission=admission,
        query_runtime=query_runtime,
        verifier=verifier,
        max_attempts=settings.max_sql_repair_attempts,
        model_fingerprint=diagnostics.chat.value,
        runtime_version=diagnostics.runtime_version,
    )
    orchestrator = ConversationOrchestrator(
        dialogue=dialogue,
        unit_of_work=uow,
        runs=runs,
        retriever=retriever,
        planner=planner,
        catalog=authority.assembled,
        retrieval_index_fingerprint=index.fingerprint,
        admission=admission,
        query_runtime=query_runtime,
        verifier=verifier,
        repair=repair,
        synthesizer=AnswerSynthesizer(
            chat_model=chat_model,
            max_context_rows=settings.max_answer_context_rows,
            max_context_bytes=settings.max_answer_context_bytes,
        ),
        clock=lambda: datetime.now(UTC),
        id_factory=_id,
    )
    return ConversationApplication(
        sessions=MySQLSessionRepository(settings),
        runs=runs,
        orchestrator=orchestrator,
    )
