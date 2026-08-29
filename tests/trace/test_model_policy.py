from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from data_agent.answer.proposal import CellReference
from data_agent.answer.service import AnswerSynthesisMode, AnswerSynthesisResult
from data_agent.contracts.run import Run, RunStatus
from data_agent.contracts.verification import CheckResult, VerificationResult
from data_agent.trace.errors import TraceIntegrityError, TracePayloadError
from data_agent.trace.model import (
    EVENT_STAGE,
    TraceEvent,
    TraceEventDraft,
    TraceEventType,
    trace_payload_fingerprint,
)
from data_agent.trace.policy import TraceCompletenessPolicy
from data_agent.trace.projection import execution_payload, synthesis_payload, verification_payload
from data_agent.verification.evidence import VerificationEvidenceIdentity, VerificationTrace
from tests.verification.factories import evidence_bundle

NOW = datetime(2026, 8, 26, 18, tzinfo=UTC)


def _event(
    sequence: int,
    event_type: TraceEventType,
    *,
    attempt: int = 0,
    payload: dict[str, object] | None = None,
) -> TraceEvent:
    outcomes = {
        TraceEventType.RUN_RECEIVED: "RECEIVED",
        TraceEventType.VERIFICATION_COMPLETED: "PASSED",
        TraceEventType.RUN_TERMINATED: "TERMINATED",
    }
    actual_payload: dict[str, object] = {"outcome": outcomes.get(event_type, "SUCCEEDED")}
    actual_payload.update(payload or {})
    return TraceEvent(
        id=f"trace-{sequence}",
        session_id="session-m15",
        run_id="run-m15",
        sequence=sequence,
        attempt=attempt,
        stage=EVENT_STAGE[event_type],
        event_type=event_type,
        payload=actual_payload,
        occurred_at=NOW,
    )


def _run(status: RunStatus, *, repair_count: int = 0) -> Run:
    return Run(
        id="run-m15",
        session_id="session-m15",
        status=status,
        repair_count=repair_count,
        started_at=NOW,
        completed_at=NOW,
        error_code=None if status is RunStatus.COMPLETED else status.value,
    )


def test_trace_payload_is_canonical_and_rejects_sensitive_or_row_evidence() -> None:
    payload = {"result_fingerprint": "a" * 64, "returned_row_count": 2}
    draft = TraceEventDraft(
        id="trace-safe",
        session_id="session-m15",
        run_id="run-m15",
        attempt=0,
        stage=EVENT_STAGE[TraceEventType.EXECUTION_COMPLETED],
        event_type=TraceEventType.EXECUTION_COMPLETED,
        payload=payload,
        occurred_at=NOW,
    )

    assert draft.payload_fingerprint == trace_payload_fingerprint(payload)
    with pytest.raises(TracePayloadError, match="forbidden field"):
        TraceEventDraft(
            id="trace-unsafe",
            session_id="session-m15",
            run_id="run-m15",
            attempt=0,
            stage=EVENT_STAGE[TraceEventType.EXECUTION_COMPLETED],
            event_type=TraceEventType.EXECUTION_COMPLETED,
            payload={"nested": {"rows": [["sensitive"]]}},
            occurred_at=NOW,
        )
    with pytest.raises(TracePayloadError, match="not allowed"):
        TraceEventDraft(
            id="trace-untyped-data",
            session_id="session-m15",
            run_id="run-m15",
            attempt=0,
            stage=EVENT_STAGE[TraceEventType.EXECUTION_COMPLETED],
            event_type=TraceEventType.EXECUTION_COMPLETED,
            payload={"outcome": "SUCCEEDED", "data": [["sensitive"]]},
            occurred_at=NOW,
        )


def test_trace_revalidates_stage_and_persisted_payload_fingerprint() -> None:
    with pytest.raises(ValidationError, match="does not match its stage"):
        TraceEventDraft(
            id="trace-stage",
            session_id="session-m15",
            run_id="run-m15",
            attempt=0,
            stage=EVENT_STAGE[TraceEventType.RETRIEVAL_COMPLETED],
            event_type=TraceEventType.PLANNING_COMPLETED,
            payload={"outcome": "SUCCEEDED"},
            occurred_at=NOW,
        )
    with pytest.raises(ValidationError, match="fingerprint mismatch"):
        TraceEventDraft(
            id="trace-tamper",
            session_id="session-m15",
            run_id="run-m15",
            attempt=0,
            stage=EVENT_STAGE[TraceEventType.RETRIEVAL_COMPLETED],
            event_type=TraceEventType.RETRIEVAL_COMPLETED,
            payload={"outcome": "SUCCEEDED"},
            payload_fingerprint="f" * 64,
            occurred_at=NOW,
        )


def test_verification_projection_attributes_failed_checks_without_result_rows() -> None:
    result = VerificationResult(
        version="v0.1",
        status="FAILED",
        checks=[
            CheckResult(
                name="actual_columns_match_expected",
                category="STRUCTURAL",
                passed=False,
                detail="actual columns differ in name or order",
            )
        ],
    )
    trace = VerificationTrace(
        evidence=VerificationEvidenceIdentity(
            query_plan_fingerprint="1" * 64,
            guarded_query_fingerprint="2" * 64,
            execution_id="execution-m15",
            sql_digest="3" * 64,
            execution_namespace="data_agent",
            result_fingerprint_version="execution-result-fingerprint-v0.1",
            result_fingerprint="4" * 64,
        ),
        applied_checks=("actual_columns_match_expected",),
        coverage_gaps=(),
        result=result,
    )

    payload = verification_payload(trace)

    assert payload["outcome"] == "FAILED"
    assert payload["failed_checks"] == [
        {
            "name": "actual_columns_match_expected",
            "category": "STRUCTURAL",
            "detail": "actual columns differ in name or order",
        }
    ]
    assert "rows" not in payload


