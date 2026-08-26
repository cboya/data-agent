from datetime import timedelta

import pytest

from data_agent.config import Settings
from data_agent.contracts.message import MessageRole
from data_agent.contracts.requirement import RequirementState, RequirementStatus
from data_agent.contracts.run import RunStatus
from data_agent.contracts.session import Session
from data_agent.persistence.errors import DuplicateRecordError, OptimisticConcurrencyError
from data_agent.persistence.mysql.dialogue_turns import MySQLDialogueTurnStore
from data_agent.persistence.mysql.messages import MySQLMessageRepository
from data_agent.persistence.mysql.runs import MySQLRunRepository
from data_agent.persistence.mysql.sessions import MySQLSessionRepository
from tests.persistence.factories import message, requirement, run, session, timestamp

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


def test_dialogue_and_run_outcome_commit_in_one_transaction(settings: Settings) -> None:
    created = MySQLSessionRepository(settings).create(session())
    runs = MySQLRunRepository(settings)
    active_run = runs.create(run(created.session.id))
    runs.transition(
        str(active_run.id),
        RunStatus.UNDERSTANDING,
        transitioned_at=timestamp() + timedelta(minutes=1),
    )
    user = message(created.session.id, "需要澄清")
    assistant = message(
        created.session.id,
        "请选择指标",
        role=MessageRole.ASSISTANT,
    )

    stored = MySQLDialogueTurnStore(settings).commit_dialogue_with_run(
        session=_updated(created.session, status=RequirementStatus.CLARIFYING, minutes=2),
        expected_revision=created.revision,
        user_message=user,
        assistant_message=assistant,
        run_id=str(active_run.id),
        target=RunStatus.CLARIFYING,
    )

    assert stored.run.status is RunStatus.CLARIFYING
    assert runs.get(str(active_run.id)).status is RunStatus.CLARIFYING
    assert MySQLSessionRepository(settings).get(created.session.id).revision == 1
    assert [
        item.message
        for item in MySQLMessageRepository(settings).list_for_session(created.session.id)
    ] == [
        user,
        assistant,
    ]


def test_dialogue_insert_failure_rolls_back_run_outcome(settings: Settings) -> None:
    created = MySQLSessionRepository(settings).create(session())
    duplicate = message(created.session.id, "already persisted")
    MySQLMessageRepository(settings).append(duplicate)
    runs = MySQLRunRepository(settings)
    active_run = runs.create(run(created.session.id))
    runs.transition(
        str(active_run.id),
        RunStatus.UNDERSTANDING,
        transitioned_at=timestamp() + timedelta(minutes=1),
    )

    with pytest.raises(DuplicateRecordError):
        MySQLDialogueTurnStore(settings).commit_dialogue_with_run(
            session=_updated(created.session, status=RequirementStatus.READY, minutes=2),
            expected_revision=created.revision,
            user_message=message(
                created.session.id,
                "duplicate id",
                message_id=duplicate.id,
            ),
            assistant_message=None,
            run_id=str(active_run.id),
            target=RunStatus.RETRIEVING,
        )

    assert runs.get(str(active_run.id)).status is RunStatus.UNDERSTANDING
    assert MySQLSessionRepository(settings).get(created.session.id).revision == 0


def _advance_to_synthesizing(repository: MySQLRunRepository, run_id: str) -> None:
    for offset, status in enumerate(
        (
            RunStatus.UNDERSTANDING,
            RunStatus.RETRIEVING,
            RunStatus.PLANNING,
            RunStatus.VALIDATING,
            RunStatus.EXECUTING,
            RunStatus.VERIFYING,
            RunStatus.SYNTHESIZING,
        ),
        start=1,
    ):
        repository.transition(
            run_id,
            status,
            transitioned_at=timestamp() + timedelta(minutes=offset),
        )


def test_final_answer_and_run_completion_commit_in_one_transaction(
    settings: Settings,
) -> None:
    created = MySQLSessionRepository(settings).create(session())
    runs = MySQLRunRepository(settings)
    active_run = runs.create(run(created.session.id))
    _advance_to_synthesizing(runs, str(active_run.id))
    completed_at = timestamp() + timedelta(minutes=8)
    assistant = message(
        created.session.id,
        "已验证结果",
        role=MessageRole.ASSISTANT,
    ).model_copy(update={"created_at": completed_at})

    stored = MySQLDialogueTurnStore(settings).complete_run_with_message(
        run_id=str(active_run.id),
        assistant_message=assistant,
        completed_at=completed_at,
    )

    assert stored.run.status is RunStatus.COMPLETED
    assert runs.get(str(active_run.id)).status is RunStatus.COMPLETED
    assert (
        MySQLMessageRepository(settings).list_for_session(created.session.id)[0].message
        == assistant
    )


def test_final_message_failure_rolls_back_run_completion(settings: Settings) -> None:
    created = MySQLSessionRepository(settings).create(session())
    duplicate = message(created.session.id, "existing assistant", role=MessageRole.ASSISTANT)
    MySQLMessageRepository(settings).append(duplicate)
    runs = MySQLRunRepository(settings)
    active_run = runs.create(run(created.session.id))
    _advance_to_synthesizing(runs, str(active_run.id))
    completed_at = timestamp() + timedelta(minutes=8)

    with pytest.raises(DuplicateRecordError):
        MySQLDialogueTurnStore(settings).complete_run_with_message(
            run_id=str(active_run.id),
            assistant_message=message(
                created.session.id,
                "duplicate final",
                role=MessageRole.ASSISTANT,
                message_id=duplicate.id,
            ).model_copy(update={"created_at": completed_at}),
            completed_at=completed_at,
        )

    assert runs.get(str(active_run.id)).status is RunStatus.SYNTHESIZING
