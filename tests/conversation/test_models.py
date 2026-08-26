from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from data_agent.answer.proposal import CellReference
from data_agent.answer.service import (
    AnswerSynthesisMode,
    AnswerSynthesisResult,
)
from data_agent.contracts.execution import ExecutionResult
from data_agent.contracts.run import Run, RunStatus
from data_agent.conversation.models import build_result_response
from data_agent.verification.context import build_verification_context
from data_agent.verification.service import DeterministicVerifier
from tests.verification.factories import evidence_bundle


def test_result_response_preserves_decimal_assumptions_and_coverage() -> None:
    bundle = evidence_bundle()
    trace = DeterministicVerifier().verify(
        build_verification_context(
            planning_trace=bundle.planning_trace,
            guarded_query=bundle.guarded_query,
            execution_metadata=bundle.execution_metadata,
            execution_result=bundle.execution_result,
        )
    )
    response = build_result_response(
        session_id="session-m14",
        run=Run(
            id="run-m14",
            session_id="session-m14",
            status=RunStatus.COMPLETED,
            started_at=datetime(2026, 8, 26, tzinfo=UTC),
            completed_at=datetime(2026, 8, 26, tzinfo=UTC),
        ),
        planning_trace=bundle.planning_trace,
        guarded_query=bundle.guarded_query,
        execution_result=bundle.execution_result,
        verification_trace=trace,
        synthesis=AnswerSynthesisResult(
            answer="首日实付金额为 100.00。",
            evidence_refs=(CellReference(row_index=0, column_index=2),),
            mode=AnswerSynthesisMode.MODEL,
        ),
    )

    assert response.data.rows[0][2] == "100.00"
    assert isinstance(response.data.rows[0][2], str)
    assert str(Decimal("100.00")) == response.data.rows[0][2]
    assert response.assumptions.requirement == ()
    assert response.assumptions.query_plan == ()
    assert response.verification.scope == "COVERAGE_BOUNDED"
    assert response.verification.unsupported
    assert all("not_applicable" not in gap.name for gap in response.verification.unsupported)
    assert response.verification.coverage < 1.0
    encoded = response.model_dump_json()
    assert '"100.00"' in encoded


def test_failed_verification_cannot_build_result_response() -> None:
    result = ExecutionResult(
        version="v0.1",
        columns=["wrong"],
        rows=[],
        returned_row_count=0,
        duration_ms=1,
        truncated=False,
    )
    bundle = evidence_bundle(result=result)
    trace = DeterministicVerifier().verify(
        build_verification_context(
            planning_trace=bundle.planning_trace,
            guarded_query=bundle.guarded_query,
            execution_metadata=bundle.execution_metadata,
            execution_result=bundle.execution_result,
        )
    )

    assert trace.result.status == "FAILED"
