"""Provider-neutral dialogue engine and atomic durable turn composition."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from data_agent.contracts.dialogue import DialogueAction, DialogueDecision, DialogueProposal
from data_agent.contracts.message import Message, MessageRole
from data_agent.contracts.requirement import RequirementState, RequirementStatus
from data_agent.contracts.session import Session, SessionStatus
from data_agent.dialogue.context import DialogueContextBuilder
from data_agent.dialogue.merge import RequirementMerger
from data_agent.dialogue.policy import DialogueOutcome, DialoguePolicy
from data_agent.dialogue.prompt import DIALOGUE_PROMPT_VERSION
from data_agent.model_runtime.ports import ChatModel
from data_agent.persistence.ports import DialogueTurnStore, StoredDialogueTurn


class DialogueEngine:
    def __init__(
        self,
        *,
        chat_model: ChatModel,
        context_builder: DialogueContextBuilder | None = None,
        merger: RequirementMerger | None = None,
        policy: DialoguePolicy | None = None,
    ) -> None:
        self._chat_model = chat_model
        self._context_builder = context_builder or DialogueContextBuilder()
        self._merger = merger or RequirementMerger()
        self._policy = policy or DialoguePolicy()

    async def understand(
        self,
        *,
        requirement: RequirementState,
        latest_user_message: str,
        last_assistant_clarification: str | None = None,
    ) -> DialogueOutcome:
        decision = await self.propose(
            requirement=requirement,
            latest_user_message=latest_user_message,
            last_assistant_clarification=last_assistant_clarification,
        )
        return self.resolve(requirement=requirement, decision=decision)

    async def propose(
        self,
        *,
        requirement: RequirementState,
        latest_user_message: str,
        last_assistant_clarification: str | None = None,
    ) -> DialogueDecision:
        messages = self._context_builder.build(
            requirement=requirement,
            latest_user_message=latest_user_message,
            last_assistant_clarification=last_assistant_clarification,
        )
        proposal = await self._chat_model.structured(
            messages=messages,
            response_type=DialogueProposal,
            purpose=DIALOGUE_PROMPT_VERSION,
        )
        return proposal.to_decision()

    def resolve(
        self,
        *,
        requirement: RequirementState,
        decision: DialogueDecision,
    ) -> DialogueOutcome:
        merged = self._merger.merge(requirement, decision.patch)
        return self._policy.apply(decision=decision, merged=merged)


@dataclass(frozen=True)
class DialogueTurnResult:
    outcome: DialogueOutcome
    stored: StoredDialogueTurn


@dataclass(frozen=True)
class PreparedDialogueTurn:
    outcome: DialogueOutcome
    session: Session
    expected_revision: int
    user_message: Message
    assistant_message: Message | None


class DialogueService:
    def __init__(
        self,
        *,
        engine: DialogueEngine,
        store: DialogueTurnStore,
        clock: Callable[[], datetime],
        id_factory: Callable[[str], str],
    ) -> None:
        self._engine = engine
        self._store = store
        self._clock = clock
        self._id_factory = id_factory

    async def process_turn(self, *, session_id: str, user_content: str) -> DialogueTurnResult:
        prepared = await self.prepare_turn(session_id=session_id, user_content=user_content)
        stored = self._store.commit(
            session=prepared.session,
            expected_revision=prepared.expected_revision,
            user_message=prepared.user_message,
            assistant_message=prepared.assistant_message,
        )
        return DialogueTurnResult(outcome=prepared.outcome, stored=stored)

    async def prepare_turn(self, *, session_id: str, user_content: str) -> PreparedDialogueTurn:
        """Understand one turn without persisting it; M14 owns the atomic Run commit."""

        snapshot = self._store.load(session_id)
        if snapshot.session.session.status is not SessionStatus.ACTIVE:
            raise ValueError("dialogue turns require an ACTIVE Session")
        outcome = await self._engine.understand(
            requirement=snapshot.session.session.requirement,
            latest_user_message=user_content,
            last_assistant_clarification=(
                snapshot.last_assistant.message.content
                if snapshot.last_assistant is not None
                and snapshot.session.session.requirement.status is RequirementStatus.CLARIFYING
                else None
            ),
        )
        committed_at = self._clock()
        current_session = snapshot.session.session
        updated_session = Session.model_validate(
            {
                **current_session.model_dump(mode="python"),
                "requirement": outcome.requirement,
                "updated_at": committed_at,
            }
        )
        user_message = Message(
            id=self._id_factory("message"),
            session_id=session_id,
            role=MessageRole.USER,
            content=user_content,
            created_at=committed_at,
        )
        assistant_message = (
            Message(
                id=self._id_factory("message"),
                session_id=session_id,
                role=MessageRole.ASSISTANT,
                content=outcome.decision.question or "",
                created_at=committed_at,
            )
            if outcome.decision.action is DialogueAction.ASK_CLARIFICATION
            else None
        )
        return PreparedDialogueTurn(
            outcome=outcome,
            session=updated_session,
            expected_revision=snapshot.session.revision,
            user_message=user_message,
            assistant_message=assistant_message,
        )
