"""Standalone M10 security and accepted-M9-proposal evaluation."""

from __future__ import annotations

import hashlib
import json
from importlib.metadata import version
from pathlib import Path
from typing import Any, Literal, Self

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from data_agent.contracts.execution import GuardStatus
from data_agent.contracts.query import QueryPlan
from data_agent.sql_guard.errors import SQLGuardEvaluationError
from data_agent.sql_guard.service import SQLAdmissionOutcome, SQLAdmissionService

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SQL_GUARD_EVAL_PATH = REPOSITORY_ROOT / "evals" / "sql_guard.yaml"
M9_PROPOSAL_SNAPSHOT_PATH = REPOSITORY_ROOT / "evals" / "m9-proposals-v0.3.json"
SQL_GUARD_REPORT_PATH = REPOSITORY_ROOT / "evals" / "reports" / "sql-guard-latest.json"


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


class SQLGuardEvalCase(_EvaluationModel):
    id: str = Field(min_length=1, pattern=r"\S")
    category: Literal[
        "valid",
        "scope",
        "authority",
        "statement",
        "write",
        "namespace",
        "function",
        "lock",
        "hint",
        "exfiltration",
    ]
    sql: str = Field(min_length=1)
    tables: tuple[str, ...] = Field(min_length=1)
    expected_guard: GuardStatus
    expected_explain: Literal["ACCEPTED"] | None = None

    @model_validator(mode="after")
    def expectation_is_consistent(self) -> Self:
        if len(self.tables) != len(set(self.tables)):
            raise ValueError("SQL guard eval tables must be unique")
        if self.expected_guard is GuardStatus.PASSED and self.expected_explain is None:
            raise ValueError("passed guard case requires an EXPLAIN expectation")
        if self.expected_guard is GuardStatus.REJECTED and self.expected_explain is not None:
            raise ValueError("rejected guard case cannot expect EXPLAIN")
        return self


