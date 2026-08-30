"""Deterministic M15 behavioral-attribution invariants."""

import hashlib
import json

from eval_harness.attribution import (
    AttributionError,
    BehavioralAttributionReport,
    TerminalBucket,
    build_attribution,
)
from eval_harness.loader import REPOSITORY_ROOT, load_golden
from eval_harness.models import (
    EvaluationEnvironmentV02,
    FinalAcceptanceReport,
    GoldenCase,
    GoldenCaseResult,
    GoldenMetrics,
    GoldenReport,
)


def _passing_result(case: GoldenCase, index: int) -> GoldenCaseResult:
    response_types = tuple(turn.expected_type for turn in case.turns)
    run_ids = tuple(f"run_{index}_{turn}" for turn in range(len(case.turns)))
    statuses = tuple(
        "COMPLETED"
        if turn.expected_type == "result"
        else "CLARIFYING"
        if turn.expected_type == "clarification"
        else "FAILED"
        for turn in case.turns
    )
    error_codes = tuple(
        "DIALOGUE_CANNOT_RESOLVE" if turn.expected_type == "failure" else None
        for turn in case.turns
    )
    failed_events = tuple(
        f"{run_id}:attempt=0:DIALOGUE:DIALOGUE_COMPLETED:CANNOT_RESOLVE"
        for run_id, turn in zip(run_ids, case.turns, strict=True)
        if turn.expected_type == "failure"
    )
    return GoldenCaseResult(
        id=case.id,
        category=case.category,
        passed=True,
        session_id=f"session_{index}",
        response_types=response_types,
        run_ids=run_ids,
        run_statuses=statuses,
        run_error_codes=error_codes,
        trace_event_ids=tuple(f"trace_{index}_{turn}" for turn in range(len(case.turns))),
        trace_payload_fingerprints=tuple("a" * 64 for _ in case.turns),
        failed_trace_events=failed_events,
        observed_tables=case.required_tables,
        observed_columns=case.expected_columns,
        failure_stage=None,
        oracle_passed=True if case.oracle is not None else None,
        trace_passed=True,
        repair_count=0,
        errors=(),
    )


def _source_report(
    *, mutations: dict[str, dict[str, object]] | None = None
) -> FinalAcceptanceReport:
    suite, golden_fingerprint = load_golden()
    results = []
    for index, case in enumerate(suite.cases):
        result = _passing_result(case, index)
        if mutations and case.id in mutations:
            result = result.model_copy(update=mutations[case.id])
        results.append(result)
    environment = EvaluationEnvironmentV02.model_construct(
        fingerprint="b" * 64,
        git_commit="c" * 40,
        golden_fingerprint=golden_fingerprint,
    )
    golden = GoldenReport.model_construct(
        version="golden-report-v0.1",
        environment=environment,
        metrics=GoldenMetrics(
            case_count=len(results),
            result_case_count=sum(result.oracle_passed is not None for result in results),
            e2e_pass_rate=sum(result.passed for result in results) / len(results),
            result_oracle_pass_rate=(
                sum(result.oracle_passed is True for result in results)
                / sum(result.oracle_passed is not None for result in results)
            ),
            trace_integrity_rate=1,
            unnecessary_clarification_rate=0,
            unauthorized_execution_count=0,
            failed_verification_synthesis_count=0,
            numeric_grounding_violation_count=0,
            repair_bound_violation_count=0,
            verified_oracle_mismatch_count=0,
        ),
        cases=tuple(results),
        passed=True,
    )
    return FinalAcceptanceReport.model_construct(
        version="mvp-acceptance-v0.1",
        environment=environment,
        stages={"dialogue": {"metrics": {"unnecessary_clarification_rate": 0.0}}},
        golden=golden,
        passed=True,
    )


def _bucket_counts(report: BehavioralAttributionReport) -> dict[TerminalBucket, int]:
    return {item.bucket: item.count for item in report.terminal_buckets}


