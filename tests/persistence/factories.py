from datetime import UTC, datetime
from uuid import uuid4

import pymysql
from pymysql.connections import Connection

from data_agent.config import Settings, require_mysql_admin_password
from data_agent.contracts.artifact import Artifact, ArtifactType
from data_agent.contracts.message import Message, MessageRole
from data_agent.contracts.requirement import (
    MetricRequirement,
    RequirementState,
    RequirementStatus,
    ResolutionStatus,
    TimeRange,
)
from data_agent.contracts.run import Run, RunStatus
from data_agent.contracts.session import Session, SessionStatus


def unique_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def timestamp(minute: int = 0) -> datetime:
    return datetime(2026, 8, 25, 13, minute, tzinfo=UTC)


def requirement(*, goal: str = "最近30天实际支付金额") -> RequirementState:
    return RequirementState(
        version="v0.1",
        goal=goal,
        metrics=[
            MetricRequirement(
                term="实际支付金额",
                resolved_name="paid_amount",
                definition="成功支付订单金额",
                status=ResolutionStatus.CONFIRMED,
            )
        ],
        time_range=TimeRange(kind="RELATIVE", value="最近30天"),
        grain="day",
        status=RequirementStatus.READY,
    )


def session(*, session_id: str | None = None) -> Session:
    now = timestamp()
    return Session(
        id=session_id or unique_id("session"),
        status=SessionStatus.ACTIVE,
        requirement=requirement(),
        created_at=now,
        updated_at=now,
    )


def message(
    session_id: str,
    content: str,
    *,
    role: MessageRole = MessageRole.USER,
    message_id: str | None = None,
) -> Message:
    return Message(
        id=message_id or unique_id("message"),
        session_id=session_id,
        role=role,
        content=content,
        created_at=timestamp(),
    )


def run(session_id: str, *, run_id: str | None = None) -> Run:
    return Run(
        id=run_id or unique_id("run"),
        session_id=session_id,
        status=RunStatus.RECEIVED,
        started_at=timestamp(),
    )


def artifact(session_id: str, run_id: str, *, artifact_id: str | None = None) -> Artifact:
    return Artifact(
        id=artifact_id or unique_id("artifact"),
        session_id=session_id,
        run_id=run_id,
        type=ArtifactType.REQUIREMENT_STATE,
        contract_version="v0.1",
        payload=requirement().model_dump(mode="json"),
        created_at=timestamp(),
    )


def admin_connection(settings: Settings, *, database: str | None = None) -> Connection:
    return pymysql.connect(
        host=settings.mysql_control_host,
        port=settings.mysql_control_port,
        user="root",
        password=require_mysql_admin_password(settings, operation="test control admin connection"),
        database=database,
        charset="utf8mb4",
        autocommit=True,
        connect_timeout=3,
        read_timeout=5,
        write_timeout=5,
    )