class SQLGuardEvalSuite(_EvaluationModel):
    version: Literal["v0.1"]
    cases: tuple[SQLGuardEvalCase, ...] = Field(min_length=25)

    @model_validator(mode="after")
    def case_ids_are_unique(self) -> Self:
        case_ids = [case.id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("SQL guard eval case ids must be unique")
        return self


class M9ProposalIdentity(_EvaluationModel):
    suite_version: str
    prompt_version: str
    provider: str
    model: str
    model_digest: str
    model_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_version: str
    retrieval_index_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    catalog_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    generated_schema_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_revision: str = Field(pattern=r"^[0-9a-f]{64}$")


class M9ProposalSnapshotSource(_EvaluationModel):
    kind: Literal["accepted_m9_planner_report"]
    accepted_head: str = Field(pattern=r"^[0-9a-f]{7,40}$")
    squash_merged_main: str = Field(pattern=r"^[0-9a-f]{40}$")
    identity: M9ProposalIdentity


class M9ProposalCase(_EvaluationModel):
    id: str = Field(min_length=1, pattern=r"\S")
    plan: QueryPlan


class M9ProposalSnapshot(_EvaluationModel):
    version: Literal["v0.1"]
    source: M9ProposalSnapshotSource
    cases: tuple[M9ProposalCase, ...] = Field(min_length=20)

    @model_validator(mode="after")
    def case_ids_are_unique(self) -> Self:
        case_ids = [case.id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("M9 proposal snapshot case ids must be unique")
        return self


class SQLAdmissionCaseResult(_EvaluationModel):
    id: str
    source: Literal["security", "accepted_m9_proposal"]
    category: str
    guard_status: GuardStatus
    guard_correct: bool | None = None
    parse_succeeded: bool
    table_scope_compliant: bool | None = None
    referenced_tables: tuple[str, ...]
    unused_declared_tables: tuple[str, ...]
    guard_violations: tuple[str, ...]
    explain_accepted: bool | None = None
    explain_correct: bool | None = None
    explain_rejection_reason: str | None = None
    guarded_query_issued: bool


class SQLGuardEvalMetrics(_EvaluationModel):
    security_case_count: int = Field(ge=25)
    security_guard_accuracy: float = Field(ge=0, le=1)
    security_explain_accuracy: float = Field(ge=0, le=1)
    proposal_case_count: int = Field(ge=20)
    proposal_sql_parse_rate: float = Field(ge=0, le=1)
    proposal_guard_pass_rate: float = Field(ge=0, le=1)
    proposal_table_scope_compliance: float = Field(ge=0, le=1)
    proposal_explain_admission_rate: float = Field(ge=0, le=1)
    proposal_unused_declared_table_rate: float = Field(ge=0, le=1)


class SQLGuardEvalIdentity(_EvaluationModel):
    suite_version: str
    sqlglot_version: str
    sql_guard_policy_version: str
    explain_policy_version: str
    analytics_schema: str
    max_sql_characters: int
    max_explain_estimated_rows: int
    max_explain_characters: int
    max_explain_nodes: int
    m9_snapshot_version: str
    m9_snapshot_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    m9_accepted_head: str
    m9_squash_merged_main: str = Field(pattern=r"^[0-9a-f]{40}$")
    m9_prompt_version: str
    m9_model_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class SQLGuardEvalReport(_EvaluationModel):
    version: Literal["v0.1"] = "v0.1"
    identity: SQLGuardEvalIdentity
    metrics: SQLGuardEvalMetrics
    cases: tuple[SQLAdmissionCaseResult, ...]
    passed: bool
    epistemic_boundary: Literal[
        "guard-and-explain-only; no normal query execution or result correctness claim"
    ] = "guard-and-explain-only; no normal query execution or result correctness claim"


def load_sql_guard_eval_suite(path: Path = SQL_GUARD_EVAL_PATH) -> SQLGuardEvalSuite:
    try:
        payload = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeySafeLoader)
        return SQLGuardEvalSuite.model_validate(payload)
    except (OSError, yaml.YAMLError, ValidationError) as error:
        raise SQLGuardEvaluationError("SQL guard evaluation suite is missing or invalid") from error


def load_m9_proposal_snapshot(
    path: Path = M9_PROPOSAL_SNAPSHOT_PATH,
) -> tuple[M9ProposalSnapshot, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        snapshot = M9ProposalSnapshot.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        raise SQLGuardEvaluationError("M9 proposal snapshot is missing or invalid") from error
    canonical = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return snapshot, fingerprint


def _case_result(
    *,
    case_id: str,
    source: Literal["security", "accepted_m9_proposal"],
    category: str,
    outcome: SQLAdmissionOutcome,
    expected_guard: GuardStatus | None = None,
    expected_explain: bool | None = None,
) -> SQLAdmissionCaseResult:
    explain_accepted = None if outcome.explain_result is None else outcome.explain_result.accepted
    return SQLAdmissionCaseResult(
        id=case_id,
        source=source,
        category=category,
        guard_status=outcome.guard.result.status,
        guard_correct=(
            None if expected_guard is None else outcome.guard.result.status is expected_guard
        ),
        parse_succeeded=outcome.guard.parse_succeeded,
        table_scope_compliant=outcome.guard.table_scope_compliant,
        referenced_tables=tuple(str(table) for table in outcome.guard.result.referenced_tables),
        unused_declared_tables=outcome.guard.unused_declared_tables,
        guard_violations=tuple(str(value) for value in outcome.guard.result.violations),
        explain_accepted=explain_accepted,
        explain_correct=(
            None if expected_explain is None else explain_accepted is expected_explain
        ),
        explain_rejection_reason=(
            None if outcome.explain_result is None else outcome.explain_result.rejection_reason
        ),
        guarded_query_issued=outcome.guarded_query is not None,
    )


def run_sql_guard_evaluation(
    admission: SQLAdmissionService,
    *,
    suite: SQLGuardEvalSuite,
    snapshot: M9ProposalSnapshot,
    snapshot_fingerprint: str,
    analytics_schema: str,
    max_sql_characters: int,
    max_explain_estimated_rows: int,
    max_explain_characters: int,
    max_explain_nodes: int,
    sql_guard_policy_version: str,
    explain_policy_version: str,
) -> SQLGuardEvalReport:
    security_results: list[SQLAdmissionCaseResult] = []
    for case in suite.cases:
        outcome = admission.admit(
            QueryPlan(
                version="v0.1",
                intent=f"M10 security evaluation: {case.id}",
                tables=list(case.tables),
                assumptions=[],
                sql=case.sql,
                expected_columns=[],
                explanation="Frozen M10 security corpus",
            )
        )
        security_results.append(
            _case_result(
                case_id=case.id,
                source="security",
                category=case.category,
                outcome=outcome,
                expected_guard=case.expected_guard,
                expected_explain=case.expected_explain == "ACCEPTED"
                if case.expected_explain is not None
                else None,
            )
        )

    proposal_results = [
        _case_result(
            case_id=case.id,
            source="accepted_m9_proposal",
            category="m9_proposal",
            outcome=admission.admit(case.plan),
        )
        for case in snapshot.cases
    ]
    security_count = len(security_results)
    explain_expectations = [
        result for result in security_results if result.explain_correct is not None
    ]
    proposal_count = len(proposal_results)
    metrics = SQLGuardEvalMetrics(
        security_case_count=security_count,
        security_guard_accuracy=(
            sum(result.guard_correct is True for result in security_results) / security_count
        ),
        security_explain_accuracy=(
            sum(result.explain_correct is True for result in explain_expectations)
            / len(explain_expectations)
        ),
        proposal_case_count=proposal_count,
        proposal_sql_parse_rate=(
            sum(result.parse_succeeded for result in proposal_results) / proposal_count
        ),
        proposal_guard_pass_rate=(
            sum(result.guard_status is GuardStatus.PASSED for result in proposal_results)
            / proposal_count
        ),
        proposal_table_scope_compliance=(
            sum(result.table_scope_compliant is True for result in proposal_results)
            / proposal_count
        ),
        proposal_explain_admission_rate=(
            sum(result.explain_accepted is True for result in proposal_results) / proposal_count
        ),
        proposal_unused_declared_table_rate=(
            sum(bool(result.unused_declared_tables) for result in proposal_results) / proposal_count
        ),
    )
    identity = snapshot.source.identity
    report = SQLGuardEvalReport(
        identity=SQLGuardEvalIdentity(
            suite_version=suite.version,
            sqlglot_version=version("sqlglot"),
            sql_guard_policy_version=sql_guard_policy_version,
            explain_policy_version=explain_policy_version,
            analytics_schema=analytics_schema,
            max_sql_characters=max_sql_characters,
            max_explain_estimated_rows=max_explain_estimated_rows,
            max_explain_characters=max_explain_characters,
            max_explain_nodes=max_explain_nodes,
            m9_snapshot_version=snapshot.version,
            m9_snapshot_fingerprint=snapshot_fingerprint,
            m9_accepted_head=snapshot.source.accepted_head,
            m9_squash_merged_main=snapshot.source.squash_merged_main,
            m9_prompt_version=identity.prompt_version,
            m9_model_fingerprint=identity.model_fingerprint,
        ),
        metrics=metrics,
        cases=tuple([*security_results, *proposal_results]),
        passed=(
            metrics.security_guard_accuracy == 1.0
            and metrics.security_explain_accuracy == 1.0
            and metrics.proposal_sql_parse_rate >= 0.98
            and metrics.proposal_guard_pass_rate == 1.0
            and metrics.proposal_table_scope_compliance == 1.0
        ),
    )
    return report


def write_sql_guard_eval_report(
    report: SQLGuardEvalReport,
    *,
    output_path: Path = SQL_GUARD_REPORT_PATH,
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


def format_sql_guard_eval_summary(report: SQLGuardEvalReport) -> str:
    metrics = report.metrics
    status = "PASS" if report.passed else "FAIL"
    return (
        f"SQL guard eval {status}: security_cases={metrics.security_case_count}, "
        f"security_guard={metrics.security_guard_accuracy:.3f}, "
        f"security_explain={metrics.security_explain_accuracy:.3f}, "
        f"m9_cases={metrics.proposal_case_count}, "
        f"parse={metrics.proposal_sql_parse_rate:.3f}, "
        f"guard={metrics.proposal_guard_pass_rate:.3f}, "
        f"table_scope={metrics.proposal_table_scope_compliance:.3f}, "
        f"explain={metrics.proposal_explain_admission_rate:.3f}, "
        f"unused_declared={metrics.proposal_unused_declared_table_rate:.3f}"
    )
