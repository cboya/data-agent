"""Targeted, evidence-bound M15 behavioral diagnosis without full Golden execution."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, cast
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from data_agent.answer.service import (
    AnswerSynthesisMode,
    AnswerSynthesisResult,
    AnswerSynthesizer,
)
from data_agent.catalog.semantic import AssembledSemanticCatalog
from data_agent.config import Settings
from data_agent.contracts.dialogue import DialogueAction, DialogueProposal
from data_agent.contracts.query import QueryPlan
from data_agent.contracts.requirement import RequirementState, RequirementStatus
from data_agent.contracts.retrieval import RetrievalResult
from data_agent.conversation.models import ConversationResponse, ResultResponse
from data_agent.conversation.runtime import ConversationApplication
from data_agent.conversation.service import ConversationOrchestrator
from data_agent.dialogue.prompt import DIALOGUE_PROMPT_VERSION
from data_agent.dialogue.service import DialogueEngine, DialogueService
from data_agent.model_runtime.errors import (
    ModelContractError,
    ModelResponseError,
    ModelTimeoutError,
    ModelTransportError,
)
from data_agent.model_runtime.ollama import (
    OllamaChatModel,
    OllamaEmbeddingModel,
    OllamaStartupDiagnostics,
)
from data_agent.model_runtime.ports import (
    ChatModel,
    ModelRuntimeDiagnostics,
    StructuredResultT,
)
from data_agent.persistence.mysql.dialogue_turns import MySQLDialogueTurnStore
from data_agent.persistence.mysql.runs import MySQLRunRepository
from data_agent.persistence.mysql.sessions import MySQLSessionRepository
from data_agent.persistence.mysql.traces import MySQLTraceRepository
from data_agent.planning.service import PlanningTrace, QueryPlanner
from data_agent.query_runtime.runtime import build_readonly_query_runtime
from data_agent.query_runtime.service import RuntimeExecutionEvidence
from data_agent.repair.service import BoundedRepairService, RepairPipelineOutcome
from data_agent.retrieval.index import load_retrieval_index
from data_agent.retrieval.runtime import load_current_catalog_authority
from data_agent.retrieval.service import HybridRetriever, RetrievalTrace
from data_agent.sql_guard.capability import GuardedQuery
from data_agent.sql_guard.runtime import build_sql_admission_service
from data_agent.sql_guard.service import SQLAdmissionOutcome, SQLAdmissionService
from data_agent.verification.context import VerificationContext
from data_agent.verification.evidence import VerificationTrace
from data_agent.verification.service import DeterministicVerifier
from eval_harness.attribution import (
    BehavioralAttributionReport,
    TerminalBucket,
)
from eval_harness.golden import _canonical_rows, _oracle_result
from eval_harness.loader import REPOSITORY_ROOT, load_golden, load_oracles
from eval_harness.models import (
    EvaluationEnvironment,
    EvaluationEnvironmentV01,
    FinalAcceptanceReport,
    GoldenCase,
    GoldenCaseResult,
)

SOURCE_REPORT_PATH = REPOSITORY_ROOT / "evals" / "reports" / "latest.json"
ATTRIBUTION_EVIDENCE_PATH = (
    REPOSITORY_ROOT / "docs" / "evidence" / "M15-BEHAVIORAL-ATTRIBUTION-3be2534.json"
)
DIAGNOSIS_JSON_PATH = (
    REPOSITORY_ROOT / "docs" / "evidence" / "M15-BEHAVIORAL-DIAGNOSIS-3be2534.json"
)
DIAGNOSIS_MARKDOWN_PATH = (
    REPOSITORY_ROOT / "docs" / "evidence" / "M15-BEHAVIORAL-DIAGNOSIS-3be2534.md"
)
M8_CHECKPOINT_PATH = REPOSITORY_ROOT / "evals" / "reports" / "m8-replay-checkpoint.json"

_FALSE_ACCEPT_SCENARIOS: dict[str, Literal["EXTRA_GRAIN", "OUTPUT_SHAPE"]] = {
    "simple-gmv": "EXTRA_GRAIN",
    "simple-paid-amount": "EXTRA_GRAIN",
    "simple-payment-attempts": "EXTRA_GRAIN",
    "join-net-revenue": "EXTRA_GRAIN",
    "agg-gmv-channel": "OUTPUT_SHAPE",
    "agg-orders-channel": "OUTPUT_SHAPE",
}


class DiagnosisError(RuntimeError):
    """The retained evidence or live environment cannot support the diagnosis."""


class _DiagnosisModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class DiagnosticIdentity(_DiagnosisModel):
    source_environment: EvaluationEnvironment
    source_attribution_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    diagnostic_git_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    runtime_source_diff_from_effect_commit: Literal["EMPTY"]
    chat_model: str
    chat_model_digest: str
    chat_model_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    embedding_model_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    ollama_runtime_version: str
    dialogue_prompt_version: str
    ollama_request_timeout_seconds: float
    ollama_max_output_tokens: int
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


type StructuredCallStatus = Literal[
    "SUCCEEDED",
    "TIMEOUT",
    "OUTPUT_INCOMPLETE",
    "INVALID_STRUCTURED_OUTPUT",
    "PROVIDER_ERROR",
    "UNEXPECTED_FAILURE",
]


class StructuredModelCallOutcome(_DiagnosisModel):
    purpose: str
    response_type: str
    status: StructuredCallStatus
    duration_ms: int = Field(ge=0)
    error_type: str | None = None
    error_detail: str | None = None


class DialogueBlocker(_DiagnosisModel):
    field: str
    subject_term: str


class M8ReplayTurn(_DiagnosisModel):
    turn_number: int = Field(ge=1)
    user_message: str
    expected_action: str
    original_stored_e2e_action: str
    standalone_m8_action: str | None
    blockers: tuple[DialogueBlocker, ...]
    structured_dialogue_proposal: dict[str, Any] | None
    normalized_dialogue_decision: dict[str, Any] | None
    requirement_patch: dict[str, Any] | None
    merged_requirement_state: dict[str, Any] | None
    structured_model_call_outcome: StructuredModelCallOutcome
    normalization_or_policy_error: str | None
    prompt_model_environment_identity: str = Field(pattern=r"^[0-9a-f]{64}$")


class M8ReplayCase(_DiagnosisModel):
    case_id: str
    classification: Literal[
        "STANDALONE_M8_ALSO_CLARIFIES",
        "STANDALONE_READY_E2E_CLARIFIED",
        "STANDALONE_STRUCTURED_MODEL_FAILURE",
        "SPEC_ORACLE_REVIEW_REQUIRED",
    ]
    turns: tuple[M8ReplayTurn, ...] = Field(min_length=1)


class M8ReplaySummary(_DiagnosisModel):
    case_count: Literal[35]
    classification_counts: dict[str, int]
    blocker_field_distribution: dict[str, int]
    cases: tuple[M8ReplayCase, ...] = Field(min_length=35, max_length=35)

    @model_validator(mode="after")
    def exact_partition(self) -> M8ReplaySummary:
        if sum(self.classification_counts.values()) != 35:
            raise ValueError("M8 replay classification counts must sum to 35")
        if len({case.case_id for case in self.cases}) != 35:
            raise ValueError("M8 replay cases must be unique")
        observed = Counter(case.classification for case in self.cases)
        if dict(sorted(observed.items())) != dict(sorted(self.classification_counts.items())):
            raise ValueError("M8 replay classification summary does not match cases")
        return self


class OracleEvidence(_DiagnosisModel):
    oracle_id: str
    sql: str
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    replay_matches_oracle: bool


class FalseAcceptForensic(_DiagnosisModel):
    case_id: str
    scenario: Literal["EXTRA_GRAIN", "OUTPUT_SHAPE"]
    source_run_ids: tuple[str, ...]
    source_observed_tables: tuple[str, ...]
    source_observed_columns: tuple[str, ...]
    replay_response_type: str
    replay_repair_count: int
    replay_reproduced_source_shape: bool
    requirement_state: dict[str, Any] | None
    planner_context: dict[str, Any] | None
    query_plan: dict[str, Any] | None
    sql: str | None
    execution_result: dict[str, Any] | None
    verification_trace: dict[str, Any] | None
    oracle: OracleEvidence
    planning_attempts: tuple[dict[str, Any], ...]
    admission_attempts: tuple[dict[str, Any], ...]
    repair_attempts: tuple[dict[str, Any], ...]
    earliest_semantic_divergence: str
    ownership: Literal[
        "M9_PLANNING",
        "M12_VERIFICATION_COVERAGE",
        "BOTH_M9_AND_M12",
        "ORACLE_SPEC_DEFECT_REQUIRING_HUMAN_REVIEW",
    ]
    rationale: str
    remediation_regression_milestones: tuple[str, ...]
    evidence_limitation: str | None = None


class BehavioralDiagnosisReport(_DiagnosisModel):
    version: Literal["m15-behavioral-diagnosis-v0.1"] = "m15-behavioral-diagnosis-v0.1"
    identity: DiagnosticIdentity
    m8_replay: M8ReplaySummary
    false_accept_forensics: tuple[FalseAcceptForensic, ...] = Field(min_length=6, max_length=6)
    recommended_frozen_milestones_to_reopen: dict[str, tuple[str, ...]]
    remediation_regression_case_ids: dict[str, tuple[str, ...]]
    evidence_limitations: tuple[str, ...]
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def exact_forensic_partition(self) -> BehavioralDiagnosisReport:
        observed = {item.case_id for item in self.false_accept_forensics}
        if observed != set(_FALSE_ACCEPT_SCENARIOS):
            raise ValueError("false-accept forensics must cover exactly the six retained cases")
        return self


@dataclass(frozen=True)
class _RecordedStructuredCall:
    outcome: StructuredModelCallOutcome
    response: BaseModel | None


class _RecordingChatModel:
    def __init__(self, delegate: ChatModel) -> None:
        self._delegate = delegate
        self.calls: list[_RecordedStructuredCall] = []

    async def structured(
        self,
        *,
        messages: list[dict[str, str]],
        response_type: type[StructuredResultT],
        purpose: str,
    ) -> StructuredResultT:
        started = time.monotonic()
        try:
            response = await self._delegate.structured(
                messages=messages,
                response_type=response_type,
                purpose=purpose,
            )
        except Exception as error:
            duration_ms = max(0, round((time.monotonic() - started) * 1000))
            status: StructuredCallStatus
            if isinstance(error, ModelTimeoutError):
                status = "TIMEOUT"
            elif isinstance(error, ModelContractError):
                status = "INVALID_STRUCTURED_OUTPUT"
            elif isinstance(error, ModelResponseError):
                status = "OUTPUT_INCOMPLETE"
            elif isinstance(error, ModelTransportError):
                status = "PROVIDER_ERROR"
            else:
                status = "UNEXPECTED_FAILURE"
            self.calls.append(
                _RecordedStructuredCall(
                    outcome=StructuredModelCallOutcome(
                        purpose=purpose,
                        response_type=response_type.__name__,
                        status=status,
                        duration_ms=duration_ms,
                        error_type=type(error).__name__,
                        error_detail=str(error)[:512],
                    ),
                    response=None,
                )
            )
            raise
        duration_ms = max(0, round((time.monotonic() - started) * 1000))
        self.calls.append(
            _RecordedStructuredCall(
                outcome=StructuredModelCallOutcome(
                    purpose=purpose,
                    response_type=response_type.__name__,
                    status="SUCCEEDED",
                    duration_ms=duration_ms,
                ),
                response=response,
            )
        )
        return response


def _git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _assert_frozen_runtime_source(source_commit: str) -> None:
    result = subprocess.run(
        [
            "git",
            "diff",
            "--quiet",
            source_commit,
            "--",
            "src",
            "evals/golden.yaml",
            "evals/oracles.yaml",
        ],
        cwd=REPOSITORY_ROOT,
        check=False,
    )
    if result.returncode != 0:
        raise DiagnosisError(
            "runtime, Golden, or Oracle source differs from the effect-acceptance commit"
        )


def _fingerprinted(model: type[BaseModel], payload: dict[str, Any]) -> BaseModel:
    canonical = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return model.model_validate(
        {**payload, "fingerprint": hashlib.sha256(canonical.encode("utf-8")).hexdigest()}
    )


def _load_retained_evidence() -> tuple[
    FinalAcceptanceReport,
    BehavioralAttributionReport,
    dict[str, GoldenCaseResult],
]:
    try:
        source = FinalAcceptanceReport.model_validate_json(
            SOURCE_REPORT_PATH.read_text(encoding="utf-8")
        )
        attribution = BehavioralAttributionReport.model_validate_json(
            ATTRIBUTION_EVIDENCE_PATH.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError) as error:
        raise DiagnosisError("retained M15 evidence is unavailable or invalid") from error
    if source.environment.fingerprint != attribution.source_environment_fingerprint:
        raise DiagnosisError("attribution and source acceptance environments do not match")
    return source, attribution, {case.id: case for case in source.golden.cases}


def _build_identity(
    *,
    source: FinalAcceptanceReport,
    attribution: BehavioralAttributionReport,
    diagnostics: ModelRuntimeDiagnostics,
    settings: Settings,
) -> DiagnosticIdentity:
    expected = source.environment
    if not isinstance(expected, EvaluationEnvironmentV01):
        raise DiagnosisError(
            "the frozen targeted diagnosis accepts only retained v0.1 effect evidence"
        )
    actual = {
        "chat model fingerprint": diagnostics.chat.value,
        "embedding model fingerprint": diagnostics.embedding.value,
        "Ollama runtime version": diagnostics.runtime_version,
        "dialogue prompt version": DIALOGUE_PROMPT_VERSION,
        "request timeout": settings.ollama_request_timeout_seconds,
        "max output tokens": settings.ollama_max_output_tokens,
    }
    required = {
        "chat model fingerprint": expected.chat_model_fingerprint,
        "embedding model fingerprint": expected.embedding_model_fingerprint,
        "Ollama runtime version": expected.ollama_runtime_version,
        "dialogue prompt version": expected.dialogue_prompt_version,
        "request timeout": expected.ollama_request_timeout_seconds,
        "max output tokens": expected.ollama_max_output_tokens,
    }
    mismatches = [name for name in required if actual[name] != required[name]]
    if mismatches:
        raise DiagnosisError(f"effect-acceptance environment identity drifted: {mismatches}")
    _assert_frozen_runtime_source(expected.git_commit)
    payload = {
        "source_environment": expected.model_dump(mode="json"),
        "source_attribution_fingerprint": attribution.fingerprint,
        "diagnostic_git_commit": _git_commit(),
        "runtime_source_diff_from_effect_commit": "EMPTY",
        "chat_model": diagnostics.chat.model,
        "chat_model_digest": diagnostics.chat.digest,
        "chat_model_fingerprint": diagnostics.chat.value,
        "embedding_model_fingerprint": diagnostics.embedding.value,
        "ollama_runtime_version": diagnostics.runtime_version,
        "dialogue_prompt_version": DIALOGUE_PROMPT_VERSION,
        "ollama_request_timeout_seconds": settings.ollama_request_timeout_seconds,
        "ollama_max_output_tokens": settings.ollama_max_output_tokens,
    }
    return cast(DiagnosticIdentity, _fingerprinted(DiagnosticIdentity, payload))


def _expected_action(expected_type: str) -> str:
    return {
        "result": DialogueAction.READY.value,
        "clarification": DialogueAction.ASK_CLARIFICATION.value,
        "failure": DialogueAction.CANNOT_RESOLVE.value,
    }[expected_type]


def _stored_action(response_type: str) -> str:
    return {
        "result": DialogueAction.READY.value,
        "clarification": DialogueAction.ASK_CLARIFICATION.value,
        "failure": DialogueAction.CANNOT_RESOLVE.value,
    }[response_type]


def _classify_m8_case(turns: tuple[M8ReplayTurn, ...]) -> str:
    if any(
        turn.structured_model_call_outcome.status != "SUCCEEDED"
        or turn.normalization_or_policy_error is not None
        for turn in turns
    ):
        return "STANDALONE_STRUCTURED_MODEL_FAILURE"
    if any(
        turn.original_stored_e2e_action == DialogueAction.ASK_CLARIFICATION.value
        and turn.standalone_m8_action == DialogueAction.READY.value
        for turn in turns
    ):
        return "STANDALONE_READY_E2E_CLARIFIED"
    if all(turn.standalone_m8_action == DialogueAction.ASK_CLARIFICATION.value for turn in turns):
        return "STANDALONE_M8_ALSO_CLARIFIES"
    return "SPEC_ORACLE_REVIEW_REQUIRED"


async def _replay_m8(
    *,
    suite_cases: dict[str, GoldenCase],
    source_cases: dict[str, GoldenCaseResult],
    attribution: BehavioralAttributionReport,
    chat_model: ChatModel,
    identity: DiagnosticIdentity,
) -> M8ReplaySummary:
    selected = next(
        bucket
        for bucket in attribution.terminal_buckets
        if bucket.bucket is TerminalBucket.UNEXPECTED_CLARIFICATION
    )
    if selected.count != 35:
        raise DiagnosisError("retained unnecessary-clarification attribution is not 35 cases")
    cases: list[M8ReplayCase] = []
    for case_attribution in selected.cases:
        case = suite_cases[case_attribution.case_id]
        original = source_cases[case.id]
        if len(original.response_types) != len(case.turns):
            raise DiagnosisError(f"source turn alignment is incomplete: {case.id}")
        recorder = _RecordingChatModel(chat_model)
        engine = DialogueEngine(chat_model=recorder)
        requirement = RequirementState(
            version="v0.1",
            status=RequirementStatus.INCOMPLETE,
        )
        last_question: str | None = None
        replayed_turns: list[M8ReplayTurn] = []
        for turn_number, turn in enumerate(case.turns, start=1):
            call_start = len(recorder.calls)
            proposal: DialogueProposal | None = None
            decision_payload: dict[str, Any] | None = None
            patch_payload: dict[str, Any] | None = None
            merged_payload: dict[str, Any] | None = None
            action: str | None = None
            blockers: tuple[DialogueBlocker, ...] = ()
            normalization_error: str | None = None
            try:
                decision = await engine.propose(
                    requirement=requirement,
                    latest_user_message=turn.content,
                    last_assistant_clarification=last_question,
                )
                recorded = recorder.calls[-1]
                if isinstance(recorded.response, DialogueProposal):
                    proposal = recorded.response
                    blockers = tuple(
                        DialogueBlocker(
                            field=str(item.field),
                            subject_term=str(item.subject_term),
                        )
                        for item in proposal.resolution.unresolved_replace
                        if item.blocking
                    )
                outcome = engine.resolve(requirement=requirement, decision=decision)
                action = decision.action.value
                decision_payload = decision.model_dump(mode="json")
                patch_payload = decision.patch.model_dump(mode="json")
                merged_payload = outcome.requirement.model_dump(mode="json")
                requirement = outcome.requirement
                last_question = (
                    str(decision.question)
                    if decision.action is DialogueAction.ASK_CLARIFICATION
                    else None
                )
            except Exception as error:
                normalization_error = f"{type(error).__name__}: {str(error)[:512]}"
            if len(recorder.calls) != call_start + 1:
                raise DiagnosisError(f"dialogue replay did not make exactly one call: {case.id}")
            call = recorder.calls[-1]
            if proposal is None and isinstance(call.response, DialogueProposal):
                proposal = call.response
                blockers = tuple(
                    DialogueBlocker(
                        field=str(item.field),
                        subject_term=str(item.subject_term),
                    )
                    for item in proposal.resolution.unresolved_replace
                    if item.blocking
                )
            replayed_turns.append(
                M8ReplayTurn(
                    turn_number=turn_number,
                    user_message=turn.content,
                    expected_action=_expected_action(turn.expected_type),
                    original_stored_e2e_action=_stored_action(
                        original.response_types[turn_number - 1]
                    ),
                    standalone_m8_action=action,
                    blockers=blockers,
                    structured_dialogue_proposal=(
                        None if proposal is None else proposal.model_dump(mode="json")
                    ),
                    normalized_dialogue_decision=decision_payload,
                    requirement_patch=patch_payload,
                    merged_requirement_state=merged_payload,
                    structured_model_call_outcome=call.outcome,
                    normalization_or_policy_error=normalization_error,
                    prompt_model_environment_identity=identity.fingerprint,
                )
            )
        replay_tuple = tuple(replayed_turns)
        cases.append(
            M8ReplayCase(
                case_id=case.id,
                classification=cast(Any, _classify_m8_case(replay_tuple)),
                turns=replay_tuple,
            )
        )
        print(
            f"M8 targeted replay {case.id}: {cases[-1].classification} "
            f"({sum(turn.structured_model_call_outcome.duration_ms for turn in replay_tuple)} ms)"
        )
    classifications = Counter(case.classification for case in cases)
    blocker_fields = Counter(
        blocker.field for case in cases for turn in case.turns for blocker in turn.blockers
    )
    return M8ReplaySummary(
        case_count=35,
        classification_counts=dict(sorted(classifications.items())),
        blocker_field_distribution=dict(sorted(blocker_fields.items())),
        cases=tuple(cases),
    )


class _RecordingRetriever:
    def __init__(self, delegate: HybridRetriever) -> None:
        self._delegate = delegate
        self.traces: list[RetrievalTrace] = []

    async def retrieve(self, query: str) -> RetrievalTrace:
        trace = await self._delegate.retrieve(query)
        self.traces.append(trace)
        return trace


class _RecordingPlanner(QueryPlanner):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.traces: list[PlanningTrace] = []

    async def plan(
        self,
        *,
        requirement: RequirementState,
        retrieval: RetrievalResult,
        catalog: AssembledSemanticCatalog,
        expected_retrieval_index_fingerprint: str,
    ) -> PlanningTrace:
        trace = await super().plan(
            requirement=requirement,
            retrieval=retrieval,
            catalog=catalog,
            expected_retrieval_index_fingerprint=expected_retrieval_index_fingerprint,
        )
        self.traces.append(trace)
        return trace


@dataclass(frozen=True)
class _AdmissionRecord:
    plan: QueryPlan
    planner_context_fingerprint: str
    outcome: SQLAdmissionOutcome


class _RecordingAdmission(SQLAdmissionService):
    def __init__(self, delegate: SQLAdmissionService) -> None:
        self._delegate = delegate
        self.records: list[_AdmissionRecord] = []

    def admit(
        self,
        plan: QueryPlan,
        *,
        planner_context_fingerprint: str,
    ) -> SQLAdmissionOutcome:
        outcome = self._delegate.admit(
            plan,
            planner_context_fingerprint=planner_context_fingerprint,
        )
        self.records.append(
            _AdmissionRecord(
                plan=plan,
                planner_context_fingerprint=planner_context_fingerprint,
                outcome=outcome,
            )
        )
        return outcome


@dataclass(frozen=True)
class _RuntimeRecord:
    guarded_query: GuardedQuery
    evidence: RuntimeExecutionEvidence


class _RuntimePort(Protocol):
    def execute_with_evidence(self, query: GuardedQuery) -> RuntimeExecutionEvidence: ...


class _RecordingQueryRuntime:
    def __init__(self, delegate: _RuntimePort) -> None:
        self._delegate = delegate
        self.records: list[_RuntimeRecord] = []

    def execute_with_evidence(self, query: GuardedQuery) -> RuntimeExecutionEvidence:
        evidence = self._delegate.execute_with_evidence(query)
        self.records.append(_RuntimeRecord(guarded_query=query, evidence=evidence))
        return evidence


@dataclass(frozen=True)
class _VerificationRecord:
    context: VerificationContext
    trace: VerificationTrace


class _RecordingVerifier(DeterministicVerifier):
    def __init__(self) -> None:
        self.records: list[_VerificationRecord] = []

    def verify(self, context: VerificationContext) -> VerificationTrace:
        trace = super().verify(context)
        self.records.append(_VerificationRecord(context=context, trace=trace))
        return trace


class _RecordingRepair(BoundedRepairService):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.outcomes: list[RepairPipelineOutcome] = []

    async def repair(self, **kwargs: Any) -> RepairPipelineOutcome:
        outcome = await super().repair(**kwargs)
        self.outcomes.append(outcome)
        return outcome


class _M12StopSynthesizer(AnswerSynthesizer):
    async def synthesize(self, context: Any) -> AnswerSynthesisResult:
        context.verify_integrity()
        return AnswerSynthesisResult(
            answer="M15 diagnostic stopped after capturing verified evidence.",
            evidence_refs=(),
            mode=AnswerSynthesisMode.DETERMINISTIC_FALLBACK,
            reason="M15_DIAGNOSTIC_M12_STOP",
        )


@dataclass(frozen=True)
class _ForensicApplication:
    application: ConversationApplication
    chat: _RecordingChatModel
    retriever: _RecordingRetriever
    planner: _RecordingPlanner
    admission: _RecordingAdmission
    runtime: _RecordingQueryRuntime
    verifier: _RecordingVerifier
    repair: _RecordingRepair


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _build_forensic_application(
    *,
    settings: Settings,
    diagnostics: ModelRuntimeDiagnostics,
    chat_model: ChatModel,
    embedding_model: OllamaEmbeddingModel,
) -> _ForensicApplication:
    authority = load_current_catalog_authority()
    index = load_retrieval_index(
        catalog=authority.assembled,
        current_generated_schema_fingerprint=authority.generated.fingerprint,
        current_semantic_revision=authority.curated.semantic_revision,
        embedding_fingerprint=diagnostics.embedding,
        model_runtime_version=diagnostics.runtime_version,
    )
    recording_chat = _RecordingChatModel(chat_model)
    retriever = _RecordingRetriever(
        HybridRetriever(
            index=index,
            catalog=authority.assembled,
            embedding_model=embedding_model,
            embedding_fingerprint=diagnostics.embedding,
            model_runtime_version=diagnostics.runtime_version,
            lexical_top_k=settings.retrieval_lexical_top_k,
            semantic_top_k=settings.retrieval_semantic_top_k,
            seed_table_limit=settings.retrieval_seed_tables,
            max_relationship_hops=settings.max_relationship_hops,
            max_total_tables=settings.max_retrieved_tables,
            rrf_k=settings.retrieval_rrf_k,
        )
    )
    runs = MySQLRunRepository(settings)
    uow = MySQLDialogueTurnStore(settings)
    admission = _RecordingAdmission(build_sql_admission_service(settings))
    runtime = _RecordingQueryRuntime(build_readonly_query_runtime(settings))
    verifier = _RecordingVerifier()
    planner = _RecordingPlanner(
        chat_model=recording_chat,
        model_fingerprint=diagnostics.chat.value,
        runtime_version=diagnostics.runtime_version,
    )
    dialogue = DialogueService(
        engine=DialogueEngine(chat_model=recording_chat),
        store=uow,
        clock=lambda: datetime.now(UTC),
        id_factory=_id,
    )
    repair = _RecordingRepair(
        chat_model=recording_chat,
        run_repository=runs,
        admission=admission,
        query_runtime=runtime,
        verifier=verifier,
        max_attempts=settings.max_sql_repair_attempts,
        model_fingerprint=diagnostics.chat.value,
        runtime_version=diagnostics.runtime_version,
        defer_terminal_transitions=True,
    )
    orchestrator = ConversationOrchestrator(
        dialogue=dialogue,
        unit_of_work=uow,
        runs=runs,
        retriever=retriever,
        planner=planner,
        catalog=authority.assembled,
        retrieval_index_fingerprint=index.fingerprint,
        admission=admission,
        query_runtime=runtime,
        verifier=verifier,
        repair=repair,
        synthesizer=_M12StopSynthesizer(chat_model=recording_chat),
        clock=lambda: datetime.now(UTC),
        id_factory=_id,
        traces=MySQLTraceRepository(settings),
    )
    application = ConversationApplication(
        sessions=MySQLSessionRepository(settings),
        runs=runs,
        orchestrator=orchestrator,
    )
    return _ForensicApplication(
        application=application,
        chat=recording_chat,
        retriever=retriever,
        planner=planner,
        admission=admission,
        runtime=runtime,
        verifier=verifier,
        repair=repair,
    )


def _serialize_planning(trace: PlanningTrace) -> dict[str, Any]:
    return {
        "planner_context": trace.context.model_dump(mode="json"),
        "planner_context_fingerprint": trace.planner_context_fingerprint,
        "query_plan": trace.plan.model_dump(mode="json"),
        "prompt_version": trace.prompt_version,
        "model_fingerprint": trace.model_fingerprint,
        "runtime_version": trace.runtime_version,
        "retrieval_index_fingerprint": trace.retrieval_index_fingerprint,
        "allowed_tables": list(trace.allowed_tables),
    }


def _serialize_admission(record: _AdmissionRecord) -> dict[str, Any]:
    guarded = record.outcome.guarded_query
    return {
        "query_plan": record.plan.model_dump(mode="json"),
        "planner_context_fingerprint": record.planner_context_fingerprint,
        "guard_status": record.outcome.guard.result.status.value,
        "guard_violations": [str(value) for value in record.outcome.guard.result.violations],
        "explain_accepted": (
            None
            if record.outcome.explain_result is None
            else record.outcome.explain_result.accepted
        ),
        "sql": None if guarded is None else guarded.sql,
        "guarded_query_fingerprint": (None if guarded is None else guarded.capability_fingerprint),
    }


def _serialize_repair(outcome: RepairPipelineOutcome) -> dict[str, Any]:
    return {
        "trace": outcome.trace.model_dump(mode="json"),
        "replacement_planning_trace": (
            None
            if outcome.replacement_planning_trace is None
            else _serialize_planning(outcome.replacement_planning_trace)
        ),
        "sql": None if outcome.guarded_query is None else outcome.guarded_query.sql,
        "execution_result": (
            None
            if outcome.execution_result is None
            else outcome.execution_result.model_dump(mode="json")
        ),
        "verification_trace": (
            None
            if outcome.verification_trace is None
            else outcome.verification_trace.model_dump(mode="json")
        ),
        "terminal_status": (
            None if outcome.terminal_status is None else outcome.terminal_status.value
        ),
        "terminal_error_code": outcome.terminal_error_code,
    }


def _forensic_ownership(
    *,
    case: GoldenCase,
    scenario: str,
    requirement: RequirementState | None,
    plan: QueryPlan | None,
    execution_columns: tuple[str, ...],
    verification: VerificationTrace | None,
    oracle_passed: bool,
) -> tuple[str, str, str, tuple[str, ...]]:
    if requirement is None or plan is None or verification is None:
        return (
            "ORACLE_SPEC_DEFECT_REQUIRING_HUMAN_REVIEW",
            "The targeted replay did not reach one complete M9-to-M12 evidence chain.",
            "Replay evidence ended before semantic divergence could be localized.",
            (),
        )
    expected = tuple(case.expected_columns)
    planned = tuple(str(column.name) for column in plan.expected_columns)
    verifier_false_accept = verification.result.status == "PASSED" and not oracle_passed
    if scenario == "EXTRA_GRAIN":
        requirement_diverged = requirement.grain is not None or bool(requirement.dimensions)
        planning_diverged = (
            len(planned) != len(expected)
            or set(planned) != set(expected)
            or len(execution_columns) != len(expected)
            or set(execution_columns) != set(expected)
        )
        if requirement_diverged:
            return (
                "ORACLE_SPEC_DEFECT_REQUIRING_HUMAN_REVIEW",
                "RequirementState already carries a grouping dimension or grain despite the "
                "explicit ungrouped request; the allowed M9/M12 owner set cannot safely assign "
                "that upstream divergence.",
                "RequirementState",
                ("M8",),
            )
    else:
        requirement_names = {
            str(value.resolved_name)
            for value in requirement.metrics
            if value.resolved_name is not None
        }
        requirement_names.update(
            str(value.resolved_name)
            for value in requirement.dimensions
            if value.resolved_name is not None
        )
        if not set(expected).issubset(requirement_names):
            return (
                "ORACLE_SPEC_DEFECT_REQUIRING_HUMAN_REVIEW",
                "The explicit output alias is absent from canonical RequirementState, so M9 and "
                "M12 cannot be assigned without reviewing the M8/output-shape contract.",
                "RequirementState",
                ("M8",),
            )
        planning_diverged = set(planned) != set(expected) or set(execution_columns) != set(expected)
    if planning_diverged and verifier_false_accept:
        return (
            "BOTH_M9_AND_M12",
            "Query planning introduced a result shape outside the explicit requested output, "
            "and M12 still returned PASSED because that negative shape invariant is not encoded.",
            "QueryPlan",
            ("M9", "M12"),
        )
    if planning_diverged:
        return (
            "M9_PLANNING",
            "The earliest replay divergence is the QueryPlan/result projection.",
            "QueryPlan",
            ("M9",),
        )
    if verifier_false_accept:
        return (
            "M12_VERIFICATION_COVERAGE",
            "Planning preserved the requested shape, but M12 PASSED a result that failed the "
            "static Oracle.",
            "VerificationTrace",
            ("M12",),
        )
    return (
        "ORACLE_SPEC_DEFECT_REQUIRING_HUMAN_REVIEW",
        "The targeted replay did not reproduce the retained false-accept behavior.",
        "Retained source result versus targeted replay",
        (),
    )


async def _run_false_accept_forensics(
    *,
    settings: Settings,
    diagnostics: ModelRuntimeDiagnostics,
    chat_model: ChatModel,
    embedding_model: OllamaEmbeddingModel,
    suite_cases: dict[str, GoldenCase],
    source_cases: dict[str, GoldenCaseResult],
) -> tuple[FalseAcceptForensic, ...]:
    suite, _ = load_golden()
    oracles = load_oracles(suite)
    forensic = _build_forensic_application(
        settings=settings,
        diagnostics=diagnostics,
        chat_model=chat_model,
        embedding_model=embedding_model,
    )
    reports: list[FalseAcceptForensic] = []
    for case_id, scenario in _FALSE_ACCEPT_SCENARIOS.items():
        case = suite_cases[case_id]
        source = source_cases[case_id]
        offsets = {
            "planning": len(forensic.planner.traces),
            "admission": len(forensic.admission.records),
            "runtime": len(forensic.runtime.records),
            "verification": len(forensic.verifier.records),
            "repair": len(forensic.repair.outcomes),
        }
        session = forensic.application.create_session()
        response: ConversationResponse | None = None
        for turn in case.turns:
            response = await forensic.application.process_message(
                session_id=session.id,
                content=turn.content,
            )
        if response is None:
            raise DiagnosisError(f"targeted forensic made no turn: {case_id}")
        planning_records = forensic.planner.traces[offsets["planning"] :]
        admission_records = forensic.admission.records[offsets["admission"] :]
        verification_records = forensic.verifier.records[offsets["verification"] :]
        repair_records = forensic.repair.outcomes[offsets["repair"] :]
        final_verification = next(
            (
                item
                for item in reversed(verification_records)
                if item.trace.result.status == "PASSED"
            ),
            None,
        )
        requirement: RequirementState | None = None
        plan: QueryPlan | None = None
        planner_context: dict[str, Any] | None = None
        sql: str | None = None
        execution_result: dict[str, Any] | None = None
        verification_trace: dict[str, Any] | None = None
        execution_columns: tuple[str, ...] = ()
        if final_verification is not None:
            context = final_verification.context
            requirement = context.planning_trace.context.requirement
            plan = context.planning_trace.plan
            planner_context = context.planning_trace.context.model_dump(mode="json")
            sql = context.guarded_query.sql
            execution_result = context.execution_result.model_dump(mode="json")
            verification_trace = final_verification.trace.model_dump(mode="json")
            execution_columns = tuple(str(value) for value in context.execution_result.columns)
        if case.oracle is None:
            raise DiagnosisError(f"false-accept case has no Oracle: {case_id}")
        oracle_sql = oracles.queries[case.oracle]
        oracle_columns, oracle_rows = _oracle_result(settings, oracle_sql)
        replay_rows: tuple[tuple[Any, ...], ...] = ()
        if final_verification is not None:
            replay_rows = tuple(
                tuple(row) for row in final_verification.context.execution_result.rows
            )
        replay_canonical = _canonical_rows(
            execution_columns,
            replay_rows,
            case.expected_columns,
        )
        oracle_canonical = _canonical_rows(
            oracle_columns,
            oracle_rows,
            case.expected_columns,
        )
        oracle_passed = (
            replay_canonical is not None
            and oracle_canonical is not None
            and replay_canonical == oracle_canonical
        )
        ownership, rationale, divergence, milestones = _forensic_ownership(
            case=case,
            scenario=scenario,
            requirement=requirement,
            plan=plan,
            execution_columns=execution_columns,
            verification=None if final_verification is None else final_verification.trace,
            oracle_passed=oracle_passed,
        )
        replay_response_type = response.type
        replay_repair_count = (
            response.evidence.repair_count if isinstance(response, ResultResponse) else 0
        )
        replay_tables = (
            tuple(sorted(value.split(".")[-1] for value in response.evidence.tables))
            if isinstance(response, ResultResponse)
            else ()
        )
        replay_reproduced = (
            isinstance(response, ResultResponse)
            and tuple(response.data.columns) == source.observed_columns
            and replay_tables == source.observed_tables
            and not oracle_passed
        )
        limitation = None
        if not replay_reproduced:
            limitation = (
                "The exact effect-bound targeted replay did not reproduce both retained public "
                "shape and Oracle failure; ownership is limited to the replay evidence plus the "
                "retained source projection."
            )
        reports.append(
            FalseAcceptForensic(
                case_id=case_id,
                scenario=scenario,
                source_run_ids=source.run_ids,
                source_observed_tables=source.observed_tables,
                source_observed_columns=source.observed_columns,
                replay_response_type=replay_response_type,
                replay_repair_count=replay_repair_count,
                replay_reproduced_source_shape=replay_reproduced,
                requirement_state=(
                    None if requirement is None else requirement.model_dump(mode="json")
                ),
                planner_context=planner_context,
                query_plan=None if plan is None else plan.model_dump(mode="json"),
                sql=sql,
                execution_result=execution_result,
                verification_trace=verification_trace,
                oracle=OracleEvidence(
                    oracle_id=case.oracle,
                    sql=oracle_sql,
                    columns=oracle_columns,
                    rows=oracle_rows,
                    replay_matches_oracle=oracle_passed,
                ),
                planning_attempts=tuple(_serialize_planning(item) for item in planning_records),
                admission_attempts=tuple(_serialize_admission(item) for item in admission_records),
                repair_attempts=tuple(_serialize_repair(item) for item in repair_records),
                earliest_semantic_divergence=divergence,
                ownership=cast(Any, ownership),
                rationale=rationale,
                remediation_regression_milestones=milestones,
                evidence_limitation=limitation,
            )
        )
        print(
            f"False-accept forensic {case_id}: owner={ownership}, "
            f"reproduced={replay_reproduced}, response={replay_response_type}"
        )
    return tuple(reports)


def _recommendations(
    m8: M8ReplaySummary,
    forensics: tuple[FalseAcceptForensic, ...],
) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    milestones: dict[str, set[str]] = {}
    regressions: dict[str, set[str]] = {}
    for case in m8.cases:
        if case.classification == "STANDALONE_M8_ALSO_CLARIFIES":
            milestones.setdefault("M8", set()).add(case.case_id)
            regressions.setdefault("M8_DIALOGUE", set()).add(case.case_id)
        elif case.classification == "STANDALONE_READY_E2E_CLARIFIED":
            milestones.setdefault("M15_INTEGRATION_CONTEXT", set()).add(case.case_id)
            regressions.setdefault("M15_DIALOGUE_INTEGRATION", set()).add(case.case_id)
        elif case.classification == "STANDALONE_STRUCTURED_MODEL_FAILURE":
            milestones.setdefault("M8_MODEL_ADAPTER", set()).add(case.case_id)
            regressions.setdefault("M8_STRUCTURED_FAILURE", set()).add(case.case_id)
        else:
            milestones.setdefault("HUMAN_SPEC_REVIEW", set()).add(case.case_id)
    for item in forensics:
        for milestone in item.remediation_regression_milestones:
            milestones.setdefault(milestone, set()).add(item.case_id)
            regressions.setdefault(f"{milestone}_FALSE_ACCEPT", set()).add(item.case_id)
        if not item.remediation_regression_milestones:
            milestones.setdefault("HUMAN_SPEC_REVIEW", set()).add(item.case_id)
    return (
        {key: tuple(sorted(value)) for key, value in sorted(milestones.items())},
        {key: tuple(sorted(value)) for key, value in sorted(regressions.items())},
    )


def _build_report(
    *,
    identity: DiagnosticIdentity,
    m8: M8ReplaySummary,
    forensics: tuple[FalseAcceptForensic, ...],
) -> BehavioralDiagnosisReport:
    milestones, regressions = _recommendations(m8, forensics)
    limitations = (
        "The original six successful pipeline objects were not retained by latest.json and the "
        "clean reset removed their database rows; Task B therefore uses exact-identity targeted "
        "replays and preserves whether each source shape was reproduced.",
        "No hidden reasoning or free-form chain-of-thought is captured; only typed structured "
        "outputs and deterministic pipeline evidence are reported.",
        "The forensic composition replaces M14 synthesis only after M12 evidence is captured, so "
        "the six-case diagnostic makes no M14 model calls or M14 behavior claim.",
    )
    payload = {
        "version": "m15-behavioral-diagnosis-v0.1",
        "identity": identity.model_dump(mode="json"),
        "m8_replay": m8.model_dump(mode="json"),
        "false_accept_forensics": [item.model_dump(mode="json") for item in forensics],
        "recommended_frozen_milestones_to_reopen": milestones,
        "remediation_regression_case_ids": regressions,
        "evidence_limitations": limitations,
    }
    return cast(BehavioralDiagnosisReport, _fingerprinted(BehavioralDiagnosisReport, payload))


def format_diagnosis_summary(report: BehavioralDiagnosisReport) -> str:
    lines = [
        "# M15 Targeted Behavioral Diagnosis",
        "",
        f"- Report fingerprint: `{report.fingerprint}`",
        f"- Source effect environment: `{report.identity.source_environment.fingerprint}`",
        f"- Chat model fingerprint: `{report.identity.chat_model_fingerprint}`",
        f"- Ollama: `{report.identity.ollama_runtime_version}`",
        f"- Dialogue prompt: `{report.identity.dialogue_prompt_version}`",
        f"- Bounds: timeout `{report.identity.ollama_request_timeout_seconds}s`, "
        f"num_predict `{report.identity.ollama_max_output_tokens}`",
        "- PR #15 disposition: **Draft; not ready for substantive review**",
        "",
        "## Targeted M8 replay (exactly 35 cases)",
        "",
    ]
    for classification, count in report.m8_replay.classification_counts.items():
        lines.append(f"- `{classification}`: {count}")
    clarification_turn_count = sum(len(case.turns) for case in report.m8_replay.cases)
    blocker_occurrence_count = sum(report.m8_replay.blocker_field_distribution.values())
    lines.extend(
        [
            "",
            f"Blocking ambiguity occurrences: {blocker_occurrence_count} across "
            f"{clarification_turn_count} replayed turns. Counts are ambiguity occurrences, so "
            "they need not sum to the 35-case partition.",
            "",
            "Blocker fields:",
        ]
    )
    for field, count in report.m8_replay.blocker_field_distribution.items():
        lines.append(f"- `{field}`: {count}")
    lines.extend(
        [
            "",
            "| Case | Expected | Original E2E | Standalone M8 | Call outcome | "
            "Blocking subjects | Classification |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for case in report.m8_replay.cases:
        expected = ", ".join(turn.expected_action for turn in case.turns)
        original = ", ".join(turn.original_stored_e2e_action for turn in case.turns)
        standalone = ", ".join(str(turn.standalone_m8_action) for turn in case.turns)
        call_outcomes = ", ".join(turn.structured_model_call_outcome.status for turn in case.turns)
        blockers = (
            "; ".join(
                f"{item.field}:{item.subject_term}" for turn in case.turns for item in turn.blockers
            )
            or "—"
        )
        lines.append(
            f"| `{case.case_id}` | {expected} | {original} | {standalone} | "
            f"{call_outcomes} | {blockers} | `{case.classification}` |"
        )
    lines.extend(
        [
            "",
            "## M12 PASSED + Oracle FAILED forensics (exactly 6 cases)",
            "",
            "| Case | Scenario | Earliest divergence | Owner | Reproduced |",
            "|---|---|---|---|---|",
        ]
    )
    for item in report.false_accept_forensics:
        lines.append(
            f"| `{item.case_id}` | `{item.scenario}` | "
            f"{item.earliest_semantic_divergence} | `{item.ownership}` | "
            f"{'yes' if item.replay_reproduced_source_shape else 'no'} |"
        )
    lines.append("")
    for item in report.false_accept_forensics:
        lines.append(f"### `{item.case_id}`")
        lines.append("")
        requirement = item.requirement_state or {}
        dimensions = [
            f"{value.get('term')}→{value.get('resolved_name')}"
            for value in cast(list[dict[str, Any]], requirement.get("dimensions", []))
        ]
        metrics = [
            f"{value.get('term')}→{value.get('resolved_name')}"
            for value in cast(list[dict[str, Any]], requirement.get("metrics", []))
        ]
        planner_context = item.planner_context or {}
        query_plan = item.query_plan or {}
        execution = item.execution_result or {}
        verification = item.verification_trace or {}
        gaps = cast(list[dict[str, Any]], verification.get("coverage_gaps", []))
        unsupported = [
            str(gap.get("name")) for gap in gaps if gap.get("disposition") == "UNSUPPORTED"
        ]
        expected_columns = [
            value.get("name")
            for value in cast(list[dict[str, Any]], query_plan.get("expected_columns", []))
        ]
        verification_status = verification.get("result", {}).get("status") if verification else None
        lines.extend(
            [
                f"- RequirementState: grain=`{requirement.get('grain')}`; "
                f"metrics={metrics or ['—']}; dimensions={dimensions or ['—']}",
                f"- PlannerContext allowed tables: `{planner_context.get('allowed_tables', [])}`",
                f"- QueryPlan tables/columns: `{query_plan.get('tables', [])}` / "
                f"`{expected_columns}`",
                f"- Execution columns/rows: `{execution.get('columns', [])}` / "
                f"`{execution.get('returned_row_count')}`",
                f"- Verification: `{verification_status}`; "
                f"unsupported coverage={unsupported or ['—']}",
                f"- Oracle columns/rows/match: `{list(item.oracle.columns)}` / "
                f"`{len(item.oracle.rows)}` / `{item.oracle.replay_matches_oracle}`",
                f"- Earliest divergence / owner: `{item.earliest_semantic_divergence}` / "
                f"`{item.ownership}`",
                f"- Assessment: {item.rationale}",
                "- SQL:",
                "",
                "```sql",
                item.sql or "-- replay did not reach an admitted SQL capability",
                "```",
            ]
        )
        if item.evidence_limitation is not None:
            lines.append(f"- Replay limitation: {item.evidence_limitation}")
        lines.append("")
    lines.extend(["", "## Recommended frozen milestones to reopen", ""])
    for milestone, case_ids in report.recommended_frozen_milestones_to_reopen.items():
        lines.append(f"- `{milestone}`: {', '.join(f'`{value}`' for value in case_ids)}")
    lines.extend(["", "## Exact remediation regression IDs", ""])
    for gate, case_ids in report.remediation_regression_case_ids.items():
        lines.append(f"- `{gate}`: {', '.join(f'`{value}`' for value in case_ids)}")
    lines.extend(["", "## Evidence limits", ""])
    lines.extend(f"- {value}" for value in report.evidence_limitations)
    return "\n".join(lines) + "\n"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_m8_checkpoint(identity: DiagnosticIdentity) -> M8ReplaySummary | None:
    if not M8_CHECKPOINT_PATH.exists():
        return None
    try:
        replay = M8ReplaySummary.model_validate_json(M8_CHECKPOINT_PATH.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise DiagnosisError("existing M8 replay checkpoint is invalid") from error
    identities = {
        turn.prompt_model_environment_identity for case in replay.cases for turn in case.turns
    }
    if identities != {identity.fingerprint}:
        raise DiagnosisError("existing M8 replay checkpoint belongs to another environment")
    return replay


def _write_m8_checkpoint(replay: M8ReplaySummary) -> None:
    _write(
        M8_CHECKPOINT_PATH,
        json.dumps(
            replay.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )


async def run_diagnosis(
    *,
    settings: Settings,
    json_path: Path = DIAGNOSIS_JSON_PATH,
    markdown_path: Path = DIAGNOSIS_MARKDOWN_PATH,
) -> BehavioralDiagnosisReport:
    source, attribution, source_cases = _load_retained_evidence()
    suite, golden_fingerprint = load_golden()
    if golden_fingerprint != source.environment.golden_fingerprint:
        raise DiagnosisError("current Golden fingerprint differs from retained effect evidence")
    suite_cases = {case.id: case for case in suite.cases}
    diagnostics = await OllamaStartupDiagnostics(settings).diagnose()
    identity = _build_identity(
        source=source,
        attribution=attribution,
        diagnostics=diagnostics,
        settings=settings,
    )
    chat_model = OllamaChatModel(settings, fingerprint=diagnostics.chat)
    embedding_model = OllamaEmbeddingModel(settings, fingerprint=diagnostics.embedding)
    m8 = _load_m8_checkpoint(identity)
    if m8 is None:
        m8 = await _replay_m8(
            suite_cases=suite_cases,
            source_cases=source_cases,
            attribution=attribution,
            chat_model=chat_model,
            identity=identity,
        )
        _write_m8_checkpoint(m8)
    else:
        print(f"M8 targeted replay: resumed exact-identity checkpoint ({m8.case_count} cases)")
    forensics = await _run_false_accept_forensics(
        settings=settings,
        diagnostics=diagnostics,
        chat_model=chat_model,
        embedding_model=embedding_model,
        suite_cases=suite_cases,
        source_cases=source_cases,
    )
    report = _build_report(identity=identity, m8=m8, forensics=forensics)
    _write(
        json_path,
        json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    _write(markdown_path, format_diagnosis_summary(report))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", type=Path, default=DIAGNOSIS_JSON_PATH)
    parser.add_argument("--markdown-out", type=Path, default=DIAGNOSIS_MARKDOWN_PATH)
    args = parser.parse_args(argv)
    report = asyncio.run(
        run_diagnosis(
            settings=Settings(),  # type: ignore[call-arg]
            json_path=args.json_out,
            markdown_path=args.markdown_out,
        )
    )
    print(
        f"M15 targeted behavioral diagnosis: fingerprint={report.fingerprint}, "
        f"m8_cases={report.m8_replay.case_count}, "
        f"forensics={len(report.false_accept_forensics)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