def test_attribution_partitions_all_cases_and_never_invents_missing_causes() -> None:
    suite, golden_fingerprint = load_golden()
    base = {result.id: result for result in _source_report().golden.cases}
    mutations: dict[str, dict[str, object]] = {
        "simple-paid-order-count": {
            "passed": False,
            "response_types": ("clarification",),
            "run_statuses": ("CLARIFYING",),
            "oracle_passed": False,
            "failure_stage": "RESULT_ORACLE",
            "errors": ("turn 1: expected result, received clarification",),
        },
        "simple-gmv": {
            "passed": False,
            "oracle_passed": False,
            "observed_columns": ("channel", "gmv"),
            "failure_stage": "RESULT_ORACLE",
            "errors": ("public result did not match the trusted result Oracle",),
        },
        "trap-gmv-versus-paid": {
            "passed": False,
            "response_types": ("failure",),
            "run_statuses": ("FAILED",),
            "run_error_codes": ("PIPELINE_FAILED",),
            "failed_trace_events": (
                f"{base['trap-gmv-versus-paid'].run_ids[0]}:attempt=0:PLANNING:"
                "PLANNING_COMPLETED:FAILED",
            ),
            "oracle_passed": False,
            "failure_stage": "PLANNING",
            "errors": ("turn 1: expected result, received failure",),
        },
        "agg-users-province": {
            "passed": False,
            "response_types": ("failure",),
            "run_statuses": ("REPAIR_EXHAUSTED",),
            "run_error_codes": ("REPAIR_ADMISSION_FAILED",),
            "failed_trace_events": (
                f"{base['agg-users-province'].run_ids[0]}:attempt=0:SQL_ADMISSION:"
                "SQL_ADMISSION_COMPLETED:FAILED",
                f"{base['agg-users-province'].run_ids[0]}:attempt=1:REPAIR:"
                "REPAIR_COMPLETED:ADMISSION_FAILED",
            ),
            "oracle_passed": False,
            "failure_stage": "SQL_ADMISSION",
            "repair_count": 1,
            "errors": ("turn 1: expected result, received failure",),
        },
        "simple-user-count": {
            "passed": False,
            "observed_tables": (),
            "failure_stage": "PUBLIC_ASSERTION",
            "errors": ("required tables missing",),
        },
    }
    source = _source_report(mutations=mutations)
    attributed = build_attribution(source, suite, golden_fingerprint=golden_fingerprint)
    counts = _bucket_counts(attributed)

    assert sum(counts.values()) == 59
    assert counts[TerminalBucket.UNEXPECTED_CLARIFICATION] == 1
    assert counts[TerminalBucket.ORACLE_MISMATCH_AFTER_VERIFIED_RUN] == 1
    assert counts[TerminalBucket.PLANNING_FAILURE] == 1
    assert counts[TerminalBucket.REPAIR_EXHAUSTED] == 1
    assert counts[TerminalBucket.PUBLIC_EVIDENCE_ASSERTION] == 1
    assert attributed.dialogue.blocker_field_counts["evidence_unavailable"] == 1
    assert attributed.dialogue.exact_same_input_comparison_count == 0
    planning = next(
        item for item in attributed.structured_model_calls if item.purpose == "planning"
    )
    assert planning.unclassified_failure == 1
    assert planning.timeout == 0
    assert planning.output_bound_or_truncation == 0
    assert attributed.m12_passed_oracle_failed_case_ids == ("simple-gmv",)
    assert attributed.oracle_mismatches[0].classification == "grain"


def test_attribution_is_deterministic_and_fails_closed_on_identity_drift() -> None:
    suite, golden_fingerprint = load_golden()
    source = _source_report()

    first = build_attribution(source, suite, golden_fingerprint=golden_fingerprint)
    second = build_attribution(source, suite, golden_fingerprint=golden_fingerprint)

    assert first.fingerprint == second.fingerprint
    assert first.dialogue.confusion.total_turns == 63
    assert sum(item.count for item in first.terminal_buckets) == 59
    try:
        build_attribution(source, suite, golden_fingerprint="d" * 64)
    except AttributionError as error:
        assert "Golden fingerprint" in str(error)
    else:
        raise AssertionError("Golden fingerprint drift must fail closed")


def test_committed_attribution_evidence_is_strict_complete_and_fingerprinted() -> None:
    path = REPOSITORY_ROOT / "docs" / "evidence" / "M15-BEHAVIORAL-ATTRIBUTION-3be2534.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    report = BehavioralAttributionReport.model_validate(raw)
    canonical = json.dumps(
        {key: value for key, value in raw.items() if key != "fingerprint"},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )

    assert report.total_cases == 59
    assert sum(bucket.count for bucket in report.terminal_buckets) == 59
    assert report.fingerprint == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert report.funnel.unexpected_clarification_cases == 35
    assert len(report.m12_passed_oracle_failed_case_ids) == 6
