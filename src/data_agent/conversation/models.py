"""Typed public M14 response envelopes assembled only from deterministic evidence."""

from __future__ import annotations

import math
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from data_agent.answer.service import AnswerSynthesisResult
from data_agent.contracts.execution import ExecutionResult
from data_agent.contracts.run import Run, RunStatus
from data_agent.contracts.session import Session, SessionStatus
from data_agent.planning.service import PlanningTrace
from data_agent.sql_guard.capability import GuardedQuery
from data_agent.verification.evidence import CoverageDisposition, VerificationTrace

type JsonCell = str | bool | int | float | None


class _PublicModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class SessionView(_PublicModel):
    id: str
    status: SessionStatus
    requirement: dict[str, object]
    revision: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_session(cls, session: Session, *, revision: int) -> SessionView:
        return cls(
            id=str(session.id),
            status=session.status,
            requirement=session.requirement.model_dump(mode="json"),
            revision=revision,
            created_at=session.created_at,
            updated_at=session.updated_at,
        )


class RunView(_PublicModel):
    id: str
    session_id: str
    status: RunStatus
    repair_count: int = Field(ge=0)
    started_at: datetime
    completed_at: datetime | None
    error_code: str | None

    @classmethod
    def from_run(cls, run: Run) -> RunView:
        return cls.model_validate(run.model_dump(mode="python"))


class ClarificationResponse(_PublicModel):
    type: Literal["clarification"] = "clarification"
    session_id: str
    run_id: str
    question: str
    requirement: dict[str, object]


class ResultData(_PublicModel):
    columns: tuple[str, ...]
    rows: tuple[tuple[JsonCell, ...], ...]


class AssumptionEvidence(_PublicModel):
    requirement: tuple[str, ...]
    query_plan: tuple[str, ...]


class QueryEvidence(_PublicModel):
    tables: tuple[str, ...]
    sql: str
    query_duration_ms: int = Field(ge=0)
    returned_row_count: int = Field(ge=0)
    repair_count: int = Field(ge=0)


class UnsupportedVerificationGap(_PublicModel):
    category: Literal["STRUCTURAL", "SEMANTIC", "EMPIRICAL"]
    name: str
    detail: str


class VerificationEvidence(_PublicModel):
    status: Literal["PASSED"]
    scope: Literal["COVERAGE_BOUNDED"] = "COVERAGE_BOUNDED"
    policy_version: str
    coverage: float = Field(ge=0.0, le=1.0)
    unsupported: tuple[UnsupportedVerificationGap, ...]


class SynthesisEvidence(_PublicModel):
    mode: Literal["MODEL", "DETERMINISTIC_FALLBACK"]
    limitation: str | None = None


class ResultResponse(_PublicModel):
    type: Literal["result"] = "result"
    session_id: str
    run_id: str
    answer: str
    data: ResultData
    assumptions: AssumptionEvidence
    evidence: QueryEvidence
    verification: VerificationEvidence
    synthesis: SynthesisEvidence


class FailureResponse(_PublicModel):
    type: Literal["failure"] = "failure"
    session_id: str
    run_id: str
    code: str
    message: str
    status: RunStatus


ConversationResponse = Annotated[
    ClarificationResponse | ResultResponse | FailureResponse,
    Field(discriminator="type"),
]


def _json_cell(value: object) -> JsonCell:
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("non-finite Decimal cannot cross the conversation API")
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite float cannot cross the conversation API")
        return value
    if isinstance(value, datetime):
        return value.isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    raise ValueError(f"unsupported result value for API: {type(value).__name__}")


def _verification_evidence(trace: VerificationTrace) -> VerificationEvidence:
    if trace.result.status != "PASSED":
        raise ValueError("failed verification cannot build a result response")
    unsupported = tuple(
        UnsupportedVerificationGap(
            category=gap.category,
            name=str(gap.name),
            detail=str(gap.detail),
        )
        for gap in trace.coverage_gaps
        if gap.disposition is CoverageDisposition.UNSUPPORTED
    )
    applicable = len(trace.applied_checks) + len(unsupported)
    coverage = 1.0 if applicable == 0 else len(trace.applied_checks) / applicable
    return VerificationEvidence(
        status="PASSED",
        policy_version=str(trace.verification_policy_version),
        coverage=coverage,
        unsupported=unsupported,
    )


def build_result_response(
    *,
    session_id: str,
    run: Run,
    planning_trace: PlanningTrace,
    guarded_query: GuardedQuery,
    execution_result: ExecutionResult,
    verification_trace: VerificationTrace,
    synthesis: AnswerSynthesisResult,
) -> ResultResponse:
    if run.status is not RunStatus.COMPLETED:
        raise ValueError("result response requires a completed Run")
    if run.session_id != session_id:
        raise ValueError("result Run belongs to another Session")
    return ResultResponse(
        session_id=session_id,
        run_id=str(run.id),
        answer=synthesis.answer,
        data=ResultData(
            columns=tuple(str(value) for value in execution_result.columns),
            rows=tuple(tuple(_json_cell(value) for value in row) for row in execution_result.rows),
        ),
        assumptions=AssumptionEvidence(
            requirement=tuple(
                str(value) for value in planning_trace.context.requirement.assumptions
            ),
            query_plan=tuple(str(value) for value in planning_trace.plan.assumptions),
        ),
        evidence=QueryEvidence(
            tables=tuple(value.qualified_name for value in guarded_query.physical_tables),
            sql=guarded_query.sql,
            query_duration_ms=execution_result.duration_ms,
            returned_row_count=execution_result.returned_row_count,
            repair_count=run.repair_count,
        ),
        verification=_verification_evidence(verification_trace),
        synthesis=SynthesisEvidence(
            mode=synthesis.mode.value,
            limitation=synthesis.reason,
        ),
    )
