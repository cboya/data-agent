"""Standalone M8 dialogue evaluation isolated from retrieval, planning, and SQL."""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from data_agent.contracts.dialogue import DialogueAction, DialogueDecision
from data_agent.contracts.requirement import RequirementState, RequirementStatus
from data_agent.dialogue.errors import DialogueError
from data_agent.dialogue.prompt import DIALOGUE_PROMPT_VERSION
from data_agent.dialogue.service import DialogueEngine
from data_agent.model_runtime.errors import ModelAdapterError
from data_agent.model_runtime.ports import ModelFingerprint

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DIALOGUE_EVAL_PATH = REPOSITORY_ROOT / "evals" / "dialogue.yaml"
DIALOGUE_REPORT_PATH = REPOSITORY_ROOT / "evals" / "reports" / "dialogue-latest.json"


class _UniqueKeySafeLoader(yaml.SafeLoader):  # type: ignore[misc]
    def construct_mapping(self, node: Any, deep: bool = False) -> dict[Any, Any]:
        self.flatten_mapping(node)
        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in mapping
            except TypeError as error:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found an unhashable mapping key",
                    key_node.start_mark,
                ) from error
            if duplicate:
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


class ExpectationOp(StrEnum):
    IGNORE = "IGNORE"
    EQUALS = "EQUALS"
    CLEAR = "CLEAR"


class ScalarExpectation(_EvaluationModel):
    op: ExpectationOp = ExpectationOp.IGNORE
    value: str | int | None = None

    @model_validator(mode="after")
    def operation_matches_value(self) -> Self:
        if self.op is ExpectationOp.EQUALS and self.value is None:
            raise ValueError("EQUALS expectation requires a value")
        if self.op is not ExpectationOp.EQUALS and self.value is not None:
            raise ValueError(f"{self.op.value} expectation cannot carry a value")
        return self


class DialogueStateExpectation(_EvaluationModel):
    metrics: tuple[str, ...] | None = None
    dimensions: tuple[str, ...] | None = None
    required_blocking_fields: tuple[str, ...] = ()
    goal: ScalarExpectation = Field(default_factory=ScalarExpectation)
    time_range_value: ScalarExpectation = Field(default_factory=ScalarExpectation)
    grain: ScalarExpectation = Field(default_factory=ScalarExpectation)
    comparison: ScalarExpectation = Field(default_factory=ScalarExpectation)
    sort: ScalarExpectation = Field(default_factory=ScalarExpectation)
    limit: ScalarExpectation = Field(default_factory=ScalarExpectation)


class DialogueEvalTurn(_EvaluationModel):
    user: str = Field(min_length=1, pattern=r"\S", max_length=4_000)
    expected_action: DialogueAction
    expected_state: DialogueStateExpectation = Field(default_factory=DialogueStateExpectation)


class DialogueEvalCase(_EvaluationModel):
    id: str = Field(min_length=1, pattern=r"\S")
    category: Literal[
        "complete",
        "metric_ambiguity",
        "time_ambiguity",
        "grain_ambiguity",
        "non_blocking",
        "explicit_clear",
        "correction",
        "multi_turn",
        "mixed_language",
    ]
    initial_state: RequirementState | None = None
    turns: tuple[DialogueEvalTurn, ...] = Field(min_length=1)


