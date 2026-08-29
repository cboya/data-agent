"""Provider-free M8 readiness evaluation over frozen proposal evidence."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from data_agent.contracts.dialogue import DialogueAction, DialogueGrainMutation, DialogueProposal
from data_agent.contracts.requirement import PatchOp, RequirementState
from data_agent.dialogue.errors import InvalidProviderEvidenceError
from data_agent.dialogue.policy import BlockingReasonCode
from data_agent.dialogue.service import DialogueEngine
from data_agent.model_runtime.ports import ChatModel

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
READINESS_EVAL_DIRECTORY = REPOSITORY_ROOT / "evals" / "dialogue_readiness"
READINESS_REPORT_PATH = REPOSITORY_ROOT / "evals" / "reports" / "dialogue-readiness-latest.json"


class _EvaluationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class ReadinessExpectedOutcome(StrEnum):
    DECISION = "DECISION"
    INVALID_PROVIDER_EVIDENCE = "INVALID_PROVIDER_EVIDENCE"


class ReadinessEvalTurn(_EvaluationModel):
    turn_number: int = Field(ge=1)
    latest_user_message: str = Field(min_length=1, pattern=r"\S")
    initial_requirement_state: RequirementState
    provider_proposal: DialogueProposal
    expected_outcome: ReadinessExpectedOutcome = ReadinessExpectedOutcome.DECISION
    expected_action: DialogueAction | None
    expected_requirement_state: RequirementState | None
    expected_reason_codes: tuple[BlockingReasonCode, ...]

    @model_validator(mode="after")
    def expected_outcome_is_complete(self) -> ReadinessEvalTurn:
        if self.expected_outcome is ReadinessExpectedOutcome.DECISION:
            if self.expected_action is None or self.expected_requirement_state is None:
                raise ValueError("decision expectation requires action and requirement state")
        elif self.expected_action is not None or self.expected_requirement_state is not None:
            raise ValueError("invalid-provider-evidence expectation cannot carry decision state")
        return self


class ReadinessEvalCase(_EvaluationModel):
    id: str = Field(min_length=1, pattern=r"\S")
    category: Literal["KNOWN_FALSE_CLARIFICATION", "KNOWN_AMBIGUOUS", "KNOWN_COMPLETE_READY"]
    turns: tuple[ReadinessEvalTurn, ...] = Field(min_length=1)


class ReadinessEvalShard(_EvaluationModel):
    version: Literal["v0.1"]
    source_diagnosis_fingerprint: str
    cases: tuple[ReadinessEvalCase, ...] = Field(min_length=1)


class ReadinessEvalSuite(_EvaluationModel):
    version: Literal["v0.1"]
    cases: tuple[ReadinessEvalCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def case_ids_are_unique(self) -> ReadinessEvalSuite:
        case_ids = [case.id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("readiness evaluation case ids must be unique")
        return self

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ReadinessTurnResult(_EvaluationModel):
    turn_number: int
    expected_outcome: ReadinessExpectedOutcome
    actual_outcome: ReadinessExpectedOutcome
    expected_action: DialogueAction | None
    actual_action: DialogueAction | None
    action_correct: bool
    state_correct: bool
    reason_codes_correct: bool
    scope_preserved: bool
    confirmed_facts_preserved: bool
    actual_reason_codes: tuple[BlockingReasonCode, ...]


class ReadinessCaseResult(_EvaluationModel):
    id: str
    category: str
    passed: bool
    turns: tuple[ReadinessTurnResult, ...]


class ReadinessEvalMetrics(_EvaluationModel):
    case_count: int
    turn_count: int
    frozen_false_clarification_case_count: int
    true_ambiguity_case_count: int
    complete_ready_control_count: int
    insufficient_provider_evidence_case_count: int
    insufficient_provider_evidence_false_ready_count: int
    unnecessary_clarification_count: int
    necessary_clarification_recall: float = Field(ge=0, le=1)
    false_ready_count: int
    action_accuracy: float = Field(ge=0, le=1)
    state_accuracy: float = Field(ge=0, le=1)
    reason_code_accuracy: float = Field(ge=0, le=1)
    scope_preservation_accuracy: float = Field(ge=0, le=1)
    confirmed_fact_preservation_accuracy: float = Field(ge=0, le=1)


class ReadinessEvalReport(_EvaluationModel):
    version: Literal["v0.1"] = "v0.1"
    suite_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_version: Literal["blocking-ambiguity-policy-v0.1"] = "blocking-ambiguity-policy-v0.1"
    metrics: ReadinessEvalMetrics
    cases: tuple[ReadinessCaseResult, ...]
    passed: bool


def load_readiness_eval_suite(
    directory: Path = READINESS_EVAL_DIRECTORY,
) -> ReadinessEvalSuite:
    cases: list[ReadinessEvalCase] = []
    paths = sorted(directory.glob("*.json"))
    if not paths:
        raise ValueError("readiness evaluation fixtures are missing")
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        shard = ReadinessEvalShard.model_validate(payload)
        cases.extend(shard.cases)
    return ReadinessEvalSuite(version="v0.1", cases=tuple(cases))


def _scope_was_preserved(turn: ReadinessEvalTurn, actual: RequirementState) -> bool:
    initial = turn.initial_requirement_state
    patch = turn.provider_proposal.patch
    if patch.time_range.op is PatchOp.NO_CHANGE and actual.time_range != initial.time_range:
        return False
    return patch.grain is not DialogueGrainMutation.NO_CHANGE or actual.grain == initial.grain


def _requirement_identity(value: object) -> str:
    resolved_name = getattr(value, "resolved_name", None)
    term = getattr(value, "term", None)
    return str(resolved_name or term)


def _confirmed_facts_were_preserved(
    turn: ReadinessEvalTurn,
    actual: RequirementState,
) -> bool:
    initial = turn.initial_requirement_state
    patch = turn.provider_proposal.patch
    retained_metric_ids = {
        _requirement_identity(value)
        for value in initial.metrics
        if _requirement_identity(value) not in {str(item) for item in patch.metrics_remove}
    }
    retained_dimension_ids = {
        _requirement_identity(value)
        for value in initial.dimensions
        if _requirement_identity(value) not in {str(item) for item in patch.dimensions_remove}
    }
    actual_metric_ids = {_requirement_identity(value) for value in actual.metrics}
    actual_dimension_ids = {_requirement_identity(value) for value in actual.dimensions}
    return (
        retained_metric_ids <= actual_metric_ids and retained_dimension_ids <= actual_dimension_ids
    )


def run_readiness_evaluation(suite: ReadinessEvalSuite) -> ReadinessEvalReport:
    engine = DialogueEngine(chat_model=cast(ChatModel, object()))
    case_results: list[ReadinessCaseResult] = []
    for case in suite.cases:
        turn_results: list[ReadinessTurnResult] = []
        for turn in case.turns:
            actual_outcome = ReadinessExpectedOutcome.DECISION
            actual_action: DialogueAction | None = None
            actual_requirement: RequirementState | None = None
            scope_preserved = True
            confirmed_facts_preserved = True
            try:
                outcome = engine.resolve_proposal(
                    requirement=turn.initial_requirement_state,
                    proposal=turn.provider_proposal,
                    latest_user_message=turn.latest_user_message,
                )
                if outcome.blocking is None:
                    raise AssertionError(
                        "proposal resolution must include blocking-policy evidence"
                    )
                actual_action = outcome.decision.action
                actual_requirement = outcome.requirement
                reason_codes = tuple(
                    assessment.reason_code for assessment in outcome.blocking.assessments
                )
                scope_preserved = _scope_was_preserved(turn, outcome.requirement)
                confirmed_facts_preserved = _confirmed_facts_were_preserved(
                    turn, outcome.requirement
                )
            except InvalidProviderEvidenceError as error:
                actual_outcome = ReadinessExpectedOutcome.INVALID_PROVIDER_EVIDENCE
                reason_codes = tuple(BlockingReasonCode(value) for value in error.reason_codes)
            outcome_correct = actual_outcome is turn.expected_outcome
            turn_results.append(
                ReadinessTurnResult(
                    turn_number=turn.turn_number,
                    expected_outcome=turn.expected_outcome,
                    actual_outcome=actual_outcome,
                    expected_action=turn.expected_action,
                    actual_action=actual_action,
                    action_correct=(
                        outcome_correct
                        and (
                            turn.expected_outcome
                            is ReadinessExpectedOutcome.INVALID_PROVIDER_EVIDENCE
                            or actual_action is turn.expected_action
                        )
                    ),
                    state_correct=(
                        outcome_correct
                        and (
                            turn.expected_outcome
                            is ReadinessExpectedOutcome.INVALID_PROVIDER_EVIDENCE
                            or actual_requirement == turn.expected_requirement_state
                        )
                    ),
                    reason_codes_correct=reason_codes == turn.expected_reason_codes,
                    scope_preserved=scope_preserved,
                    confirmed_facts_preserved=confirmed_facts_preserved,
                    actual_reason_codes=reason_codes,
                )
            )
        case_results.append(
            ReadinessCaseResult(
                id=case.id,
                category=case.category,
                passed=all(
                    turn.action_correct
                    and turn.state_correct
                    and turn.reason_codes_correct
                    and turn.scope_preserved
                    and turn.confirmed_facts_preserved
                    for turn in turn_results
                ),
                turns=tuple(turn_results),
            )
        )

    turns = [turn for case in case_results for turn in case.turns]
    false_clarification_turns = [
        turn
        for case in case_results
        if case.category == "KNOWN_FALSE_CLARIFICATION"
        for turn in case.turns
    ]
    expected_ready = [
        turn for turn in false_clarification_turns if turn.expected_action is DialogueAction.READY
    ]
    expected_ask = [
        turn for turn in turns if turn.expected_action is DialogueAction.ASK_CLARIFICATION
    ]
    expected_invalid = [
        turn
        for turn in turns
        if turn.expected_outcome is ReadinessExpectedOutcome.INVALID_PROVIDER_EVIDENCE
    ]
    metrics = ReadinessEvalMetrics(
        case_count=len(case_results),
        turn_count=len(turns),
        frozen_false_clarification_case_count=sum(
            case.category == "KNOWN_FALSE_CLARIFICATION" for case in case_results
        ),
        true_ambiguity_case_count=sum(case.category == "KNOWN_AMBIGUOUS" for case in case_results),
        complete_ready_control_count=sum(
            case.category == "KNOWN_COMPLETE_READY" for case in case_results
        ),
        insufficient_provider_evidence_case_count=sum(
            any(
                turn.expected_outcome is ReadinessExpectedOutcome.INVALID_PROVIDER_EVIDENCE
                for turn in case.turns
            )
            for case in case_results
        ),
        insufficient_provider_evidence_false_ready_count=sum(
            turn.actual_action is DialogueAction.READY for turn in expected_invalid
        ),
        unnecessary_clarification_count=sum(
            turn.actual_action is DialogueAction.ASK_CLARIFICATION for turn in expected_ready
        ),
        necessary_clarification_recall=(
            sum(turn.actual_action is DialogueAction.ASK_CLARIFICATION for turn in expected_ask)
            / len(expected_ask)
        ),
        false_ready_count=sum(turn.actual_action is DialogueAction.READY for turn in expected_ask),
        action_accuracy=sum(turn.action_correct for turn in turns) / len(turns),
        state_accuracy=sum(turn.state_correct for turn in turns) / len(turns),
        reason_code_accuracy=sum(turn.reason_codes_correct for turn in turns) / len(turns),
        scope_preservation_accuracy=sum(turn.scope_preserved for turn in turns) / len(turns),
        confirmed_fact_preservation_accuracy=(
            sum(turn.confirmed_facts_preserved for turn in turns) / len(turns)
        ),
    )
    return ReadinessEvalReport(
        suite_fingerprint=suite.fingerprint,
        metrics=metrics,
        cases=tuple(case_results),
        passed=(
            metrics.frozen_false_clarification_case_count == 35
            and metrics.complete_ready_control_count == 1
            and metrics.insufficient_provider_evidence_case_count == 3
            and metrics.insufficient_provider_evidence_false_ready_count == 0
            and metrics.unnecessary_clarification_count == 0
            and metrics.necessary_clarification_recall == 1.0
            and metrics.false_ready_count == 0
            and metrics.action_accuracy == 1.0
            and metrics.state_accuracy == 1.0
            and metrics.reason_code_accuracy == 1.0
            and metrics.scope_preservation_accuracy == 1.0
            and metrics.confirmed_fact_preservation_accuracy == 1.0
        ),
    )


def write_readiness_eval_report(
    report: ReadinessEvalReport,
    *,
    output_path: Path = READINESS_REPORT_PATH,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        report.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    output_path.write_text(f"{payload}\n", encoding="utf-8")
    return output_path


def format_readiness_eval_summary(report: ReadinessEvalReport) -> str:
    metrics = report.metrics
    return (
        f"M8 readiness eval {'PASS' if report.passed else 'FAIL'}: "
        f"cases={metrics.case_count}, turns={metrics.turn_count}, "
        f"unnecessary_clarification={metrics.unnecessary_clarification_count}, "
        f"necessary_recall={metrics.necessary_clarification_recall:.3f}, "
        f"false_ready={metrics.false_ready_count}, "
        f"insufficient_evidence_false_ready="
        f"{metrics.insufficient_provider_evidence_false_ready_count}, "
        f"state={metrics.state_accuracy:.3f}, "
        f"scope={metrics.scope_preservation_accuracy:.3f}, "
        f"facts={metrics.confirmed_fact_preservation_accuracy:.3f}"
    )
