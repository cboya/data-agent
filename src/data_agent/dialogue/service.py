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
from data_agent.dialogue.policy import (
    BlockingAmbiguityPolicy,
    BlockingPolicyResult,
    DialogueOutcome,
    DialoguePolicy,
)
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
        blocking_policy: BlockingAmbiguityPolicy | None = None,
    ) -> None:
        self._chat_model = chat_model
        self._context_builder = context_builder or DialogueContextBuilder()
        self._merger = merger or RequirementMerger()
        self._policy = policy or DialoguePolicy()
        self._blocking_policy = blocking_policy or BlockingAmbiguityPolicy()

    async def understand(
        self,
        *,
        requirement: RequirementState,
        latest_user_message: str,
        last_assistant_clarification: str | None = None,
    ) -> DialogueOutcome:
        proposal = await self._request_proposal(
            requirement=requirement,
            latest_user_message=latest_user_message,
            last_assistant_clarification=last_assistant_clarification,
        )
        return self.resolve_proposal(
            requirement=requirement,
            proposal=proposal,
            latest_user_message=latest_user_message,
        )

    async def propose(
        self,
        *,
        requirement: RequirementState,
        latest_user_message: str,
        last_assistant_clarification: str | None = None,
    ) -> DialogueDecision:
        proposal = await self._request_proposal(
            requirement=requirement,
            latest_user_message=latest_user_message,
            last_assistant_clarification=last_assistant_clarification,
        )
        return self.resolve_proposal(
            requirement=requirement,
            proposal=proposal,
            latest_user_message=latest_user_message,
        ).decision

    async def _request_proposal(
        self,
        *,
        requirement: RequirementState,
        latest_user_message: str,
        last_assistant_clarification: str | None = None,
    ) -> DialogueProposal:
        messages = self._context_builder.build(
            requirement=requirement,
            latest_user_message=latest_user_message,
            last_assistant_clarification=last_assistant_clarification,
        )
        return await self._chat_model.structured(
            messages=messages,
            response_type=DialogueProposal,
            purpose=DIALOGUE_PROMPT_VERSION,
        )

    def resolve_proposal(
        self,
        *,
        requirement: RequirementState,
        proposal: DialogueProposal,
        latest_user_message: str,
    ) -> DialogueOutcome:
        candidate_patch = proposal.to_candidate_patch()
        candidate_merged = self._merger.merge(requirement, candidate_patch)
        blocking = self._blocking_policy.evaluate(
            requirement=requirement,
            merged=candidate_merged,
            proposal=proposal,
            latest_user_message=latest_user_message,
        )
        decision = self._final_decision(proposal=proposal, blocking=blocking)
        merged = self._merger.merge(requirement, decision.patch)
        outcome = self._policy.apply(decision=decision, merged=merged)
        return DialogueOutcome(
            decision=outcome.decision,
            requirement=outcome.requirement,
            blocking=blocking,
        )

    @staticmethod
    def _final_decision(
        *,
        proposal: DialogueProposal,
        blocking: BlockingPolicyResult,
    ) -> DialogueDecision:
        patch = proposal.to_requirement_patch(blocking=blocking.blocking_candidates)
        if not blocking.has_blocking:
            action = DialogueAction.READY
            question = None
        elif proposal.resolution.action is DialogueAction.CANNOT_RESOLVE:
            action = DialogueAction.CANNOT_RESOLVE
            question = None
        else:
            action = DialogueAction.ASK_CLARIFICATION
            question = proposal.resolution.question
        reason_codes = ",".join(assessment.reason_code.value for assessment in blocking.assessments)
        return DialogueDecision.model_validate(
            {
                "version": proposal.version,
                "patch": patch.model_dump(mode="json"),
                "action": action,
                "question": question,
                "reason": f"blocking-ambiguity-policy:{reason_codes or 'NO_CANDIDATES'}",
            }
        )

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