def test_execution_and_synthesis_projections_keep_bounded_evidence_only() -> None:
    bundle = evidence_bundle()
    execution = execution_payload(bundle.execution_metadata, result=bundle.execution_result)
    synthesis = synthesis_payload(
        AnswerSynthesisResult(
            answer="首日实付金额为 100.00。",
            evidence_refs=(CellReference(row_index=0, column_index=2),),
            mode=AnswerSynthesisMode.MODEL,
            proposal_fingerprint="a" * 64,
        ),
        assistant_message_id="message-m15",
    )

    assert execution["columns"] == ["period", "province", "paid_amount"]
    assert "rows" not in execution
    assert synthesis["answer_proposal_fingerprint"] == "a" * 64
    assert "answer" not in synthesis


def test_direct_success_and_clarification_have_frozen_complete_paths() -> None:
    direct_types = (
        TraceEventType.RUN_RECEIVED,
        TraceEventType.DIALOGUE_COMPLETED,
        TraceEventType.RETRIEVAL_COMPLETED,
        TraceEventType.PLANNING_COMPLETED,
        TraceEventType.SQL_ADMISSION_COMPLETED,
        TraceEventType.EXECUTION_COMPLETED,
        TraceEventType.VERIFICATION_COMPLETED,
        TraceEventType.SYNTHESIS_COMPLETED,
        TraceEventType.RUN_TERMINATED,
    )
    direct = tuple(
        _event(
            index,
            event_type,
            payload=(
                {"terminal_status": RunStatus.COMPLETED.value}
                if event_type is TraceEventType.RUN_TERMINATED
                else None
            ),
        )
        for index, event_type in enumerate(direct_types, start=1)
    )
    TraceCompletenessPolicy().validate(_run(RunStatus.COMPLETED), direct)

    clarification = (
        _event(1, TraceEventType.RUN_RECEIVED),
        _event(2, TraceEventType.DIALOGUE_COMPLETED),
        _event(
            3,
            TraceEventType.RUN_TERMINATED,
            payload={"terminal_status": RunStatus.CLARIFYING.value},
        ),
    )
    TraceCompletenessPolicy().validate(_run(RunStatus.CLARIFYING), clarification)


def test_repaired_success_requires_visible_original_and_attempt_one_branches() -> None:
    types = (
        TraceEventType.RUN_RECEIVED,
        TraceEventType.DIALOGUE_COMPLETED,
        TraceEventType.RETRIEVAL_COMPLETED,
        TraceEventType.PLANNING_COMPLETED,
        TraceEventType.SQL_ADMISSION_COMPLETED,
        TraceEventType.REPAIR_COMPLETED,
        TraceEventType.PLANNING_COMPLETED,
        TraceEventType.SQL_ADMISSION_COMPLETED,
        TraceEventType.EXECUTION_COMPLETED,
        TraceEventType.VERIFICATION_COMPLETED,
        TraceEventType.SYNTHESIS_COMPLETED,
        TraceEventType.RUN_TERMINATED,
    )
    events = tuple(
        _event(
            index,
            event_type,
            attempt=0 if index <= 5 else 1,
            payload=(
                {"terminal_status": RunStatus.COMPLETED.value}
                if event_type is TraceEventType.RUN_TERMINATED
                else (
                    {"eligible": True, "outcome": "SUCCEEDED"}
                    if event_type is TraceEventType.REPAIR_COMPLETED
                    else ({"outcome": "FAILED"} if index == 5 else None)
                )
            ),
        )
        for index, event_type in enumerate(types, start=1)
    )
    TraceCompletenessPolicy().validate(
        _run(RunStatus.COMPLETED, repair_count=1),
        events,
    )

    with pytest.raises(TraceIntegrityError, match="sequence"):
        TraceCompletenessPolicy().validate(
            _run(RunStatus.COMPLETED, repair_count=1),
            (*events[:7], events[8:][0], *events[9:]),
        )


def test_failed_repair_requires_typed_attempt_branch() -> None:
    prefix = tuple(
        _event(
            index,
            event_type,
            payload={"outcome": "FAILED"} if index == 5 else None,
        )
        for index, event_type in enumerate(
            (
                TraceEventType.RUN_RECEIVED,
                TraceEventType.DIALOGUE_COMPLETED,
                TraceEventType.RETRIEVAL_COMPLETED,
                TraceEventType.PLANNING_COMPLETED,
                TraceEventType.SQL_ADMISSION_COMPLETED,
            ),
            start=1,
        )
    )
    eligible = (
        *prefix,
        _event(
            6,
            TraceEventType.REPAIR_COMPLETED,
            attempt=1,
            payload={"eligible": True, "outcome": "MODEL_FAILED"},
        ),
        _event(
            7,
            TraceEventType.RUN_TERMINATED,
            attempt=1,
            payload={"terminal_status": RunStatus.REPAIR_EXHAUSTED.value},
        ),
    )
    TraceCompletenessPolicy().validate(_run(RunStatus.REPAIR_EXHAUSTED, repair_count=1), eligible)

    malformed = (
        *prefix,
        _event(
            6,
            TraceEventType.REPAIR_COMPLETED,
            payload={"eligible": True, "outcome": "MODEL_FAILED"},
        ),
        _event(
            7,
            TraceEventType.RUN_TERMINATED,
            payload={"terminal_status": RunStatus.REPAIR_EXHAUSTED.value},
        ),
    )
    with pytest.raises(TraceIntegrityError, match="attempt one"):
        TraceCompletenessPolicy().validate(
            _run(RunStatus.REPAIR_EXHAUSTED, repair_count=1), malformed
        )
