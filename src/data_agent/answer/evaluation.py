"""Frozen provider-free M14 grounding and response-authority evaluation."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Self

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from data_agent.answer.errors import AnswerGroundingError
from data_agent.answer.grounding import (
    ANSWER_GROUNDING_POLICY_VERSION,
    AnswerGroundingPolicy,
)
from data_agent.answer.prompt import ANSWER_PROMPT_VERSION
from data_agent.answer.proposal import AnswerProposal, CellReference
from data_agent.answer.service import AnswerSynthesisMode, AnswerSynthesisResult
from data_agent.catalog.semantic import load_assembled_catalog
from data_agent.contracts.run import Run, RunStatus
from data_agent.conversation.models import build_result_response
from data_agent.verification.context import build_verification_context
from data_agent.verification.evaluation import build_constructed_verification_evidence
from data_agent.verification.service import DeterministicVerifier

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
ANSWER_EVAL_PATH = REPOSITORY_ROOT / "evals" / "answer.yaml"
ANSWER_REPORT_PATH = REPOSITORY_ROOT / "evals" / "reports" / "answer-latest.json"


class AnswerEvaluationError(RuntimeError):
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


class _EvalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class AnswerEvalCase(_EvalModel):
    id: str = Field(min_length=1, pattern=r"\S")
    answer: str = Field(min_length=1)
    references: tuple[tuple[int, int], ...]
    expected: Literal["ACCEPT", "REJECT"]


class AnswerEvalSuite(_EvalModel):
    version: Literal["v0.1"]
    cases: tuple[AnswerEvalCase, ...] = Field(min_length=6)

    @model_validator(mode="after")
    def has_unique_required_cases(self) -> Self:
        ids = {case.id for case in self.cases}
        required = {
            "grounded-decimal-first-row",
            "hallucinated-number",
            "derived-percentage",
            "invalid-cell-reference",
            "missing-cell-reference",
        }
        if len(ids) != len(self.cases) or not required.issubset(ids):
            raise ValueError("answer eval cases are duplicated or incomplete")
        return self


class AnswerEvalCaseResult(_EvalModel):
    id: str
    expected: Literal["ACCEPT", "REJECT"]
    actual: Literal["ACCEPT", "REJECT"]
    passed: bool


class AnswerEvalMetrics(_EvalModel):
    case_count: int = Field(ge=6)
    grounding_decision_accuracy: float = Field(ge=0, le=1)
    ungrounded_numeric_rejection: float = Field(ge=0, le=1)
    derived_arithmetic_rejection: float = Field(ge=0, le=1)
    invalid_reference_rejection: float = Field(ge=0, le=1)
    decimal_api_fidelity: float = Field(ge=0, le=1)
    coverage_limitation_visibility: float = Field(ge=0, le=1)


class AnswerEvalIdentity(_EvalModel):
    suite_version: str
    suite_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_version: str
    grounding_policy_version: str


class AnswerEvalReport(_EvalModel):
    version: Literal["v0.1"] = "v0.1"
    identity: AnswerEvalIdentity
    metrics: AnswerEvalMetrics
    cases: tuple[AnswerEvalCaseResult, ...]
    passed: bool
    epistemic_boundary: Literal[
        "grounding-and-response-authority-only; no-language-quality-claim"
    ] = "grounding-and-response-authority-only; no-language-quality-claim"


def load_answer_eval_suite(
    path: Path = ANSWER_EVAL_PATH,
) -> tuple[AnswerEvalSuite, str]:
    try:
        payload = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeySafeLoader)
        suite = AnswerEvalSuite.model_validate(payload)
    except (OSError, TypeError, yaml.YAMLError, ValidationError) as error:
        raise AnswerEvaluationError("answer evaluation suite is missing or invalid") from error
    canonical = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return suite, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def evaluate_current_answer() -> AnswerEvalReport:
    suite, suite_fingerprint = load_answer_eval_suite()
    bundle = build_constructed_verification_evidence(load_assembled_catalog())
    verification = DeterministicVerifier().verify(
        build_verification_context(
            planning_trace=bundle.planning_trace,
            guarded_query=bundle.guarded_query,
            execution_metadata=bundle.execution_metadata,
            execution_result=bundle.execution_result,
        )
    )
    from data_agent.answer.context import build_answer_synthesis_context

    context = build_answer_synthesis_context(
        session_id="m14-eval-session",
        run_id="m14-eval-run",
        planning_trace=bundle.planning_trace,
        guarded_query=bundle.guarded_query,
        execution_metadata=bundle.execution_metadata,
        execution_result=bundle.execution_result,
        verification_trace=verification,
    )
    policy = AnswerGroundingPolicy()
    results: list[AnswerEvalCaseResult] = []
    for case in suite.cases:
        proposal = AnswerProposal(
            answer=case.answer,
            evidence_refs=[
                CellReference(row_index=row, column_index=column) for row, column in case.references
            ],
        )
        try:
            policy.validate(context=context, proposal=proposal)
        except AnswerGroundingError:
            actual: Literal["ACCEPT", "REJECT"] = "REJECT"
        else:
            actual = "ACCEPT"
        results.append(
            AnswerEvalCaseResult(
                id=case.id,
                expected=case.expected,
                actual=actual,
                passed=actual == case.expected,
            )
        )

    completed_at = datetime(2026, 8, 26, tzinfo=UTC)
    response = build_result_response(
        session_id="m14-eval-session",
        run=Run(
            id="m14-eval-run",
            session_id="m14-eval-session",
            status=RunStatus.COMPLETED,
            started_at=completed_at,
            completed_at=completed_at,
        ),
        planning_trace=bundle.planning_trace,
        guarded_query=bundle.guarded_query,
        execution_result=bundle.execution_result,
        verification_trace=verification,
        synthesis=AnswerSynthesisResult(
            answer="首日实付金额为 100.00。",
            evidence_refs=(CellReference(row_index=0, column_index=2),),
            mode=AnswerSynthesisMode.MODEL,
        ),
    )
    by_id = {result.id: result for result in results}
    accuracy = sum(result.passed for result in results) / len(results)
    metrics = AnswerEvalMetrics(
        case_count=len(results),
        grounding_decision_accuracy=accuracy,
        ungrounded_numeric_rejection=float(by_id["hallucinated-number"].passed),
        derived_arithmetic_rejection=float(by_id["derived-percentage"].passed),
        invalid_reference_rejection=float(
            by_id["invalid-cell-reference"].passed and by_id["missing-cell-reference"].passed
        ),
        decimal_api_fidelity=float(response.data.rows[0][2] == "100.00"),
        coverage_limitation_visibility=float(bool(response.verification.unsupported)),
    )
    report = AnswerEvalReport(
        identity=AnswerEvalIdentity(
            suite_version=suite.version,
            suite_fingerprint=suite_fingerprint,
            prompt_version=ANSWER_PROMPT_VERSION,
            grounding_policy_version=ANSWER_GROUNDING_POLICY_VERSION,
        ),
        metrics=metrics,
        cases=tuple(results),
        passed=all(
            value == 1.0
            for value in (
                metrics.grounding_decision_accuracy,
                metrics.ungrounded_numeric_rejection,
                metrics.derived_arithmetic_rejection,
                metrics.invalid_reference_rejection,
                metrics.decimal_api_fidelity,
                metrics.coverage_limitation_visibility,
            )
        ),
    )
    write_answer_eval_report(report)
    return report


def write_answer_eval_report(
    report: AnswerEvalReport,
    *,
    output_path: Path = ANSWER_REPORT_PATH,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = (
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    )
    temporary = output_path.with_name(f".{output_path.name}.tmp")
    try:
        temporary.write_text(serialized, encoding="utf-8")
        temporary.replace(output_path)
    finally:
        temporary.unlink(missing_ok=True)
    return output_path


def format_answer_eval_summary(report: AnswerEvalReport) -> str:
    metrics = report.metrics
    return (
        f"Answer eval {'PASS' if report.passed else 'FAIL'}: "
        f"cases={metrics.case_count}, grounding={metrics.grounding_decision_accuracy:.3f}, "
        f"numeric_reject={metrics.ungrounded_numeric_rejection:.3f}, "
        f"arithmetic_reject={metrics.derived_arithmetic_rejection:.3f}, "
        f"references={metrics.invalid_reference_rejection:.3f}, "
        f"decimal={metrics.decimal_api_fidelity:.3f}, "
        f"coverage={metrics.coverage_limitation_visibility:.3f}"
    )