class DialogueEvalSuite(_EvaluationModel):
    version: Literal["v0.1"]
    cases: tuple[DialogueEvalCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def case_ids_are_unique(self) -> Self:
        case_ids = [case.id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("dialogue eval case ids must be unique")
        return self


class DialogueTurnEvalResult(_EvaluationModel):
    turn: int = Field(ge=1)
    user: str
    expected_action: DialogueAction
    actual_action: DialogueAction | None
    proposed_decision: DialogueDecision | None = None
    actual_requirement: RequirementState | None = None
    action_correct: bool
    state_correct: bool
    errors: tuple[str, ...] = ()


class DialogueCaseEvalResult(_EvaluationModel):
    id: str
    category: str
    passed: bool
    turns_to_ready: int | None
    turns: tuple[DialogueTurnEvalResult, ...]


class DialogueEvalMetrics(_EvaluationModel):
    case_count: int = Field(ge=1)
    turn_count: int = Field(ge=1)
    action_accuracy: float = Field(ge=0, le=1)
    state_accuracy: float = Field(ge=0, le=1)
    required_clarification_recall: float = Field(ge=0, le=1)
    unnecessary_clarification_rate: float = Field(ge=0, le=1)
    explicit_clear_accuracy: float = Field(ge=0, le=1)
    correction_accuracy: float = Field(ge=0, le=1)
    multi_turn_convergence: float = Field(ge=0, le=1)
    mean_turns_to_ready: float = Field(ge=0)


class DialogueEvalIdentity(_EvaluationModel):
    suite_version: str
    prompt_version: str
    provider: str
    model: str
    model_digest: str | None
    model_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_version: str


class DialogueEvalReport(_EvaluationModel):
    version: Literal["v0.1"] = "v0.1"
    identity: DialogueEvalIdentity
    metrics: DialogueEvalMetrics
    cases: tuple[DialogueCaseEvalResult, ...]
    passed: bool


def load_dialogue_eval_suite(path: Path = DIALOGUE_EVAL_PATH) -> DialogueEvalSuite:
    try:
        payload = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeySafeLoader)
        return DialogueEvalSuite.model_validate(payload)
    except (OSError, yaml.YAMLError, ValidationError) as error:
        raise DialogueError("dialogue evaluation suite is missing or invalid") from error


def _identity(value: object) -> str:
    resolved_name = getattr(value, "resolved_name", None)
    term = getattr(value, "term", None)
    return str(resolved_name or term)


def _check_scalar(
    *,
    name: str,
    actual: str | int | None,
    expectation: ScalarExpectation,
) -> str | None:
    if expectation.op is ExpectationOp.IGNORE:
        return None
    if expectation.op is ExpectationOp.CLEAR:
        return None if actual is None else f"{name} expected CLEAR, got {actual!r}"
    return (
        None
        if actual == expectation.value
        else f"{name} expected {expectation.value!r}, got {actual!r}"
    )


def _state_errors(
    state: RequirementState,
    expected: DialogueStateExpectation,
) -> list[str]:
    errors: list[str] = []
    if expected.metrics is not None:
        metric_actual = tuple(sorted(_identity(value) for value in state.metrics))
        wanted = tuple(sorted(expected.metrics))
        if metric_actual != wanted:
            errors.append(f"metrics expected {wanted!r}, got {metric_actual!r}")
    if expected.dimensions is not None:
        dimension_actual = tuple(sorted(_identity(value) for value in state.dimensions))
        wanted = tuple(sorted(expected.dimensions))
        if dimension_actual != wanted:
            errors.append(f"dimensions expected {wanted!r}, got {dimension_actual!r}")
    blocking = {str(value.field) for value in state.unresolved if value.blocking}
    missing_blocking = set(expected.required_blocking_fields) - blocking
    if missing_blocking:
        errors.append(f"missing blocking fields: {sorted(missing_blocking)!r}")
    scalar_values: tuple[tuple[str, str | int | None, ScalarExpectation], ...] = (
        ("goal", state.goal, expected.goal),
        (
            "time_range_value",
            str(state.time_range.value) if state.time_range is not None else None,
            expected.time_range_value,
        ),
        ("grain", state.grain, expected.grain),
        ("comparison", state.comparison, expected.comparison),
        ("sort", state.sort, expected.sort),
        ("limit", state.limit, expected.limit),
    )
    for name, scalar_actual, expectation in scalar_values:
        error = _check_scalar(name=name, actual=scalar_actual, expectation=expectation)
        if error is not None:
            errors.append(error)
    return errors


def _empty_requirement() -> RequirementState:
    return RequirementState(version="v0.1", status=RequirementStatus.INCOMPLETE)


def _evaluation_error(error: Exception) -> str:
    cause = error.__cause__
    if isinstance(cause, ValidationError):
        details = "; ".join(
            f"{'.'.join(str(value) for value in item['loc'])}: {item['msg']}"
            for item in cause.errors(include_input=False)[:5]
        )
        return f"{type(error).__name__}: {details}"
    return f"{type(error).__name__}: {error}"


async def run_dialogue_evaluation(
    engine: DialogueEngine,
    *,
    suite: DialogueEvalSuite,
    chat_fingerprint: ModelFingerprint,
    runtime_version: str,
) -> DialogueEvalReport:
    case_results: list[DialogueCaseEvalResult] = []
    for case in suite.cases:
        state = case.initial_state or _empty_requirement()
        last_clarification: str | None = None
        turn_results: list[DialogueTurnEvalResult] = []
        turns_to_ready: int | None = None
        prior_failed = False
        for turn_number, turn in enumerate(case.turns, start=1):
            actual_action: DialogueAction | None = None
            proposed_decision: DialogueDecision | None = None
            actual_requirement: RequirementState | None = None
            errors: list[str] = []
            state_errors: list[str] = []
            if prior_failed:
                errors.append("turn not executed after prior evaluation failure")
            else:
                try:
                    outcome = await engine.understand(
                        requirement=state,
                        latest_user_message=turn.user,
                        last_assistant_clarification=last_clarification,
                    )
                    proposed_decision = outcome.decision
                    state = outcome.requirement
                    actual_requirement = state
                    actual_action = outcome.decision.action
                    state_errors = _state_errors(state, turn.expected_state)
                    errors.extend(state_errors)
                    if actual_action is DialogueAction.ASK_CLARIFICATION:
                        last_clarification = outcome.decision.question
                    else:
                        last_clarification = None
                    if actual_action is DialogueAction.READY and turns_to_ready is None:
                        turns_to_ready = turn_number
                except (DialogueError, ModelAdapterError, ValidationError, ValueError) as error:
                    errors.append(_evaluation_error(error))
                    prior_failed = True
            action_correct = actual_action is turn.expected_action
            if not action_correct:
                errors.append(
                    f"action expected {turn.expected_action.value}, "
                    f"got {actual_action.value if actual_action is not None else 'ERROR'}"
                )
            turn_results.append(
                DialogueTurnEvalResult(
                    turn=turn_number,
                    user=turn.user,
                    expected_action=turn.expected_action,
                    actual_action=actual_action,
                    proposed_decision=proposed_decision,
                    actual_requirement=actual_requirement,
                    action_correct=action_correct,
                    state_correct=not state_errors and not prior_failed,
                    errors=tuple(errors),
                )
            )
        case_results.append(
            DialogueCaseEvalResult(
                id=case.id,
                category=case.category,
                passed=all(
                    result.action_correct and result.state_correct for result in turn_results
                ),
                turns_to_ready=turns_to_ready,
                turns=tuple(turn_results),
            )
        )

    turns = [turn for case in case_results for turn in case.turns]
    expected_clarifications = [
        turn for turn in turns if turn.expected_action is DialogueAction.ASK_CLARIFICATION
    ]
    expected_ready = [turn for turn in turns if turn.expected_action is DialogueAction.READY]
    clear_cases = [case for case in case_results if case.category == "explicit_clear"]
    correction_cases = [case for case in case_results if case.category == "correction"]
    multi_turn_cases = [case for case in case_results if case.category == "multi_turn"]
    ready_cases = [
        (case, result)
        for case, result in zip(suite.cases, case_results, strict=True)
        if case.turns[-1].expected_action is DialogueAction.READY
    ]

    def case_accuracy(values: list[DialogueCaseEvalResult]) -> float:
        return sum(value.passed for value in values) / len(values) if values else 1.0

    mean_turns_to_ready = (
        sum(
            result.turns_to_ready if result.turns_to_ready is not None else len(case.turns) + 1
            for case, result in ready_cases
        )
        / len(ready_cases)
        if ready_cases
        else 0.0
    )
    metrics = DialogueEvalMetrics(
        case_count=len(case_results),
        turn_count=len(turns),
        action_accuracy=sum(turn.action_correct for turn in turns) / len(turns),
        state_accuracy=sum(turn.state_correct for turn in turns) / len(turns),
        required_clarification_recall=(
            sum(
                turn.actual_action is DialogueAction.ASK_CLARIFICATION
                for turn in expected_clarifications
            )
            / len(expected_clarifications)
            if expected_clarifications
            else 1.0
        ),
        unnecessary_clarification_rate=(
            sum(turn.actual_action is DialogueAction.ASK_CLARIFICATION for turn in expected_ready)
            / len(expected_ready)
            if expected_ready
            else 0.0
        ),
        explicit_clear_accuracy=case_accuracy(clear_cases),
        correction_accuracy=case_accuracy(correction_cases),
        multi_turn_convergence=case_accuracy(multi_turn_cases),
        mean_turns_to_ready=mean_turns_to_ready,
    )
    return DialogueEvalReport(
        identity=DialogueEvalIdentity(
            suite_version=suite.version,
            prompt_version=DIALOGUE_PROMPT_VERSION,
            provider=chat_fingerprint.provider,
            model=chat_fingerprint.model,
            model_digest=chat_fingerprint.digest,
            model_fingerprint=chat_fingerprint.value,
            runtime_version=runtime_version,
        ),
        metrics=metrics,
        cases=tuple(case_results),
        passed=(
            metrics.action_accuracy >= 0.90
            and metrics.state_accuracy >= 0.90
            and metrics.required_clarification_recall >= 0.90
            and metrics.unnecessary_clarification_rate <= 0.10
            and metrics.explicit_clear_accuracy == 1.0
            and metrics.correction_accuracy == 1.0
            and metrics.multi_turn_convergence == 1.0
        ),
    )


def write_dialogue_eval_report(
    report: DialogueEvalReport,
    *,
    output_path: Path = DIALOGUE_REPORT_PATH,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = (
        json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    temporary_path = output_path.with_name(f".{output_path.name}.tmp")
    try:
        temporary_path.write_text(serialized, encoding="utf-8")
        temporary_path.replace(output_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return output_path


def format_dialogue_eval_summary(report: DialogueEvalReport) -> str:
    metrics = report.metrics
    status = "PASS" if report.passed else "FAIL"
    return (
        f"Dialogue eval {status}: cases={metrics.case_count}, turns={metrics.turn_count}, "
        f"action_accuracy={metrics.action_accuracy:.3f}, "
        f"state_accuracy={metrics.state_accuracy:.3f}, "
        f"clarification_recall={metrics.required_clarification_recall:.3f}, "
        f"unnecessary_clarification={metrics.unnecessary_clarification_rate:.3f}, "
        f"clear={metrics.explicit_clear_accuracy:.3f}, "
        f"correction={metrics.correction_accuracy:.3f}, "
        f"multi_turn={metrics.multi_turn_convergence:.3f}, "
        f"turns_to_ready={metrics.mean_turns_to_ready:.2f}"
    )
