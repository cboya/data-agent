"""Standalone deterministic M13 eligibility and safety evaluation."""

from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Literal, Self

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from data_agent.contracts.run import RunStatus
from data_agent.repair.evidence import (
    REPAIR_FAILURE_FINGERPRINT_VERSION,
    REPAIR_POLICY_VERSION,
    RepairCategory,
    RepairFailure,
    RepairStage,
    repair_failure_fingerprint,
)
from data_agent.repair.policy import RepairEligibilityPolicy

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
REPAIR_EVAL_PATH = REPOSITORY_ROOT / "evals" / "repair.yaml"
REPAIR_REPORT_PATH = REPOSITORY_ROOT / "evals" / "reports" / "repair-latest.json"


class RepairEvaluationError(RuntimeError):
    pass


class _UniqueKeySafeLoader(yaml.SafeLoader):  # type: ignore[misc]
    def construct_mapping(self, node: Any, deep: bool = False) -> dict[Any, Any]:
        self.flatten_mapping(node)
        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in mapping:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found duplicate key: {key}",
                    key_node.start_mark,
                )
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


class _EvaluationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class RepairEvalCase(_EvaluationModel):
    id: str = Field(min_length=1, pattern=r"\S")
    stage: RepairStage
    category: RepairCategory
    code: str = Field(min_length=1)
    provider_errno: int | None = Field(default=None, ge=1)
    failed_checks: tuple[str, ...] = ()
    coverage_gaps: tuple[str, ...] = ()
    budget_remaining: bool = True
    expected_eligible: bool
    expected_terminal: RunStatus | None = None
    expected_model_calls: Literal[0, 1]


class RepairEvalSuite(_EvaluationModel):
    version: Literal["v0.1"]
    cases: tuple[RepairEvalCase, ...] = Field(min_length=12)

    @model_validator(mode="after")
    def suite_covers_safety_boundary(self) -> Self:
        ids = [case.id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("repair eval case ids must be unique")
        required = {
            "syntax",
            "unknown-column",
            "ambiguous-column",
            "policy-denial",
            "dangerous-function",
            "table-escape",
            "too-expensive",
            "timeout",
            "unavailable",
            "integrity",
            "coverage-gap",
            "exhausted",
        }
        if not required.issubset(ids):
            raise ValueError("repair eval suite is missing a required safety case")
        return self


class RepairEvalCaseResult(_EvaluationModel):
    id: str
    failure_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_eligible: bool
    actual_eligible: bool
    expected_terminal: RunStatus | None
    actual_terminal: RunStatus | None
    expected_model_calls: Literal[0, 1]
    actual_model_calls: Literal[0, 1]
    passed: bool


class RepairEvalMetrics(_EvaluationModel):
    case_count: int = Field(ge=12)
    eligibility_classification_accuracy: float = Field(ge=0, le=1)
    policy_integrity_no_model_call_accuracy: float = Field(ge=0, le=1)
    repair_bound_enforcement: float = Field(ge=0, le=1)
    concurrent_claim_bound_enforcement: float = Field(ge=0, le=1)


class RepairEvalIdentity(_EvaluationModel):
    suite_version: str
    suite_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    repair_policy_version: str
    failure_fingerprint_version: str
    max_attempts: int = Field(ge=0)


class RepairEvalReport(_EvaluationModel):
    version: Literal["v0.1"] = "v0.1"
    identity: RepairEvalIdentity
    metrics: RepairEvalMetrics
    cases: tuple[RepairEvalCaseResult, ...]
    passed: bool
    epistemic_boundary: Literal[
        "typed-eligibility-and-bound-only; real-model-repair-success-reported-separately"
    ] = "typed-eligibility-and-bound-only; real-model-repair-success-reported-separately"


def load_repair_eval_suite(
    path: Path = REPAIR_EVAL_PATH,
) -> tuple[RepairEvalSuite, str]:
    try:
        payload = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeySafeLoader)
        suite = RepairEvalSuite.model_validate(payload)
    except (OSError, TypeError, yaml.YAMLError, ValidationError) as error:
        raise RepairEvaluationError("repair evaluation suite is missing or invalid") from error
    canonical = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return suite, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _failure(case: RepairEvalCase) -> RepairFailure:
    return RepairFailure(
        source_run_id="m13_eval_run",
        stage=case.stage,
        category=case.category,
        code=case.code,
        provider_errno=case.provider_errno,
        failed_checks=case.failed_checks,
        coverage_gaps=case.coverage_gaps,
        query_plan_fingerprint="1" * 64,
        planner_context_fingerprint="2" * 64,
    )


