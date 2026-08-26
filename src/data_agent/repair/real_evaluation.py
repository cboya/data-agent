"""Bounded real-Ollama M13 smoke through a fresh M9-M12 branch."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from data_agent.config import Settings
from data_agent.contracts.query import ExpectedColumn, QueryPlan
from data_agent.contracts.retrieval import RetrievalHit, RetrievalResult
from data_agent.contracts.run import Run, RunStatus
from data_agent.contracts.session import Session, SessionStatus
from data_agent.model_runtime.ollama import OllamaChatModel
from data_agent.persistence.mysql.runs import MySQLRunRepository
from data_agent.persistence.mysql.sessions import MySQLSessionRepository
from data_agent.planning.evaluation import PlannerEvalCase, load_planner_eval_suite
from data_agent.planning.runtime import CurrentPlannerRuntime, load_current_planner_runtime
from data_agent.planning.service import PlanningTrace
from data_agent.query_runtime.runtime import build_readonly_query_runtime
from data_agent.repair.evidence import RepairFailure, RepairOutcomeKind, repair_failure_fingerprint
from data_agent.repair.failures import failure_from_admission, failure_from_verification
from data_agent.repair.prompt import QUERY_REPAIR_PROMPT_VERSION
from data_agent.repair.service import BoundedRepairService
from data_agent.sql_guard.capability import query_plan_fingerprint
from data_agent.sql_guard.runtime import build_sql_admission_service
from data_agent.verification.context import build_verification_context
from data_agent.verification.service import DeterministicVerifier

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
REAL_REPAIR_REPORT_PATH = REPOSITORY_ROOT / "evals" / "reports" / "repair-ollama-latest.json"

_VALID_SQL = (
    "SELECT DATE(fact_order.paid_at) AS period, "
    "SUM(fact_order.paid_amount) AS paid_amount FROM fact_order "
    "WHERE fact_order.paid_at >= DATE_SUB(CURRENT_DATE, INTERVAL 30 DAY) "
    "GROUP BY DATE(fact_order.paid_at) ORDER BY period"
)
type RealRepairCaseId = Literal["syntax", "unknown-column", "verification-alias"]


class _EvaluationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class RealRepairCaseResult(_EvaluationModel):
    id: RealRepairCaseId
    failure_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    prompt_version: str
    model_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_version: str
    repair_count: int = Field(ge=0)
    model_calls: int = Field(ge=0, le=1)
    outcome: str
    verification_passed: bool
    replacement_query_plan_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    failed_checks: tuple[str, ...] = ()
    error_type: str | None = None


class RealRepairMetrics(_EvaluationModel):
    case_count: Literal[3] = 3
    eligible_first_attempt_success: float = Field(ge=0, le=1)
    post_repair_m12_pass: float = Field(ge=0, le=1)
    bound_enforcement: float = Field(ge=0, le=1)


class RealRepairIdentity(_EvaluationModel):
    prompt_version: str
    model_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_version: str
    retrieval_index_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    catalog_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    generated_schema_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    max_attempts: int = Field(ge=0)


class RealRepairReport(_EvaluationModel):
    version: Literal["v0.1"] = "v0.1"
    identity: RealRepairIdentity
    metrics: RealRepairMetrics
    cases: tuple[RealRepairCaseResult, ...]
    passed: bool
    epistemic_boundary: Literal[
        "three-case-controlled-world-smoke; no-general-self-healing-claim"
    ] = "three-case-controlled-world-smoke; no-general-self-healing-claim"


def _case() -> PlannerEvalCase:
    return next(case for case in load_planner_eval_suite().cases if case.id == "paid-amount-daily")


def _retrieval(runtime: CurrentPlannerRuntime, case: PlannerEvalCase) -> RetrievalResult:
    catalog = runtime.retrieval.authority.assembled
    selected = set(case.retrieved_tables)
    return RetrievalResult(
        version="v0.1",
        query=str(case.requirement.goal),
        hits=[
            RetrievalHit(
                table=table,
                lexical_rank=rank if rank <= 4 else None,
                semantic_rank=rank if rank <= 4 else None,
                fused_score=1.0 / rank if rank <= 4 else 0.0,
                reason="frozen M13 real-repair schema slice",
                source="SEED" if rank <= 4 else "GRAPH_EXPANSION",
            )
            for rank, table in enumerate(case.retrieved_tables, start=1)
        ],
        relationships=[
            relationship
            for relationship in catalog.relationships
            if str(relationship.from_table) in selected and str(relationship.to_table) in selected
        ],
        index_fingerprint=runtime.retrieval.index.fingerprint,
    )


def _plan(sql: str) -> QueryPlan:
    return QueryPlan(
        version="v0.1",
        intent="Daily actual paid amount for the last 30 days",
        tables=["fact_order"],
        assumptions=[],
        sql=sql,
        expected_columns=[
            ExpectedColumn(name="period", semantic_role="day"),
            ExpectedColumn(name="paid_amount", semantic_role="metric"),
        ],
        explanation="Controlled M13 repair smoke input",
    )


def _original_trace(
    runtime: CurrentPlannerRuntime,
    case: PlannerEvalCase,
    plan: QueryPlan,
) -> PlanningTrace:
    context = runtime.planner.build_context(
        requirement=case.requirement,
        retrieval=_retrieval(runtime, case),
        catalog=runtime.retrieval.authority.assembled,
        expected_retrieval_index_fingerprint=runtime.retrieval.index.fingerprint,
    )
    return runtime.planner.accept(context=context, proposal=plan)


def _create_validating_run(settings: Settings, case: PlannerEvalCase) -> Run:
    now = datetime.now(UTC)
    session_id = f"m13_eval_session_{uuid4().hex}"
    run_id = f"m13_eval_run_{uuid4().hex}"
    MySQLSessionRepository(settings).create(
        Session(
            id=session_id,
            status=SessionStatus.ACTIVE,
            requirement=case.requirement,
            created_at=now,
            updated_at=now,
        )
    )
    repository = MySQLRunRepository(settings)
    current = repository.create(
        Run(id=run_id, session_id=session_id, status=RunStatus.RECEIVED, started_at=now)
    )
    for status in (
        RunStatus.UNDERSTANDING,
        RunStatus.RETRIEVING,
        RunStatus.PLANNING,
        RunStatus.VALIDATING,
    ):
        current = repository.transition(current.id, status, transitioned_at=now)
    return current


def _initial_failure(
    *,
    case_id: str,
    original: PlanningTrace,
    run: Run,
    settings: Settings,
) -> RepairFailure:
    admission_service = build_sql_admission_service(settings)
    admission = admission_service.admit(
        original.plan,
        planner_context_fingerprint=original.planner_context_fingerprint,
    )
    if case_id in {"syntax", "unknown-column"}:
        return failure_from_admission(original, admission)
    if admission.guarded_query is None:
        raise RuntimeError("verification smoke input did not pass M10")
    repository = MySQLRunRepository(settings)
    repository.transition(run.id, RunStatus.EXECUTING, transitioned_at=datetime.now(UTC))
    execution = build_readonly_query_runtime(settings).execute_with_evidence(
        admission.guarded_query
    )
    repository.transition(run.id, RunStatus.VERIFYING, transitioned_at=datetime.now(UTC))
    verification = DeterministicVerifier().verify(
        build_verification_context(
            planning_trace=original,
            guarded_query=admission.guarded_query,
            execution_metadata=execution.metadata,
            execution_result=execution.result,
        )
    )
    if verification.result.status != "FAILED":
        raise RuntimeError("verification smoke input unexpectedly passed M12")
    return failure_from_verification(original, admission.guarded_query, verification)


async def evaluate_real_repair(settings: Settings) -> RealRepairReport:
    runtime = await load_current_planner_runtime(settings)
    case = _case()
    inputs: tuple[tuple[RealRepairCaseId, QueryPlan], ...] = (
        ("syntax", _plan("SELECT ( FROM fact_order")),
        (
            "unknown-column",
            _plan(_VALID_SQL.replace("fact_order.paid_amount", "fact_order.missing_paid_amount")),
        ),
        ("verification-alias", _plan(_VALID_SQL.replace(" AS paid_amount", " AS wrong_alias"))),
    )
    results: list[RealRepairCaseResult] = []
    for raw_case_id, plan in inputs:
        case_id: RealRepairCaseId = raw_case_id
        run = _create_validating_run(settings, case)
        original = _original_trace(runtime, case, plan)
        failure: RepairFailure | None = None
        outcome_kind = "EVALUATION_ERROR"
        verification_passed = False
        model_calls = 0
        repair_count = run.repair_count
        error_type: str | None = None
        replacement_fingerprint: str | None = None
        failed_checks: tuple[str, ...] = ()
        try:
            failure = _initial_failure(
                case_id=case_id,
                original=original,
                run=run,
                settings=settings,
            )
            repairer = BoundedRepairService(
                chat_model=OllamaChatModel(
                    settings,
                    fingerprint=runtime.retrieval.diagnostics.chat,
                ),
                run_repository=MySQLRunRepository(settings),
                admission=build_sql_admission_service(settings),
                query_runtime=build_readonly_query_runtime(settings),
                max_attempts=settings.max_sql_repair_attempts,
                model_fingerprint=runtime.retrieval.diagnostics.chat.value,
                runtime_version=runtime.retrieval.diagnostics.runtime_version,
            )
            outcome = await repairer.repair(
                run_id=run.id,
                original=original,
                failure=failure,
            )
            outcome_kind = outcome.trace.outcome.value
            model_calls = 1 if outcome.trace.attempt == 1 else 0
            repair_count = outcome.run.repair_count
            verification_passed = (
                outcome.verification_trace is not None
                and outcome.verification_trace.result.status == "PASSED"
            )
            if outcome.replacement_planning_trace is not None:
                replacement_fingerprint = query_plan_fingerprint(
                    outcome.replacement_planning_trace.plan
                )
            if outcome.verification_trace is not None:
                failed_checks = tuple(
                    str(check.name)
                    for check in outcome.verification_trace.result.checks
                    if not check.passed
                )
        except Exception as error:
            error_type = type(error).__name__
            repair_count = MySQLRunRepository(settings).get(run.id).repair_count
        results.append(
            RealRepairCaseResult(
                id=case_id,
                failure_fingerprint=(
                    None if failure is None else repair_failure_fingerprint(failure)
                ),
                prompt_version=QUERY_REPAIR_PROMPT_VERSION,
                model_fingerprint=runtime.retrieval.diagnostics.chat.value,
                runtime_version=runtime.retrieval.diagnostics.runtime_version,
                repair_count=repair_count,
                model_calls=model_calls,
                outcome=outcome_kind,
                verification_passed=verification_passed,
                replacement_query_plan_fingerprint=replacement_fingerprint,
                failed_checks=failed_checks,
                error_type=error_type,
            )
        )
    success = sum(result.outcome == RepairOutcomeKind.SUCCEEDED.value for result in results) / 3
    m12_pass = sum(result.verification_passed for result in results) / 3
    bound = sum(result.repair_count <= settings.max_sql_repair_attempts for result in results) / 3
    metrics = RealRepairMetrics(
        eligible_first_attempt_success=success,
        post_repair_m12_pass=m12_pass,
        bound_enforcement=bound,
    )
    authority = runtime.retrieval.authority.assembled
    return RealRepairReport(
        identity=RealRepairIdentity(
            prompt_version=QUERY_REPAIR_PROMPT_VERSION,
            model_fingerprint=runtime.retrieval.diagnostics.chat.value,
            runtime_version=runtime.retrieval.diagnostics.runtime_version,
            retrieval_index_fingerprint=runtime.retrieval.index.fingerprint,
            catalog_fingerprint=authority.catalog_fingerprint,
            generated_schema_fingerprint=authority.generated_metadata_fingerprint,
            semantic_revision=authority.semantic_revision,
            max_attempts=settings.max_sql_repair_attempts,
        ),
        metrics=metrics,
        cases=tuple(results),
        passed=success == 1.0 and m12_pass == 1.0 and bound == 1.0,
    )


def write_real_repair_report(
    report: RealRepairReport,
    *,
    output_path: Path = REAL_REPAIR_REPORT_PATH,
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


def format_real_repair_summary(report: RealRepairReport) -> str:
    metrics = report.metrics
    status = "PASS" if report.passed else "FAIL"
    return (
        f"Real repair smoke {status}: cases={metrics.case_count}, "
        f"first_attempt={metrics.eligible_first_attempt_success:.3f}, "
        f"post_m12={metrics.post_repair_m12_pass:.3f}, "
        f"bound={metrics.bound_enforcement:.3f}"
    )
