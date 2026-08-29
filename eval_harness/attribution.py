"""Deterministic, eval-only attribution for a completed M15 acceptance report."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from eval_harness.loader import REPOSITORY_ROOT, load_golden
from eval_harness.models import FinalAcceptanceReport, GoldenCase, GoldenCaseResult, GoldenSuite

SOURCE_REPORT_PATH = REPOSITORY_ROOT / "evals" / "reports" / "latest.json"
ATTRIBUTION_JSON_PATH = REPOSITORY_ROOT / "evals" / "reports" / "attribution-latest.json"
ATTRIBUTION_MARKDOWN_PATH = REPOSITORY_ROOT / "evals" / "reports" / "attribution-latest.md"


class AttributionError(RuntimeError):
    """The source report cannot support deterministic attribution."""


class _AttributionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class TerminalBucket(StrEnum):
    PASS = "PASS"
    UNEXPECTED_CLARIFICATION = "UNEXPECTED_CLARIFICATION"
    DIALOGUE_STRUCTURED_FAILURE = "DIALOGUE_STRUCTURED_FAILURE"
    RETRIEVAL_FAILURE = "RETRIEVAL_FAILURE"
    PLANNING_FAILURE = "PLANNING_FAILURE"
    SQL_ADMISSION_FAILURE = "SQL_ADMISSION_FAILURE"
    EXECUTION_FAILURE = "EXECUTION_FAILURE"
    VERIFICATION_FAILURE = "VERIFICATION_FAILURE"
    REPAIR_EXHAUSTED = "REPAIR_EXHAUSTED"
    ANSWER_SYNTHESIS_FAILURE = "ANSWER_SYNTHESIS_FAILURE"
    ORACLE_MISMATCH_AFTER_VERIFIED_RUN = "ORACLE_MISMATCH_AFTER_VERIFIED_RUN"
    PUBLIC_EVIDENCE_ASSERTION = "PUBLIC_EVIDENCE_ASSERTION"


class CaseAttribution(_AttributionModel):
    case_id: str
    bucket: TerminalBucket
    owner_milestones: tuple[str, ...]
    failure_codes: tuple[str, ...]
    run_ids: tuple[str, ...]
    trace_event_ids: tuple[str, ...]


class BucketAttribution(_AttributionModel):
    bucket: TerminalBucket
    count: int = Field(ge=0)
    cases: tuple[CaseAttribution, ...]

    @model_validator(mode="after")
    def count_matches_cases(self) -> Self:
        if self.count != len(self.cases):
            raise ValueError("terminal bucket count does not match its cases")
        return self


class StageFunnel(_AttributionModel):
    received: int = Field(ge=0)
    expected_safe_dialogue_terminal: int = Field(ge=0)
    dialogue_ready: int = Field(ge=0)
    unexpected_clarification_cases: int = Field(ge=0)
    unexpected_clarification_turns: int = Field(ge=0)
    dialogue_structured_failure: int = Field(ge=0)
    retrieval_pass: int = Field(ge=0)
    planning_pass: int = Field(ge=0)
    admission_pass: int = Field(ge=0)
    execution_pass: int = Field(ge=0)
    verification_pass: int = Field(ge=0)
    repair_entered: int = Field(ge=0)
    synthesis_pass: int = Field(ge=0)
    oracle_reached: int = Field(ge=0)
    oracle_pass: int = Field(ge=0)
    golden_pass: int = Field(ge=0)


class DialogueConfusionMatrix(_AttributionModel):
    expected_ready_actual_ready: int = Field(ge=0)
    expected_ready_actual_clarify: int = Field(ge=0)
    expected_clarify_actual_ready: int = Field(ge=0)
    expected_clarify_actual_clarify: int = Field(ge=0)
    expected_ready_actual_dialogue_failure: int = Field(ge=0)
    expected_failure_actual_failure: int = Field(ge=0)
    total_turns: int = Field(ge=0)

    @model_validator(mode="after")
    def matrix_covers_every_turn(self) -> Self:
        cells = (
            self.expected_ready_actual_ready
            + self.expected_ready_actual_clarify
            + self.expected_clarify_actual_ready
            + self.expected_clarify_actual_clarify
            + self.expected_ready_actual_dialogue_failure
            + self.expected_failure_actual_failure
        )
        if cells != self.total_turns:
            raise ValueError("dialogue confusion matrix does not cover every turn")
        return self


class UnexpectedClarificationCase(_AttributionModel):
    case_id: str
    unexpected_turns: tuple[int, ...]
    blocker_fields: tuple[str, ...] = ()
    blocker_evidence: Literal["AVAILABLE", "UNAVAILABLE_IN_SOURCE_REPORT"]
    standalone_comparison: Literal["MATCH", "MISMATCH", "NOT_REPLAYED"]
    ownership_assessment: str
    run_ids: tuple[str, ...]
    trace_event_ids: tuple[str, ...]


class DialogueAttribution(_AttributionModel):
    confusion: DialogueConfusionMatrix
    blocker_field_counts: dict[str, int]
    unexpected_cases: tuple[UnexpectedClarificationCase, ...]
    exact_same_input_comparison_count: int = Field(ge=0)
    comparison_not_replayed_count: int = Field(ge=0)
    single_turn_same_entrypoint_count: int = Field(ge=0)
    stateful_multi_turn_unresolved_count: int = Field(ge=0)
    standalone_stage_unnecessary_clarification_rate: float | None = Field(default=None, ge=0, le=1)
    e2e_unnecessary_clarification_rate: float = Field(ge=0, le=1)
    evidence_limitation: str


class StructuredCallOutcome(_AttributionModel):
    purpose: Literal["dialogue", "planning", "repair", "answer"]
    inferred_calls: int = Field(ge=0)
    successful_structured_output: int = Field(ge=0)
    timeout: int = Field(ge=0)
    output_bound_or_truncation: int = Field(ge=0)
    invalid_json_or_schema: int = Field(ge=0)
    provider_error: int = Field(ge=0)
    unclassified_failure: int = Field(ge=0)
    evidence_status: Literal["EXACT_STAGE_OUTCOME_CAUSE_PARTIAL"]

    @model_validator(mode="after")
    def outcomes_cover_calls(self) -> Self:
        outcomes = (
            self.successful_structured_output
            + self.timeout
            + self.output_bound_or_truncation
            + self.invalid_json_or_schema
            + self.provider_error
            + self.unclassified_failure
        )
        if outcomes != self.inferred_calls:
            raise ValueError("structured-call outcomes do not cover inferred calls")
        return self


class OracleMismatch(_AttributionModel):
    case_id: str
    classification: Literal[
        "metric", "filter", "time", "grain", "join", "fan_out", "shape", "value"
    ]
    m12_passed: bool
    expected_columns: tuple[str, ...]
    observed_columns: tuple[str, ...]
    required_tables: tuple[str, ...]
    observed_tables: tuple[str, ...]
    run_ids: tuple[str, ...]
    trace_event_ids: tuple[str, ...]


class MilestoneRecommendation(_AttributionModel):
    rank: int = Field(ge=1)
    milestones: tuple[str, ...]
    case_ids: tuple[str, ...]
    expected_case_impact: int = Field(ge=1)
    rationale: str


class BehavioralAttributionReport(_AttributionModel):
    version: Literal["behavioral-attribution-v0.1"] = "behavioral-attribution-v0.1"
    source_report_version: str
    source_environment_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_git_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    golden_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    total_cases: int = Field(ge=1)
    funnel: StageFunnel
    terminal_buckets: tuple[BucketAttribution, ...]
    dialogue: DialogueAttribution
    structured_model_calls: tuple[StructuredCallOutcome, ...]
    oracle_mismatches: tuple[OracleMismatch, ...]
    m12_passed_oracle_failed_case_ids: tuple[str, ...]
    milestone_recommendations: tuple[MilestoneRecommendation, ...]
    evidence_limitations: tuple[str, ...]
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def terminal_partition_is_exact(self) -> Self:
        attributed = [case.case_id for bucket in self.terminal_buckets for case in bucket.cases]
        if len(attributed) != self.total_cases or len(set(attributed)) != self.total_cases:
            raise ValueError("terminal attribution is not an exact case partition")
        if self.funnel.received != self.total_cases:
            raise ValueError("stage funnel does not start with every Golden case")
        return self


@dataclass(frozen=True)
class _FailedEvent:
    run_id: str
    stage: str
    outcome: str


def _parse_failed_event(value: str) -> _FailedEvent:
    parts = value.split(":", maxsplit=4)
    if len(parts) != 5 or not parts[1].startswith("attempt="):
        raise AttributionError(f"invalid failed trace event projection: {value}")
    return _FailedEvent(run_id=parts[0], stage=parts[2], outcome=parts[4])


def _failed_events(result: GoldenCaseResult) -> tuple[_FailedEvent, ...]:
    return tuple(_parse_failed_event(value) for value in result.failed_trace_events)


def _run_failed_stage(result: GoldenCaseResult, run_id: str) -> str | None:
    return next((event.stage for event in _failed_events(result) if event.run_id == run_id), None)


def _actual_dialogue_outcome(
    result: GoldenCaseResult,
    *,
    turn_index: int,
) -> Literal["READY", "CLARIFY", "DIALOGUE_FAILURE", "FAILURE"]:
    response_type = result.response_types[turn_index]
    if response_type == "clarification":
        return "CLARIFY"
    if response_type == "result":
        return "READY"
    run_id = result.run_ids[turn_index]
    error_code = result.run_error_codes[turn_index]
    failed_stage = _run_failed_stage(result, run_id)
    if error_code == "DIALOGUE_CANNOT_RESOLVE":
        return "FAILURE"
    if failed_stage == "DIALOGUE":
        return "DIALOGUE_FAILURE"
    return "READY"


def _validate_case_alignment(case: GoldenCase, result: GoldenCaseResult) -> None:
    expected = len(case.turns)
    observed_lengths = (
        len(result.response_types),
        len(result.run_ids),
        len(result.run_statuses),
        len(result.run_error_codes),
    )
    if any(length != expected for length in observed_lengths):
        raise AttributionError(
            f"case {case.id} lacks per-turn public/Run evidence: expected={expected}, "
            f"observed={observed_lengths}"
        )


def _unexpected_turns(case: GoldenCase, result: GoldenCaseResult) -> tuple[int, ...]:
    return tuple(
        index + 1
        for index, (turn, response_type) in enumerate(
            zip(case.turns, result.response_types, strict=True)
        )
        if turn.expected_type != "clarification" and response_type == "clarification"
    )


def _failure_codes(result: GoldenCaseResult) -> tuple[str, ...]:
    values = [value for value in result.run_error_codes if value is not None]
    values.extend(f"{event.stage}:{event.outcome}" for event in _failed_events(result))
    return tuple(dict.fromkeys(values))


def _terminal_bucket(case: GoldenCase, result: GoldenCaseResult) -> TerminalBucket:
    if result.passed:
        return TerminalBucket.PASS
    if _unexpected_turns(case, result):
        return TerminalBucket.UNEXPECTED_CLARIFICATION
    if result.response_types[-1] == "result" and result.oracle_passed is False:
        return TerminalBucket.ORACLE_MISMATCH_AFTER_VERIFIED_RUN
    if any(status == "REPAIR_EXHAUSTED" for status in result.run_statuses):
        return TerminalBucket.REPAIR_EXHAUSTED
    stage = result.failure_stage
    mapping = {
        "DIALOGUE": TerminalBucket.DIALOGUE_STRUCTURED_FAILURE,
        "RETRIEVAL": TerminalBucket.RETRIEVAL_FAILURE,
        "PLANNING": TerminalBucket.PLANNING_FAILURE,
        "SQL_ADMISSION": TerminalBucket.SQL_ADMISSION_FAILURE,
        "EXECUTION": TerminalBucket.EXECUTION_FAILURE,
        "VERIFICATION": TerminalBucket.VERIFICATION_FAILURE,
        "REPAIR": TerminalBucket.REPAIR_EXHAUSTED,
        "SYNTHESIS": TerminalBucket.ANSWER_SYNTHESIS_FAILURE,
        "PUBLIC_ASSERTION": TerminalBucket.PUBLIC_EVIDENCE_ASSERTION,
    }
    if stage in mapping:
        return mapping[stage]
    raise AttributionError(f"case {case.id} has no deterministic terminal attribution: {stage}")


def _owner_milestones(bucket: TerminalBucket, result: GoldenCaseResult) -> tuple[str, ...]:
    fixed = {
        TerminalBucket.PASS: (),
        TerminalBucket.UNEXPECTED_CLARIFICATION: ("M8",),
        TerminalBucket.DIALOGUE_STRUCTURED_FAILURE: ("M8", "M4"),
        TerminalBucket.RETRIEVAL_FAILURE: ("M7",),
        TerminalBucket.PLANNING_FAILURE: ("M9",),
        TerminalBucket.SQL_ADMISSION_FAILURE: ("M10",),
        TerminalBucket.EXECUTION_FAILURE: ("M11",),
        TerminalBucket.VERIFICATION_FAILURE: ("M12",),
        TerminalBucket.ANSWER_SYNTHESIS_FAILURE: ("M14",),
        TerminalBucket.ORACLE_MISMATCH_AFTER_VERIFIED_RUN: ("M9", "M12"),
        TerminalBucket.PUBLIC_EVIDENCE_ASSERTION: ("M9", "M12"),
    }
    if bucket is not TerminalBucket.REPAIR_EXHAUSTED:
        return fixed[bucket]
    source_stages = {event.stage for event in _failed_events(result)}
    owners = ["M13"]
    for stage, milestone in (
        ("SQL_ADMISSION", "M10"),
        ("EXECUTION", "M11"),
        ("VERIFICATION", "M12"),
    ):
        if stage in source_stages:
            owners.append(milestone)
    return tuple(owners)


def _build_terminal_buckets(
    suite: GoldenSuite,
    results: dict[str, GoldenCaseResult],
) -> tuple[BucketAttribution, ...]:
    grouped: dict[TerminalBucket, list[CaseAttribution]] = {bucket: [] for bucket in TerminalBucket}
    for case in suite.cases:
        result = results[case.id]
        bucket = _terminal_bucket(case, result)
        grouped[bucket].append(
            CaseAttribution(
                case_id=case.id,
                bucket=bucket,
                owner_milestones=_owner_milestones(bucket, result),
                failure_codes=_failure_codes(result),
                run_ids=result.run_ids,
                trace_event_ids=result.trace_event_ids,
            )
        )
    return tuple(
        BucketAttribution(bucket=bucket, count=len(grouped[bucket]), cases=tuple(grouped[bucket]))
        for bucket in TerminalBucket
    )


def _build_dialogue(
    report: FinalAcceptanceReport,
    suite: GoldenSuite,
    results: dict[str, GoldenCaseResult],
) -> DialogueAttribution:
    cells: Counter[str] = Counter()
    unexpected_cases: list[UnexpectedClarificationCase] = []
    single_turn_same_entrypoint = 0
    stateful_multi_turn = 0
    for case in suite.cases:
        result = results[case.id]
        turns = _unexpected_turns(case, result)
        if turns:
            single_turn = len(case.turns) == 1 and turns == (1,)
            single_turn_same_entrypoint += int(single_turn)
            stateful_multi_turn += int(not single_turn)
            unexpected_cases.append(
                UnexpectedClarificationCase(
                    case_id=case.id,
                    unexpected_turns=turns,
                    blocker_evidence="UNAVAILABLE_IN_SOURCE_REPORT",
                    standalone_comparison="NOT_REPLAYED",
                    ownership_assessment=(
                        "M8_DIALOGUE_MODEL_OR_GOLDEN_DISTRIBUTION_SAME_EMPTY_STATE_ENTRYPOINT"
                        if single_turn
                        else "M8_OR_STATEFUL_INTEGRATION_UNRESOLVED_WITHOUT_SAME_INPUT_REPLAY"
                    ),
                    run_ids=result.run_ids,
                    trace_event_ids=result.trace_event_ids,
                )
            )
        for index, turn in enumerate(case.turns):
            expected = (
                "READY"
                if turn.expected_type == "result"
                else "CLARIFY"
                if turn.expected_type == "clarification"
                else "FAILURE"
            )
            actual = _actual_dialogue_outcome(result, turn_index=index)
            if expected == "FAILURE" and actual == "FAILURE":
                cells["EXPECTED_FAILURE_ACTUAL_FAILURE"] += 1
            elif expected == "READY" and actual == "DIALOGUE_FAILURE":
                cells["EXPECTED_READY_ACTUAL_DIALOGUE_FAILURE"] += 1
            else:
                cells[f"EXPECTED_{expected}_ACTUAL_{actual}"] += 1

    dialogue_metrics = report.stages.get("dialogue", {}).get("metrics", {})
    standalone_rate = dialogue_metrics.get("unnecessary_clarification_rate")
    if standalone_rate is not None and not isinstance(standalone_rate, int | float):
        raise AttributionError("standalone dialogue metric has an invalid type")
    total_turns = sum(len(case.turns) for case in suite.cases)
    confusion = DialogueConfusionMatrix(
        expected_ready_actual_ready=cells["EXPECTED_READY_ACTUAL_READY"],
        expected_ready_actual_clarify=cells["EXPECTED_READY_ACTUAL_CLARIFY"],
        expected_clarify_actual_ready=cells["EXPECTED_CLARIFY_ACTUAL_READY"],
        expected_clarify_actual_clarify=cells["EXPECTED_CLARIFY_ACTUAL_CLARIFY"],
        expected_ready_actual_dialogue_failure=cells["EXPECTED_READY_ACTUAL_DIALOGUE_FAILURE"],
        expected_failure_actual_failure=cells["EXPECTED_FAILURE_ACTUAL_FAILURE"],
        total_turns=total_turns,
    )
    unavailable_turns = sum(len(case.unexpected_turns) for case in unexpected_cases)
    return DialogueAttribution(
        confusion=confusion,
        blocker_field_counts={
            "metric": 0,
            "time_range": 0,
            "grain": 0,
            "dimension": 0,
            "filter": 0,
            "comparison": 0,
            "other": 0,
            "evidence_unavailable": unavailable_turns,
        },
        unexpected_cases=tuple(unexpected_cases),
        exact_same_input_comparison_count=0,
        comparison_not_replayed_count=len(unexpected_cases),
        single_turn_same_entrypoint_count=single_turn_same_entrypoint,
        stateful_multi_turn_unresolved_count=stateful_multi_turn,
        standalone_stage_unnecessary_clarification_rate=(
            None if standalone_rate is None else float(standalone_rate)
        ),
        e2e_unnecessary_clarification_rate=report.golden.metrics.unnecessary_clarification_rate,
        evidence_limitation=(
            "Golden report v0.1 does not persist clarification blocker fields or same-input "
            "standalone replay outcomes; the completed model environment was not rerun."
        ),
    )


def _build_funnel(
    suite: GoldenSuite,
    results: dict[str, GoldenCaseResult],
) -> StageFunnel:
    dialogue_ready: set[str] = set()
    dialogue_failure: set[str] = set()
    retrieval_pass: set[str] = set()
    planning_pass: set[str] = set()
    admission_pass: set[str] = set()
    execution_pass: set[str] = set()
    verification_pass: set[str] = set()
    synthesis_pass: set[str] = set()
    oracle_reached: set[str] = set()
    oracle_pass: set[str] = set()
    for case in suite.cases:
        result = results[case.id]
        for index, run_id in enumerate(result.run_ids):
            actual = _actual_dialogue_outcome(result, turn_index=index)
            if actual == "DIALOGUE_FAILURE":
                dialogue_failure.add(case.id)
            if actual != "READY":
                continue
            dialogue_ready.add(case.id)
            failed_stage = _run_failed_stage(result, run_id)
            if failed_stage != "RETRIEVAL":
                retrieval_pass.add(case.id)
            if failed_stage not in {"RETRIEVAL", "PLANNING"}:
                planning_pass.add(case.id)
            response_type = result.response_types[index]
            if response_type == "result" or failed_stage not in {
                "RETRIEVAL",
                "PLANNING",
                "SQL_ADMISSION",
            }:
                admission_pass.add(case.id)
            if response_type == "result" or failed_stage in {"VERIFICATION", "SYNTHESIS"}:
                execution_pass.add(case.id)
            if response_type == "result" or failed_stage == "SYNTHESIS":
                verification_pass.add(case.id)
            if response_type == "result":
                synthesis_pass.add(case.id)
                oracle_reached.add(case.id)
        if result.oracle_passed is True:
            oracle_pass.add(case.id)
    unexpected = {case.id for case in suite.cases if _unexpected_turns(case, results[case.id])}
    return StageFunnel(
        received=len(suite.cases),
        expected_safe_dialogue_terminal=sum(
            case.turns[-1].expected_type == "failure" and results[case.id].passed
            for case in suite.cases
        ),
        dialogue_ready=len(dialogue_ready),
        unexpected_clarification_cases=len(unexpected),
        unexpected_clarification_turns=sum(
            len(_unexpected_turns(case, results[case.id])) for case in suite.cases
        ),
        dialogue_structured_failure=len(dialogue_failure),
        retrieval_pass=len(retrieval_pass),
        planning_pass=len(planning_pass),
        admission_pass=len(admission_pass),
        execution_pass=len(execution_pass),
        verification_pass=len(verification_pass),
        repair_entered=sum(
            result.repair_count > 0
            or any(event.stage == "REPAIR" for event in _failed_events(result))
            for result in results.values()
        ),
        synthesis_pass=len(synthesis_pass),
        oracle_reached=len(oracle_reached),
        oracle_pass=len(oracle_pass),
        golden_pass=sum(result.passed for result in results.values()),
    )


def _classified_model_failures(codes: tuple[str, ...]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for code in codes:
        normalized = code.upper()
        if "TIMEOUT" in normalized:
            counts["timeout"] += 1
        elif "TRUNCAT" in normalized or "OUTPUT_BOUND" in normalized:
            counts["output_bound_or_truncation"] += 1
        elif "JSON" in normalized or "SCHEMA" in normalized or "CONTRACT" in normalized:
            counts["invalid_json_or_schema"] += 1
        elif "PROVIDER" in normalized or "TRANSPORT" in normalized:
            counts["provider_error"] += 1
        else:
            counts["unclassified_failure"] += 1
    return counts


def _call_outcome(
    purpose: Literal["dialogue", "planning", "repair", "answer"],
    calls: int,
    successful: int,
    failure_codes: tuple[str, ...],
) -> StructuredCallOutcome:
    classified = _classified_model_failures(failure_codes)
    if sum(classified.values()) != calls - successful:
        raise AttributionError(f"{purpose} structured-call evidence does not balance")
    return StructuredCallOutcome(
        purpose=purpose,
        inferred_calls=calls,
        successful_structured_output=successful,
        timeout=classified["timeout"],
        output_bound_or_truncation=classified["output_bound_or_truncation"],
        invalid_json_or_schema=classified["invalid_json_or_schema"],
        provider_error=classified["provider_error"],
        unclassified_failure=classified["unclassified_failure"],
        evidence_status="EXACT_STAGE_OUTCOME_CAUSE_PARTIAL",
    )


def _build_structured_calls(
    suite: GoldenSuite,
    results: dict[str, GoldenCaseResult],
) -> tuple[StructuredCallOutcome, ...]:
    dialogue_calls = dialogue_success = 0
    planning_calls = planning_success = 0
    answer_calls = answer_success = 0
    dialogue_failures: list[str] = []
    planning_failures: list[str] = []
    answer_failures: list[str] = []
    repair_calls = sum(result.repair_count for result in results.values())
    repair_failures: list[str] = []
    for case in suite.cases:
        result = results[case.id]
        events = _failed_events(result)
        for index, run_id in enumerate(result.run_ids):
            dialogue_calls += 1
            actual = _actual_dialogue_outcome(result, turn_index=index)
            stage = _run_failed_stage(result, run_id)
            if actual == "DIALOGUE_FAILURE":
                dialogue_failures.append(result.run_error_codes[index] or "UNCLASSIFIED")
                continue
            dialogue_success += 1
            if actual != "READY" or stage == "RETRIEVAL":
                continue
            planning_calls += 1
            if stage == "PLANNING":
                planning_failures.append(result.run_error_codes[index] or "UNCLASSIFIED")
                continue
            planning_success += 1
            if result.response_types[index] == "result":
                answer_calls += 1
                answer_success += 1
            elif stage == "SYNTHESIS":
                answer_calls += 1
                answer_failures.append(result.run_error_codes[index] or "UNCLASSIFIED")
        repair_failures.extend(
            event.outcome
            for event in events
            if event.stage == "REPAIR" and "MODEL" in event.outcome.upper()
        )
    repair_success = repair_calls - len(repair_failures)
    return (
        _call_outcome("dialogue", dialogue_calls, dialogue_success, tuple(dialogue_failures)),
        _call_outcome("planning", planning_calls, planning_success, tuple(planning_failures)),
        _call_outcome("repair", repair_calls, repair_success, tuple(repair_failures)),
        _call_outcome("answer", answer_calls, answer_success, tuple(answer_failures)),
    )


def _oracle_classification(case: GoldenCase, result: GoldenCaseResult) -> str:
    expected = set(case.expected_columns)
    observed = set(result.observed_columns)
    if expected < observed:
        return "grain"
    if expected != observed:
        return "shape"
    if not set(case.required_tables).issubset(result.observed_tables):
        return "join"
    return "value"


def _build_oracle_mismatches(
    suite: GoldenSuite,
    results: dict[str, GoldenCaseResult],
) -> tuple[OracleMismatch, ...]:
    mismatches: list[OracleMismatch] = []
    for case in suite.cases:
        result = results[case.id]
        if result.response_types[-1] != "result" or result.oracle_passed is not False:
            continue
        if result.run_statuses[-1] != "COMPLETED" or not result.trace_passed:
            raise AttributionError(f"Oracle mismatch {case.id} lacks verified completed evidence")
        mismatches.append(
            OracleMismatch(
                case_id=case.id,
                classification=_oracle_classification(case, result),  # type: ignore[arg-type]
                m12_passed=True,
                expected_columns=case.expected_columns,
                observed_columns=result.observed_columns,
                required_tables=case.required_tables,
                observed_tables=result.observed_tables,
                run_ids=result.run_ids,
                trace_event_ids=result.trace_event_ids,
            )
        )
    return tuple(mismatches)


def _case_ids_for(
    buckets: tuple[BucketAttribution, ...],
    *selected: TerminalBucket,
) -> tuple[str, ...]:
    wanted = set(selected)
    return tuple(
        case.case_id for bucket in buckets if bucket.bucket in wanted for case in bucket.cases
    )


def _recommendations(
    buckets: tuple[BucketAttribution, ...],
    dialogue: DialogueAttribution,
) -> tuple[MilestoneRecommendation, ...]:
    m8_ids = tuple(case.case_id for case in dialogue.unexpected_cases)
    semantic_ids = _case_ids_for(
        buckets,
        TerminalBucket.ORACLE_MISMATCH_AFTER_VERIFIED_RUN,
        TerminalBucket.PUBLIC_EVIDENCE_ASSERTION,
        TerminalBucket.PLANNING_FAILURE,
    )
    repair_ids = _case_ids_for(
        buckets,
        TerminalBucket.REPAIR_EXHAUSTED,
        TerminalBucket.SQL_ADMISSION_FAILURE,
    )
    answer_ids = _case_ids_for(buckets, TerminalBucket.ANSWER_SYNTHESIS_FAILURE)
    candidates = (
        (
            ("M8",),
            m8_ids,
            (
                "Unexpected clarification is the dominant multiplier; blocker fields require "
                "future non-secret diagnostic capture before remediation."
            ),
        ),
        (
            ("M9", "M12"),
            semantic_ids,
            (
                "Verified results with Oracle/public-evidence mismatch require planner-semantic "
                "ownership and verification-coverage review."
            ),
        ),
        (
            ("M13", "M10", "M12"),
            repair_ids,
            "Terminal admission/verification repair branches exhausted or were denied.",
        ),
        (
            ("M14",),
            answer_ids,
            "Verified empty/aggregation results failed structured answer synthesis.",
        ),
    )
    recommendations: list[MilestoneRecommendation] = []
    for milestones, case_ids, rationale in candidates:
        if not case_ids:
            continue
        recommendations.append(
            MilestoneRecommendation(
                rank=len(recommendations) + 1,
                milestones=milestones,
                case_ids=case_ids,
                expected_case_impact=len(case_ids),
                rationale=rationale,
            )
        )
    return tuple(recommendations)


def build_attribution(
    report: FinalAcceptanceReport,
    suite: GoldenSuite,
    *,
    golden_fingerprint: str,
) -> BehavioralAttributionReport:
    if report.golden.environment.golden_fingerprint != golden_fingerprint:
        raise AttributionError("source report does not bind the current frozen Golden fingerprint")
    results = {result.id: result for result in report.golden.cases}
    expected_ids = [case.id for case in suite.cases]
    if len(results) != len(report.golden.cases) or set(results) != set(expected_ids):
        raise AttributionError("source report does not exactly cover the frozen Golden cases")
    for case in suite.cases:
        _validate_case_alignment(case, results[case.id])
    buckets = _build_terminal_buckets(suite, results)
    dialogue = _build_dialogue(report, suite, results)
    oracle_mismatches = _build_oracle_mismatches(suite, results)
    candidate = BehavioralAttributionReport(
        source_report_version=report.version,
        source_environment_fingerprint=report.environment.fingerprint,
        source_git_commit=report.environment.git_commit,
        golden_fingerprint=golden_fingerprint,
        total_cases=len(suite.cases),
        funnel=_build_funnel(suite, results),
        terminal_buckets=buckets,
        dialogue=dialogue,
        structured_model_calls=_build_structured_calls(suite, results),
        oracle_mismatches=oracle_mismatches,
        m12_passed_oracle_failed_case_ids=tuple(item.case_id for item in oracle_mismatches),
        milestone_recommendations=_recommendations(buckets, dialogue),
        evidence_limitations=(
            "Golden report v0.1 stores trace IDs and payload fingerprints, not trace payloads; "
            "the clean reset removed the source run rows before this attribution pass.",
            "Clarification blocker fields are absent, so no blocker category is inferred "
            "from case text.",
            "Generic pipeline failure codes do not distinguish timeout, output-bound, invalid "
            "structured output, and provider failures.",
            "Same-input standalone M8 replay was not run under the completed large-model "
            "environment.",
        ),
        fingerprint="0" * 64,
    )
    canonical = json.dumps(
        candidate.model_dump(mode="json", exclude={"fingerprint"}),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return candidate.model_copy(
        update={"fingerprint": hashlib.sha256(canonical.encode("utf-8")).hexdigest()}
    )


def format_attribution_summary(report: BehavioralAttributionReport) -> str:
    lines = [
        "# M15 Behavioral Failure Attribution",
        "",
        f"Source environment: `{report.source_environment_fingerprint}`  ",
        f"Source Git: `{report.source_git_commit}`  ",
        f"Attribution fingerprint: `{report.fingerprint}`",
        "",
        "## Stage funnel",
        "",
        "> Counts mean a case reached/passed the stage at least once. Multi-turn side branches are "
        "reported separately and are not an attrition partition.",
        "",
        "| Evidence | Cases |",
        "| --- | ---: |",
    ]
    for label, value in report.funnel.model_dump().items():
        lines.append(f"| {label} | {value} |")
    lines.extend(
        [
            "",
            "## Mutually exclusive terminal attribution",
            "",
            "| Bucket | Count | Case IDs |",
            "| --- | ---: | --- |",
        ]
    )
    for bucket in report.terminal_buckets:
        ids = ", ".join(case.case_id for case in bucket.cases) or "—"
        lines.append(f"| {bucket.bucket.value} | {bucket.count} | {ids} |")
    confusion = report.dialogue.confusion
    lines.extend(
        [
            "",
            "## Dialogue outcome matrix",
            "",
            "| Expected / actual | READY | CLARIFY | DIALOGUE FAILURE |",
            "| --- | ---: | ---: | ---: |",
            (
                "| READY | "
                f"{confusion.expected_ready_actual_ready} | "
                f"{confusion.expected_ready_actual_clarify} | "
                f"{confusion.expected_ready_actual_dialogue_failure} |"
            ),
            (
                "| CLARIFY | "
                f"{confusion.expected_clarify_actual_ready} | "
                f"{confusion.expected_clarify_actual_clarify} | 0 |"
            ),
            "",
            "Expected safe terminal failures observed: "
            f"{confusion.expected_failure_actual_failure}.",
            "",
            "All unexpected-clarification blocker fields are marked `evidence_unavailable`: the "
            "v0.1 source report did not persist the public clarification requirement/question or "
            "trace payload. No field was guessed from the user text.",
            "",
            "Unexpected clarification cases:",
            "",
        ]
    )
    lines.extend(
        f"- `{case.case_id}` turns={list(case.unexpected_turns)} runs={list(case.run_ids)} "
        f"trace_ids={list(case.trace_event_ids)}"
        for case in report.dialogue.unexpected_cases
    )
    lines.extend(
        [
            "",
            "Same-input standalone comparison was not replayed. "
            f"Single-turn cases sharing the same empty-state DialogueService entrypoint: "
            f"{report.dialogue.single_turn_same_entrypoint_count}; stateful multi-turn cases still "
            f"unresolved: {report.dialogue.stateful_multi_turn_unresolved_count}. Standalone stage "
            f"unnecessary-clarification rate was "
            f"{report.dialogue.standalone_stage_unnecessary_clarification_rate}; E2E was "
            f"{report.dialogue.e2e_unnecessary_clarification_rate}.",
            "",
            "## Structured-model outcomes",
            "",
            "| Purpose | Calls | Success | Timeout | Output bound | Invalid structured | "
            "Provider | Unclassified |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for call_outcome in report.structured_model_calls:
        lines.append(
            f"| {call_outcome.purpose} | {call_outcome.inferred_calls} | "
            f"{call_outcome.successful_structured_output} | {call_outcome.timeout} | "
            f"{call_outcome.output_bound_or_truncation} | "
            f"{call_outcome.invalid_json_or_schema} | {call_outcome.provider_error} | "
            f"{call_outcome.unclassified_failure} |"
        )
    lines.extend(
        [
            "",
            "Zero classified causes mean no such typed cause was retained in the report; generic "
            "pipeline failures remain unclassified rather than being treated as proof of absence.",
            "",
            "## M12 PASSED + Oracle FAILED",
            "",
        ]
    )
    for mismatch in report.oracle_mismatches:
        lines.append(
            f"- `{mismatch.case_id}` classification={mismatch.classification}; "
            f"expected_columns={list(mismatch.expected_columns)}; "
            f"observed_columns={list(mismatch.observed_columns)}; "
            f"runs={list(mismatch.run_ids)}; "
            f"trace_ids={list(mismatch.trace_event_ids)}"
        )
    lines.extend(["", "## Recommended frozen-milestone remediation order", ""])
    for recommendation in report.milestone_recommendations:
        lines.append(
            f"{recommendation.rank}. **{' + '.join(recommendation.milestones)}** — "
            f"{recommendation.expected_case_impact} cases: "
            f"{', '.join(recommendation.case_ids)}. {recommendation.rationale}"
        )
    lines.extend(["", "## Evidence limitations", ""])
    lines.extend(f"- {value}" for value in report.evidence_limitations)
    lines.append("")
    return "\n".join(lines)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def run_attribution(
    *,
    source_path: Path = SOURCE_REPORT_PATH,
    json_path: Path = ATTRIBUTION_JSON_PATH,
    markdown_path: Path = ATTRIBUTION_MARKDOWN_PATH,
) -> BehavioralAttributionReport:
    try:
        source = FinalAcceptanceReport.model_validate_json(source_path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise AttributionError(
            f"M15 source report is unavailable or invalid: {source_path}"
        ) from error
    suite, golden_fingerprint = load_golden()
    report = build_attribution(source, suite, golden_fingerprint=golden_fingerprint)
    serialized = json.dumps(
        report.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True
    )
    _write(json_path, f"{serialized}\n")
    _write(markdown_path, format_attribution_summary(report))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE_REPORT_PATH)
    parser.add_argument("--json-out", type=Path, default=ATTRIBUTION_JSON_PATH)
    parser.add_argument("--markdown-out", type=Path, default=ATTRIBUTION_MARKDOWN_PATH)
    args = parser.parse_args(argv)
    report = run_attribution(
        source_path=args.source,
        json_path=args.json_out,
        markdown_path=args.markdown_out,
    )
    print(
        f"M15 behavioral attribution: cases={report.total_cases}, "
        f"fingerprint={report.fingerprint}, json={args.json_out}, markdown={args.markdown_out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