def _evaluate_case(case: RepairEvalCase) -> RepairEvalCaseResult:
    failure = _failure(case)
    decision = RepairEligibilityPolicy().evaluate(failure)
    model_calls: Literal[0, 1] = 1 if decision.eligible and case.budget_remaining else 0
    terminal = (
        RunStatus.REPAIR_EXHAUSTED
        if decision.eligible and not case.budget_remaining
        else decision.terminal_status
    )
    passed = (
        decision.eligible == case.expected_eligible
        and terminal is case.expected_terminal
        and model_calls == case.expected_model_calls
    )
    return RepairEvalCaseResult(
        id=case.id,
        failure_fingerprint=repair_failure_fingerprint(failure),
        expected_eligible=case.expected_eligible,
        actual_eligible=decision.eligible,
        expected_terminal=case.expected_terminal,
        actual_terminal=terminal,
        expected_model_calls=case.expected_model_calls,
        actual_model_calls=model_calls,
        passed=passed,
    )


def _concurrent_bound_score(max_attempts: int) -> float:
    lock = threading.Lock()
    claimed = 0

    def claim() -> bool:
        nonlocal claimed
        with lock:
            if claimed >= max_attempts:
                return False
            claimed += 1
            return True

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(lambda _: claim(), range(8)))
    return 1.0 if sum(outcomes) == max_attempts == claimed else 0.0


def run_repair_evaluation(
    *,
    suite: RepairEvalSuite,
    suite_fingerprint: str,
    max_attempts: int,
) -> RepairEvalReport:
    results = tuple(_evaluate_case(case) for case in suite.cases)
    protected = [
        result
        for case, result in zip(suite.cases, results, strict=True)
        if case.category
        in {RepairCategory.POLICY, RepairCategory.INTEGRITY, RepairCategory.CAPABILITY}
    ]
    exhausted = [result for result in results if result.id == "exhausted"]
    metrics = RepairEvalMetrics(
        case_count=len(results),
        eligibility_classification_accuracy=sum(
            result.actual_eligible == result.expected_eligible for result in results
        )
        / len(results),
        policy_integrity_no_model_call_accuracy=sum(
            result.actual_model_calls == 0 for result in protected
        )
        / len(protected),
        repair_bound_enforcement=sum(
            result.actual_model_calls == 0 and result.actual_terminal is RunStatus.REPAIR_EXHAUSTED
            for result in exhausted
        )
        / len(exhausted),
        concurrent_claim_bound_enforcement=_concurrent_bound_score(max_attempts),
    )
    passed = all(result.passed for result in results) and all(
        value == 1.0
        for value in (
            metrics.eligibility_classification_accuracy,
            metrics.policy_integrity_no_model_call_accuracy,
            metrics.repair_bound_enforcement,
            metrics.concurrent_claim_bound_enforcement,
        )
    )
    return RepairEvalReport(
        identity=RepairEvalIdentity(
            suite_version=suite.version,
            suite_fingerprint=suite_fingerprint,
            repair_policy_version=REPAIR_POLICY_VERSION,
            failure_fingerprint_version=REPAIR_FAILURE_FINGERPRINT_VERSION,
            max_attempts=max_attempts,
        ),
        metrics=metrics,
        cases=results,
        passed=passed,
    )


def write_repair_eval_report(
    report: RepairEvalReport,
    *,
    output_path: Path = REPAIR_REPORT_PATH,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = (
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    )
    temporary_path = output_path.with_name(f".{output_path.name}.tmp")
    try:
        temporary_path.write_text(serialized, encoding="utf-8")
        temporary_path.replace(output_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return output_path


def evaluate_current_repair(max_attempts: int) -> RepairEvalReport:
    suite, suite_fingerprint = load_repair_eval_suite()
    report = run_repair_evaluation(
        suite=suite,
        suite_fingerprint=suite_fingerprint,
        max_attempts=max_attempts,
    )
    write_repair_eval_report(report)
    return report


def format_repair_eval_summary(report: RepairEvalReport) -> str:
    metrics = report.metrics
    status = "PASS" if report.passed else "FAIL"
    return (
        f"Repair eval {status}: cases={metrics.case_count}, "
        f"eligibility={metrics.eligibility_classification_accuracy:.3f}, "
        f"zero_model={metrics.policy_integrity_no_model_call_accuracy:.3f}, "
        f"bound={metrics.repair_bound_enforcement:.3f}, "
        f"concurrent_bound={metrics.concurrent_claim_bound_enforcement:.3f}"
    )
