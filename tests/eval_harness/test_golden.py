from __future__ import annotations

from datetime import UTC, datetime

from data_agent.trace.model import EVENT_STAGE, TraceEvent, TraceEventType
from eval_harness.golden import (
    _canonical_rows,
    _numeric_grounding_violations,
    _trace_gate_counts,
)
from eval_harness.loader import load_golden, load_oracles

GOLDEN_FINGERPRINT = "53d969d1196877829cc89ee3070d75a1fea6ba88bfd5986fbe66beb21fcf93f7"


def _event(
    sequence: int,
    event_type: TraceEventType,
    payload: dict[str, object],
) -> TraceEvent:
    return TraceEvent(
        id=f"trace-eval-{sequence}",
        session_id="session-eval",
        run_id="run-eval",
        sequence=sequence,
        attempt=0,
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
