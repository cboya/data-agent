from datetime import timedelta

import pytest

from data_agent.config import Settings
from data_agent.contracts.message import MessageRole
from data_agent.contracts.requirement import RequirementState, RequirementStatus
from data_agent.contracts.session import Session
from data_agent.persistence.errors import DuplicateRecordError, OptimisticConcurrencyError
from data_agent.persistence.mysql.dialogue_turns import MySQLDialogueTurnStore
from data_agent.persistence.mysql.messages import MySQLMessageRepository
from data_agent.persistence.mysql.sessions import MySQLSessionRepository
from tests.persistence.factories import message, requirement, session

pytestmark = pytest.mark.integration


def _updated(current: Session, *, status: RequirementStatus, minutes: int) -> Session:
    requirement_value = RequirementState.model_validate(
        {**requirement().model_dump(mode="python"), "status": status}
    )
    return Session.model_validate(
        {
            **current.model_dump(mode="python"),
            "requirement": requirement_value,
            "updated_at": current.updated_at + timedelta(minutes=minutes),
        }
    )


def test_dialogue_turn_atomically_updates_session_and_appends_messages(
    settings: Settings,
) -> None:
    created = MySQLSessionRepository(settings).create(session())
    user = message(created.session.id, "最近销售怎么样")
    assistant = message(
        created.session.id,
        "你想看实际支付金额、订单量还是 GMV?",
        role=MessageRole.ASSISTANT,
    )
    stored = MySQLDialogueTurnStore(settings).commit(
        session=_updated(created.session, status=RequirementStatus.CLARIFYING, minutes=1),
        expected_revision=created.revision,
        user_message=user,
        assistant_message=assistant,
    )

    reloaded = MySQLSessionRepository(settings).get(created.session.id)
    messages = MySQLMessageRepository(settings).list_for_session(created.session.id)
    assert stored.session.revision == 1
    assert reloaded.session.requirement.status is RequirementStatus.CLARIFYING
    assert [value.sequence for value in messages] == [1, 2]
    assert [value.message for value in messages] == [user, assistant]


def test_stale_dialogue_revision_rolls_back_all_messages(settings: Settings) -> None:
    session_repository = MySQLSessionRepository(settings)
    created = session_repository.create(session())
    stale = MySQLDialogueTurnStore(settings).load(created.session.id)
    session_repository.update(
        _updated(created.session, status=RequirementStatus.READY, minutes=1),
        expected_revision=created.revision,
    )

    with pytest.raises(OptimisticConcurrencyError, match="expected 0"):
        MySQLDialogueTurnStore(settings).commit(
            session=_updated(created.session, status=RequirementStatus.CLARIFYING, minutes=2),
            expected_revision=stale.session.revision,
            user_message=message(created.session.id, "stale user message"),
            assistant_message=None,
        )

    assert MySQLMessageRepository(settings).list_for_session(created.session.id) == []
    assert session_repository.get(created.session.id).revision == 1


def test_message_insert_failure_rolls_back_session_update(settings: Settings) -> None:
    session_repository = MySQLSessionRepository(settings)
    created = session_repository.create(session())
    duplicate = message(created.session.id, "already persisted")
    MySQLMessageRepository(settings).append(duplicate)

    with pytest.raises(DuplicateRecordError):
        MySQLDialogueTurnStore(settings).commit(
            session=_updated(created.session, status=RequirementStatus.CLARIFYING, minutes=1),
            expected_revision=created.revision,
            user_message=message(
                created.session.id,
                "duplicate id",
                message_id=duplicate.id,
            ),
            assistant_message=None,
        )

    reloaded = session_repository.get(created.session.id)
    messages = MySQLMessageRepository(settings).list_for_session(created.session.id)
    assert reloaded.revision == 0
    assert reloaded.session.requirement.status is RequirementStatus.READY
    assert [value.message for value in messages] == [duplicate]
