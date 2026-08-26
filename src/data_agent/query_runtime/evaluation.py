"""Standalone deterministic M11 evaluation over M10-issued capabilities."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from importlib.metadata import version
from pathlib import Path
from typing import Any, Literal, Self, cast

import pymysql
import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from data_agent.config import Settings
from data_agent.contracts.query import QueryPlan
from data_agent.query_runtime.errors import CapabilityIntegrityError, QueryTimeoutError
from data_agent.query_runtime.evidence import ExecutionMetadata
from data_agent.query_runtime.mysql import MySQLQueryConnectionFactory
from data_agent.query_runtime.service import (
    QUERY_RUNTIME_POLICY_VERSION,
    ReadOnlyQueryRuntime,
    RuntimeLimits,
)
from data_agent.sql_guard.capability import GuardedQuery
from data_agent.sql_guard.explain import EXPLAIN_POLICY_VERSION, ExplainPolicy, MySQLExplainProvider
from data_agent.sql_guard.guard import SQL_GUARD_POLICY_VERSION, SQLGuard
from data_agent.sql_guard.service import SQLAdmissionService

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_EVAL_PATH = REPOSITORY_ROOT / "evals" / "runtime.yaml"
RUNTIME_REPORT_PATH = REPOSITORY_ROOT / "evals" / "reports" / "runtime-latest.json"
_STANDALONE_EVAL_CONTEXT_FINGERPRINT = hashlib.sha256(
    b"m11-standalone-eval-context-v0.1"
).hexdigest()


class RuntimeEvaluationError(RuntimeError):
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


class RuntimeEvalCase(_EvaluationModel):
    id: str = Field(min_length=1, pattern=r"\S")
    category: Literal["success", "row_bound", "byte_bound", "timeout"]
    sql: str = Field(min_length=1)
    tables: tuple[str, ...] = Field(min_length=1)
    max_execution_time_ms: int = Field(default=5_000, gt=0)
    max_result_rows: int = Field(default=1_000, gt=0)
    max_result_bytes: int = Field(default=8_388_608, gt=0)
    expected_columns: tuple[str, ...] = Field(min_length=1)
    expected_returned_rows: int = Field(ge=0)
    expected_truncated: bool
    expected_decimal: str | None = None

    @model_validator(mode="after")
    def expectation_is_consistent(self) -> Self:
        if len(self.tables) != len(set(self.tables)):
            raise ValueError("runtime eval tables must be unique")
        if self.category == "timeout" and self.expected_returned_rows != 0:
            raise ValueError("timeout case cannot expect returned rows")
        return self


class RuntimeEvalSuite(_EvaluationModel):
    version: Literal["v0.1"]
    cases: tuple[RuntimeEvalCase, ...] = Field(min_length=5)

    @model_validator(mode="after")
    def case_ids_and_categories_are_complete(self) -> Self:
        ids = [case.id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("runtime eval case ids must be unique")
        required = {"success", "row_bound", "byte_bound", "timeout"}
        if {case.category for case in self.cases} != required:
            raise ValueError("runtime eval suite must cover every M11 category")
        return self


class RuntimeEvalCaseResult(_EvaluationModel):
    id: str
    category: str
    capability_issued: bool
    executed: bool
    error_code: str | None
    columns: tuple[str, ...]
    returned_row_count: int
    duration_ms: int
    truncated: bool
    result_shape_correct: bool
    numeric_fidelity_correct: bool | None
    execution_attempt_count: int
    passed: bool


class RuntimeEvalMetrics(_EvaluationModel):
    case_count: int = Field(ge=5)
    execution_success_rate: float = Field(ge=0, le=1)
    timeout_enforcement: float = Field(ge=0, le=1)
    row_bound_enforcement: float = Field(ge=0, le=1)
    byte_bound_enforcement: float = Field(ge=0, le=1)
    result_shape_fidelity: float = Field(ge=0, le=1)
    numeric_fidelity: float = Field(ge=0, le=1)
    capability_only_admission: float = Field(ge=0, le=1)
    readonly_enforcement: float = Field(ge=0, le=1)
    no_hidden_retry: float = Field(ge=0, le=1)


class RuntimeEvalIdentity(_EvaluationModel):
    suite_version: str
    suite_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_policy_version: str
    sql_guard_policy_version: str
    explain_policy_version: str
    pymysql_version: str
    mysql_version: str
    analytics_schema: str
    database_principal_class: str
    default_max_execution_time_ms: int
    client_read_timeout_seconds: int
    default_max_result_rows: int
    default_max_result_bytes: int


class RuntimeEvalReport(_EvaluationModel):
    version: Literal["v0.1"] = "v0.1"
    identity: RuntimeEvalIdentity
    metrics: RuntimeEvalMetrics
    cases: tuple[RuntimeEvalCaseResult, ...]
    passed: bool
    epistemic_boundary: Literal[
        "execution-and-database-values-only; no semantic-answer-correctness claim"
    ] = "execution-and-database-values-only; no semantic-answer-correctness claim"


class _RecordingSink:
    def __init__(self) -> None:
        self.records: list[ExecutionMetadata] = []

    def record(self, metadata: ExecutionMetadata) -> None:
        self.records.append(metadata)


def load_runtime_eval_suite(path: Path = RUNTIME_EVAL_PATH) -> tuple[RuntimeEvalSuite, str]:
    try:
        payload = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeySafeLoader)
        suite = RuntimeEvalSuite.model_validate(payload)
    except (OSError, TypeError, yaml.YAMLError, ValidationError) as error:
        raise RuntimeEvaluationError("runtime evaluation suite is missing or invalid") from error
    canonical = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return suite, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _admission(settings: Settings) -> SQLAdmissionService:
    return SQLAdmissionService(
        guard=SQLGuard(
            analytics_schema=settings.mysql_database,
            max_sql_characters=settings.max_sql_characters,
        ),
        explain_provider=MySQLExplainProvider(settings),
        explain_policy=ExplainPolicy(
            max_estimated_rows_per_access=settings.max_explain_estimated_rows
        ),
    )


def _issue_case_capability(
    admission: SQLAdmissionService,
    case: RuntimeEvalCase,
) -> GuardedQuery:
    outcome = admission.admit(
        QueryPlan(
            version="v0.1",
            intent=f"M11 runtime evaluation: {case.id}",
            tables=list(case.tables),
            assumptions=[],
            sql=case.sql,
            expected_columns=[],
            explanation="Frozen M11 deterministic runtime case",
        ),
        planner_context_fingerprint=_STANDALONE_EVAL_CONTEXT_FINGERPRINT,
    )
    if outcome.guarded_query is None:
        raise RuntimeEvaluationError(f"M10 did not issue capability for M11 case: {case.id}")
    return outcome.guarded_query


def _evaluate_case(
    settings: Settings,
    admission: SQLAdmissionService,
    case: RuntimeEvalCase,
) -> RuntimeEvalCaseResult:
    capability = _issue_case_capability(admission, case)
    sink = _RecordingSink()
    runtime = ReadOnlyQueryRuntime(
        connection_factory=MySQLQueryConnectionFactory(settings),
        limits=RuntimeLimits(
            max_execution_time_ms=case.max_execution_time_ms,
            max_result_rows=case.max_result_rows,
            max_result_bytes=case.max_result_bytes,
        ),
        metadata_sink=sink,
    )
    if case.category == "timeout":
        try:
            runtime.execute(capability)
        except QueryTimeoutError:
            metadata = sink.records[0]
            passed = metadata.execution_attempt_count == 1
            return RuntimeEvalCaseResult(
                id=case.id,
                category=case.category,
                capability_issued=True,
                executed=False,
                error_code=metadata.error_code,
                columns=(),
                returned_row_count=0,
                duration_ms=metadata.duration_ms,
                truncated=False,
                result_shape_correct=True,
                numeric_fidelity_correct=None,
                execution_attempt_count=metadata.execution_attempt_count,
                passed=passed,
            )
        raise RuntimeEvaluationError(f"timeout case unexpectedly succeeded: {case.id}")

    result = runtime.execute(capability)
    metadata = sink.records[0]
    shape_correct = (
        tuple(result.columns) == case.expected_columns
        and result.returned_row_count == case.expected_returned_rows
        and result.truncated is case.expected_truncated
    )
    numeric_correct: bool | None = None
    if case.expected_decimal is not None:
        value = result.rows[0][0] if result.rows and result.rows[0] else None
        numeric_correct = isinstance(value, Decimal) and str(value) == case.expected_decimal
    return RuntimeEvalCaseResult(
        id=case.id,
        category=case.category,
        capability_issued=True,
        executed=True,
        error_code=None,
        columns=tuple(str(column) for column in result.columns),
        returned_row_count=result.returned_row_count,
        duration_ms=result.duration_ms,
        truncated=result.truncated,
        result_shape_correct=shape_correct,
        numeric_fidelity_correct=numeric_correct,
        execution_attempt_count=metadata.execution_attempt_count,
        passed=shape_correct and numeric_correct is not False,
    )


def _capability_only_probe(settings: Settings) -> bool:
    runtime = ReadOnlyQueryRuntime(
        connection_factory=MySQLQueryConnectionFactory(settings),
        limits=RuntimeLimits(
            max_execution_time_ms=settings.max_query_time_ms,
            max_result_rows=settings.max_result_rows,
            max_result_bytes=settings.max_result_bytes,
        ),
    )
    try:
        runtime.execute(cast(GuardedQuery, "SELECT 1"))
    except CapabilityIntegrityError:
        return True
    return False


def _readonly_principal_probe(settings: Settings) -> tuple[bool, str]:
    factory = MySQLQueryConnectionFactory(settings)
    version_connection = factory.connect()
    try:
        with version_connection.cursor() as cursor:
            cursor.execute("SELECT VERSION()")
            row = cursor.fetchone()
    finally:
        version_connection.close()
    if row is None or len(row) != 1 or not isinstance(row[0], str):
        raise RuntimeEvaluationError("MySQL version probe returned an invalid shape")
    mysql_version = row[0]

    statements = (
        "UPDATE dim_region SET province = province WHERE id = 1",
        "DELETE FROM dim_region WHERE id = -1",
        "CREATE TABLE runtime_eval_write_probe (id INT)",
        f"SELECT COUNT(*) FROM `{settings.mysql_control_database}`.`agent_session`",
    )
    denied = 0
    for statement in statements:
        connection = factory.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(statement)
        except pymysql.MySQLError as error:
            if error.args and error.args[0] in {1044, 1142}:
                denied += 1
        finally:
            connection.close()
    return denied == len(statements), mysql_version


def run_runtime_evaluation(
    settings: Settings,
    *,
    suite: RuntimeEvalSuite,
    suite_fingerprint: str,
) -> RuntimeEvalReport:
    admission = _admission(settings)
    results = tuple(_evaluate_case(settings, admission, case) for case in suite.cases)
    non_timeout = [result for result in results if result.category != "timeout"]
    timeout = [result for result in results if result.category == "timeout"]
    row_bound = [result for result in results if result.category == "row_bound"]
    byte_bound = [result for result in results if result.category == "byte_bound"]
    numeric = [result for result in results if result.numeric_fidelity_correct is not None]
    readonly, mysql_version = _readonly_principal_probe(settings)
    capability_only = _capability_only_probe(settings)
    metrics = RuntimeEvalMetrics(
        case_count=len(results),
        execution_success_rate=sum(result.executed for result in non_timeout) / len(non_timeout),
        timeout_enforcement=sum(result.error_code == "QUERY_TIMEOUT" for result in timeout)
        / len(timeout),
        row_bound_enforcement=sum(result.passed for result in row_bound) / len(row_bound),
        byte_bound_enforcement=sum(result.passed for result in byte_bound) / len(byte_bound),
        result_shape_fidelity=sum(result.result_shape_correct for result in non_timeout)
        / len(non_timeout),
        numeric_fidelity=sum(result.numeric_fidelity_correct is True for result in numeric)
        / len(numeric),
        capability_only_admission=float(capability_only),
        readonly_enforcement=float(readonly),
        no_hidden_retry=sum(result.execution_attempt_count == 1 for result in results)
        / len(results),
    )
    factory = MySQLQueryConnectionFactory(settings)
    report = RuntimeEvalReport(
        identity=RuntimeEvalIdentity(
            suite_version=suite.version,
            suite_fingerprint=suite_fingerprint,
            runtime_policy_version=QUERY_RUNTIME_POLICY_VERSION,
            sql_guard_policy_version=SQL_GUARD_POLICY_VERSION,
            explain_policy_version=EXPLAIN_POLICY_VERSION,
            pymysql_version=version("pymysql"),
            mysql_version=mysql_version,
            analytics_schema=settings.mysql_database,
            database_principal_class=factory.principal_class,
            default_max_execution_time_ms=settings.max_query_time_ms,
            client_read_timeout_seconds=settings.mysql_query_read_timeout_seconds,
            default_max_result_rows=settings.max_result_rows,
            default_max_result_bytes=settings.max_result_bytes,
        ),
        metrics=metrics,
        cases=results,
        passed=all(result.passed for result in results)
        and all(
            value == 1.0 for value in metrics.model_dump().values() if isinstance(value, float)
        ),
    )
    return report


def write_runtime_eval_report(
    report: RuntimeEvalReport,
    *,
    output_path: Path = RUNTIME_REPORT_PATH,
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


def format_runtime_eval_summary(report: RuntimeEvalReport) -> str:
    metrics = report.metrics
    status = "PASS" if report.passed else "FAIL"
    return (
        f"Runtime eval {status}: cases={metrics.case_count}, "
        f"execution={metrics.execution_success_rate:.3f}, "
        f"timeout={metrics.timeout_enforcement:.3f}, "
        f"row_bound={metrics.row_bound_enforcement:.3f}, "
        f"byte_bound={metrics.byte_bound_enforcement:.3f}, "
        f"shape={metrics.result_shape_fidelity:.3f}, "
        f"numeric={metrics.numeric_fidelity:.3f}, "
        f"capability_only={metrics.capability_only_admission:.3f}, "
        f"readonly={metrics.readonly_enforcement:.3f}, "
        f"no_retry={metrics.no_hidden_retry:.3f}"
    )
