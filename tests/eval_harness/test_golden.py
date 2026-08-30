from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, cast

import pytest

import eval_harness.golden as golden_module
from data_agent.trace.model import EVENT_STAGE, TraceEvent, TraceEventType
from eval_harness.golden import (
    _canonical_rows,
    _numeric_grounding_violations,
    _passes_golden_gates,
    _trace_gate_counts,
    _verified_oracle_mismatch,
    run_golden,
)
from eval_harness.loader import load_golden, load_oracles
from eval_harness.models import EvaluationEnvironmentV01, GoldenCaseResult, GoldenMetrics

GOLDEN_FINGERPRINT = "53d969d1196877829cc89ee3070d75a1fea6ba88bfd5986fbe66beb21fcf93f7"


def _event(
    sequence: int,
    event_type: TraceEventType,
    payload: dict[str, object],
    *,
    attempt: Literal[0, 1] = 0,
) -> TraceEvent:
    return TraceEvent(
        id=f"trace-eval-{sequence}",
        session_id="session-eval",
        run_id="run-eval",
        sequence=sequence,
        attempt=attempt,
        stage=EVENT_STAGE[event_type],
        event_type=event_type,
        payload=payload,
        occurred_at=datetime(2026, 8, 26, tzinfo=UTC),
    )


def test_frozen_golden_has_exact_category_and_oracle_coverage() -> None:
    golden, fingerprint = load_golden()
    oracles = load_oracles(golden)

    assert len(golden.cases) == 59
    assert fingerprint == GOLDEN_FINGERPRINT
    assert {case.category for case in golden.cases} == {
        "simple",
        "aggregation",
        "join_trap",
        "multi_turn",
        "failure",
        "repair_empty",
    }
    assert set(oracles.queries) == {case.oracle for case in golden.cases if case.oracle is not None}
    repair_cases = [case for case in golden.cases if case.category == "repair_empty"]
    assert [case.id for case in repair_cases] == [
        "empty-future-orders",
        "empty-future-paid",
        "repair-users-province",
    ]
    empty_cases = [case for case in golden.cases if case.id.startswith("empty-")]
    assert [case.id for case in empty_cases] == ["empty-future-orders", "empty-future-paid"]


def test_oracle_comparison_distinguishes_empty_rows_from_wrong_columns() -> None:
    assert _canonical_rows(("value",), (), ("value",)) == ()
    assert _canonical_rows(("wrong",), (), ("value",)) is None
    assert _canonical_rows(("b", "a"), ((2, 1),), ("a", "b")) == ("[1, 2]",)


def test_numeric_grounding_gate_uses_persisted_synthesis_references() -> None:
    event = _event(
        1,
        TraceEventType.SYNTHESIS_COMPLETED,
        {
            "outcome": "SUCCEEDED",
            "evidence_refs": [{"row_index": 0, "column_index": 0}],
        },
    )
    grounded = {"answer": "实际支付金额为 100.00。", "data": {"rows": [["100.00"]]}}
    invented = {"answer": "实际支付金额为 999.00。", "data": {"rows": [["100.00"]]}}

    assert _numeric_grounding_violations(grounded, (event,)) == 0
    assert _numeric_grounding_violations(invented, (event,)) == 1


def test_trace_gate_rejects_execution_without_same_attempt_admission() -> None:
    execution = _event(
        1,
        TraceEventType.EXECUTION_COMPLETED,
        {"outcome": "SUCCEEDED"},
    )
    assert _trace_gate_counts((execution,)) == (1, 0, 0)


def test_verified_oracle_mismatch_uses_persisted_final_passed_verification() -> None:
    failed_verification = _event(
        1,
        TraceEventType.VERIFICATION_COMPLETED,
        {"outcome": "FAILED"},
    )
    passed_verification = _event(
        2,
        TraceEventType.VERIFICATION_COMPLETED,
        {"outcome": "PASSED"},
        attempt=1,
    )
    final_synthesis = _event(
        3,
        TraceEventType.SYNTHESIS_COMPLETED,
        {"outcome": "SUCCEEDED"},
        attempt=1,
    )
    events = (failed_verification, passed_verification, final_synthesis)

    assert _verified_oracle_mismatch(oracle_passed=False, events=events) == 1
    assert _verified_oracle_mismatch(oracle_passed=True, events=events) == 0
    assert _verified_oracle_mismatch(oracle_passed=False, events=events[:-1]) == 0


def test_verified_oracle_mismatch_overrides_passing_behavioral_rates() -> None:
    passing_rates = GoldenMetrics(
        case_count=59,
        result_case_count=55,
        e2e_pass_rate=54 / 59,
        result_oracle_pass_rate=50 / 55,
        trace_integrity_rate=1.0,
        unnecessary_clarification_rate=0.0,
        unauthorized_execution_count=0,
        failed_verification_synthesis_count=0,
        numeric_grounding_violation_count=0,
        repair_bound_violation_count=0,
        verified_oracle_mismatch_count=0,
    )

    assert _passes_golden_gates(passing_rates)
    assert not _passes_golden_gates(
        passing_rates.model_copy(update={"verified_oracle_mismatch_count": 1})
    )


def test_run_golden_aggregates_verified_oracle_mismatch_into_exact_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suite, _ = load_golden()
    oracles = load_oracles(suite)
    mismatched_case_id = "simple-order-count"

    def fake_run_case(**kwargs: Any) -> tuple[GoldenCaseResult, int, int, int, int, int, int]:
        case = kwargs["case"]
        mismatch = int(case.id == mismatched_case_id)
        oracle_passed = None if case.oracle is None else not mismatch
        return (
            GoldenCaseResult(
                id=case.id,
                category=case.category,
                passed=not mismatch,
                session_id=f"session-{case.id}",
                response_types=tuple(turn.expected_type for turn in case.turns),
                run_ids=(),
                run_statuses=(),
                run_error_codes=(),
                trace_event_ids=(),
                trace_payload_fingerprints=(),
                failed_trace_events=(),
                observed_tables=case.required_tables,
                observed_columns=case.expected_columns,
                failure_stage="RESULT_ORACLE" if mismatch else None,
                oracle_passed=oracle_passed,
                trace_passed=True,
                repair_count=0,
                errors=("trusted Oracle mismatch",) if mismatch else (),
            ),
            0,
            0,
            0,
            0,
            0,
            mismatch,
        )

    monkeypatch.setattr(golden_module, "_run_case", fake_run_case)
    report = run_golden(
        client=cast(Any, None),
        settings=cast(Any, None),
        suite=suite,
        oracles=oracles,
        environment=EvaluationEnvironmentV01.model_construct(),
    )

    assert report.metrics.e2e_pass_rate >= 0.90
    assert report.metrics.result_oracle_pass_rate >= 0.90
    assert report.metrics.verified_oracle_mismatch_count == 1
    assert not report.passed
