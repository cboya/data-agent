import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from data_agent.contracts.dialogue import DialogueAction, DialogueDecision
from data_agent.contracts.requirement import Ambiguity, RequirementPatch, RequirementStatus
from data_agent.contracts.session import Session, SessionStatus
from data_agent.dialogue.service import DialogueEngine, DialogueService
from data_agent.persistence.ports import (
    DialogueTurnSnapshot,
    StoredDialogueTurn,
    StoredMessage,
    StoredSession,
)
from tests.dialogue.factories import FixedDialogueModel, empty_requirement

NOW = datetime(2026, 8, 25, 16, 0, tzinfo=UTC)


@dataclass
class RecordingTurnStore:
    snapshot: DialogueTurnSnapshot
    committed: StoredDialogueTurn | None = None

    def load(self, session_id: str) -> DialogueTurnSnapshot:
        assert session_id == self.snapshot.session.session.id
        return self.snapshot

    def commit(
        self,
        *,
        session: Session,
        expected_revision: int,
        user_message: object,
        assistant_message: object,
    ) -> StoredDialogueTurn:
        from data_agent.contracts.message import Message

        assert isinstance(user_message, Message)
        assert assistant_message is None or isinstance(assistant_message, Message)
        assert expected_revision == self.snapshot.session.revision
        stored = StoredDialogueTurn(
            session=StoredSession(session=session, revision=expected_revision + 1),
            user_message=StoredMessage(message=user_message, sequence=1),
            assistant_message=(
                StoredMessage(message=assistant_message, sequence=2)
                if assistant_message is not None
                else None
            ),
        )
        self.committed = stored
        return stored


def test_service_persists_one_atomic_clarification_outcome() -> None:
    decision = DialogueDecision.model_validate(
        {
            "version": "v0.1",
            "patch": RequirementPatch(
                version="v0.2",
                unresolved_replace=[
                    Ambiguity(
                        field="metric",
                        reason="sales has multiple materially different definitions",
                        options=["paid_amount", "order_count", "gmv"],
                    )
                ],
            ).model_dump(mode="json"),
            "action": DialogueAction.ASK_CLARIFICATION,
            "question": "你想看实际支付金额、订单量还是 GMV?",
            "reason": "metric is blocking",
        }
    )
    session = Session(
        id="session-1",
        status=SessionStatus.ACTIVE,
        requirement=empty_requirement(),
        created_at=NOW,
        updated_at=NOW,
    )
    store = RecordingTurnStore(
        DialogueTurnSnapshot(
            session=StoredSession(session=session, revision=0), last_assistant=None
        )
    )
    model = FixedDialogueModel(decision)
    ids = iter(("message-user", "message-assistant"))
    service = DialogueService(
        engine=DialogueEngine(chat_model=model),
        store=store,
        clock=lambda: NOW,
        id_factory=lambda _: next(ids),
    )

    result = asyncio.run(
        service.process_turn(session_id="session-1", user_content="最近销售怎么样")
    )

    assert result.outcome.requirement.status is RequirementStatus.CLARIFYING
    assert result.stored.session.revision == 1
    assert result.stored.user_message.message.content == "最近销售怎么样"
    assert result.stored.assistant_message is not None
    assert result.stored.assistant_message.message.content == decision.question
    assert len(model.calls[0][0]) == 2
