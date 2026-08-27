"""Standalone deterministic M12 evaluation over constructed coherent evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, Self

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from data_agent.catalog.semantic import AssembledSemanticCatalog, load_assembled_catalog
from data_agent.contracts.catalog import CatalogDocument, Relationship
from data_agent.contracts.execution import ExecutionResult
from data_agent.contracts.query import ExpectedColumn, QueryPlan
from data_agent.contracts.requirement import (
    DimensionRequirement,
    MetricRequirement,
    RequirementState,
    RequirementStatus,
    ResolutionStatus,
    TimeRange,
)
from data_agent.planning.context import (
    PLANNER_CONTEXT_FINGERPRINT_VERSION,
    PlannerCatalogIdentity,
    PlannerContext,
    planner_context_fingerprint,
)
from data_agent.planning.prompt import PLANNER_PROMPT_VERSION
from data_agent.planning.service import PlanningTrace
from data_agent.query_runtime.evidence import (
    EXECUTION_METADATA_VERSION,
    RESULT_BYTE_ACCOUNTING_VERSION,
    RESULT_FINGERPRINT_VERSION,
    ExecutionMetadata,
    ExecutionOutcome,
    execution_result_fingerprint,
)
from data_agent.sql_guard.capability import GuardedQuery, GuardedSQL
from data_agent.sql_guard.explain import EXPLAIN_POLICY_VERSION, ExplainPolicy
from data_agent.sql_guard.guard import SQL_GUARD_POLICY_VERSION, SQLGuard
from data_agent.sql_guard.service import SQLAdmissionService
from data_agent.verification.context import build_verification_context
from data_agent.verification.errors import VerificationIntegrityError
from data_agent.verification.evidence import (
    VERIFICATION_POLICY_VERSION,
    CoverageDisposition,
    VerificationTrace,
)
from data_agent.verification.service import DeterministicVerifier

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
VERIFICATION_EVAL_PATH = REPOSITORY_ROOT / "evals" / "verification.yaml"
VERIFICATION_REPORT_PATH = REPOSITORY_ROOT / "evals" / "reports" / "verification-latest.json"

type VerificationMutation = Literal[
    "VALID",
    "COLUMN_MISMATCH",
    "TRUNCATED",
    "MISSING_METRIC",
    "MISSING_DIMENSION",
    "MISSING_PERIOD",
    "WRONG_METRIC_SOURCE",
    "INVALID_JOIN",
    "NEGATIVE_COUNT",
    "DUPLICATE_GROUP_KEYS",
    "PLAN_IDENTITY_MISMATCH",
    "RELATIONSHIP_CONTEXT_MISMATCH",
    "DOCUMENT_CONTEXT_MISMATCH",
    "CAPABILITY_METADATA_MISMATCH",
    "RESULT_FINGERPRINT_MISMATCH",
    "FROZEN_SIMPLE_GMV",
    "FROZEN_SIMPLE_PAID_AMOUNT",
    "FROZEN_SIMPLE_PAYMENT_ATTEMPTS",
    "FROZEN_JOIN_NET_REVENUE",
    "FROZEN_AGG_GMV_CHANNEL",
    "FROZEN_AGG_ORDERS_CHANNEL",
]
type ExpectedVerificationDecision = Literal[
    "PASS",
    "STRUCTURAL_FAILURE",
    "SEMANTIC_FAILURE",
    "EMPIRICAL_FAILURE",
    "INTEGRITY_ERROR",
]

_VALID_SQL = (
    "SELECT DATE(o.paid_at) AS period, r.province AS province, "
    "SUM(o.paid_amount) AS paid_amount FROM fact_order AS o "
    "JOIN dim_user AS u ON o.user_id = u.id "
    "JOIN dim_region AS r ON u.region_id = r.id "
    "WHERE o.paid_at >= DATE_SUB(CURRENT_DATE, INTERVAL 30 DAY) "
    "GROUP BY DATE(o.paid_at), r.province"
)


class VerificationEvaluationError(RuntimeError):
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


class VerificationEvalCase(_EvaluationModel):
    id: str = Field(min_length=1, pattern=r"\S")
    mutation: VerificationMutation
    expected: ExpectedVerificationDecision
    verified_oracle_regression: bool = False


class VerificationEvalSuite(_EvaluationModel):
    version: Literal["v0.2"]
    cases: tuple[VerificationEvalCase, ...] = Field(min_length=12)

    @model_validator(mode="after")
    def cases_cover_m12_boundaries(self) -> Self:
        ids = [case.id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("verification eval case ids must be unique")
        required: set[ExpectedVerificationDecision] = {
            "PASS",
            "STRUCTURAL_FAILURE",
            "SEMANTIC_FAILURE",
            "EMPIRICAL_FAILURE",
            "INTEGRITY_ERROR",
        }
        if {case.expected for case in self.cases} != required:
            raise ValueError("verification eval must cover every decision class")
        frozen_oracle_regressions = {
            "simple-gmv",
            "simple-paid-amount",
            "simple-payment-attempts",
            "join-net-revenue",
            "agg-gmv-channel",
            "agg-orders-channel",
        }
        actual_oracle_regressions = {
            case.id for case in self.cases if case.verified_oracle_regression
        }
        if actual_oracle_regressions != frozen_oracle_regressions:
            raise ValueError("verification eval must preserve the six frozen Oracle regressions")
        if any(
            case.expected != "SEMANTIC_FAILURE"
            for case in self.cases
            if case.verified_oracle_regression
        ):
            raise ValueError("frozen Oracle regressions must expect semantic failure")
        return self


class VerificationEvalCaseResult(_EvaluationModel):
    id: str
    mutation: str
    expected: ExpectedVerificationDecision
    actual: ExpectedVerificationDecision
    failed_categories: tuple[str, ...]
    applied_check_count: int = Field(ge=0)
    not_applicable_gap_count: int = Field(ge=0)
    unsupported_gap_count: int = Field(ge=0)
    verified_oracle_regression: bool
    passed: bool


class VerificationEvalMetrics(_EvaluationModel):
    case_count: int = Field(ge=12)
    structural_decision_accuracy: float = Field(ge=0, le=1)
    semantic_decision_accuracy: float = Field(ge=0, le=1)
    empirical_decision_accuracy: float = Field(ge=0, le=1)
    false_accept_rate: float = Field(ge=0, le=1)
    false_reject_rate: float = Field(ge=0, le=1)
    identity_mismatch_rejection: float = Field(ge=0, le=1)
    planner_context_substitution_rejection: float = Field(ge=0, le=1)
    truncation_rejection: float = Field(ge=0, le=1)
    verified_oracle_mismatch_count: int = Field(ge=0)
    verification_coverage: float = Field(ge=0, le=1)


class VerificationEvalIdentity(_EvaluationModel):
    suite_version: str
    suite_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    verification_policy_version: str
    execution_metadata_version: str
    result_fingerprint_version: str
    planner_context_fingerprint_version: str
    sql_guard_policy_version: str
    explain_policy_version: str
    catalog_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    generated_schema_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_revision: str = Field(pattern=r"^[0-9a-f]{64}$")


class VerificationEvalReport(_EvaluationModel):
    version: Literal["v0.1"] = "v0.1"
    identity: VerificationEvalIdentity
    metrics: VerificationEvalMetrics
    cases: tuple[VerificationEvalCaseResult, ...]
    passed: bool
    epistemic_boundary: Literal[
        "encoded-applicable-invariants-only; no global business-correctness claim"
    ] = "encoded-applicable-invariants-only; no global business-correctness claim"


class _StaticExplainProvider:
    def explain(self, candidate: GuardedSQL) -> str:
        table = candidate.physical_tables[0].name
        return json.dumps(
            {
                "query_block": {
                    "table": {
                        "table_name": table,
                        "access_type": "ALL",
                        "rows_examined_per_scan": 10,
                    }
                }
            }
        )


@dataclass(frozen=True)
class _EvidenceBundle:
    planning_trace: PlanningTrace
    guarded_query: GuardedQuery
    execution_metadata: ExecutionMetadata
    execution_result: ExecutionResult


ConstructedVerificationEvidence = _EvidenceBundle


def load_verification_eval_suite(
    path: Path = VERIFICATION_EVAL_PATH,
) -> tuple[VerificationEvalSuite, str]:
    try:
        payload = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeySafeLoader)
        suite = VerificationEvalSuite.model_validate(payload)
    except (OSError, TypeError, yaml.YAMLError, ValidationError) as error:
        raise VerificationEvaluationError(
            "verification evaluation suite is missing or invalid"
        ) from error
    canonical = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return suite, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _requirement(
    *,
    metric: str | None = "paid_amount",
    dimension: str | None = "province",
    grain: str | None = "day",
    include_time: bool = True,
) -> RequirementState:
    metrics = []
    if metric is not None:
        metrics.append(
            MetricRequirement(
                term=metric.replace("_", " "),
                resolved_name=metric,
                status=ResolutionStatus.CONFIRMED,
            )
        )
    dimensions = []
    if dimension is not None:
        dimensions.append(
            DimensionRequirement(
                term=dimension,
                resolved_name=dimension,
                status=ResolutionStatus.CONFIRMED,
            )
        )
    return RequirementState(
        version="v0.1",
        goal="Constructed deterministic M12 evaluation requirement",
        metrics=metrics,
        dimensions=dimensions,
        time_range=TimeRange(kind="RELATIVE", value="last_30_days") if include_time else None,
        grain=grain,
        status=RequirementStatus.READY,
    )


def _plan(
    *,
    sql: str = _VALID_SQL,
    tables: tuple[str, ...] = ("fact_order", "dim_user", "dim_region"),
    columns: tuple[str, ...] = ("period", "province", "paid_amount"),
) -> QueryPlan:
    return QueryPlan(
        version="v0.1",
        intent="Constructed deterministic M12 evaluation plan",
        tables=list(tables),
        assumptions=[],
        sql=sql,
        expected_columns=[ExpectedColumn(name=name) for name in columns],
        explanation="Frozen constructed verification evidence",
    )


def _result(
    *,
    columns: tuple[str, ...] = ("period", "province", "paid_amount"),
    rows: list[list[object]] | None = None,
    truncated: bool = False,
) -> ExecutionResult:
    actual_rows = rows
    if actual_rows is None:
        actual_rows = [
            [date(2026, 8, 1), "广东", Decimal("100.00")],
            [date(2026, 8, 2), "广东", Decimal("80.00")],
        ]
    return ExecutionResult(
        version="v0.1",
        columns=list(columns),
        rows=actual_rows,
        returned_row_count=len(actual_rows),
        duration_ms=1,
        truncated=truncated,
    )


def _frozen_requirement(
    *,
    metric_term: str,
    metric: str,
    dimension_term: str | None = None,
    dimension: str | None = None,
    include_all_time: bool = False,
) -> RequirementState:
    return RequirementState(
        version="v0.1",
        metrics=[
            MetricRequirement(
                term=metric_term,
                resolved_name=metric,
                status=ResolutionStatus.CONFIRMED,
            )
        ],
        dimensions=(
            [
                DimensionRequirement(
                    term=dimension_term,
                    resolved_name=dimension,
                    status=ResolutionStatus.CONFIRMED,
                )
            ]
            if dimension_term is not None and dimension is not None
            else []
        ),
        time_range=TimeRange(kind="RELATIVE", value="all") if include_all_time else None,
        status=RequirementStatus.READY,
    )


def _frozen_plan(
    *,
    intent: str,
    tables: tuple[str, ...],
    sql: str,
    columns: tuple[tuple[str, str], ...],
) -> QueryPlan:
    return QueryPlan(
        version="v0.1",
        intent=intent,
        tables=list(tables),
        assumptions=[],
        sql=sql,
        expected_columns=[
            ExpectedColumn(name=name, semantic_role=semantic_role)
            for name, semantic_role in columns
        ],
        explanation="Frozen M15 false-acceptance replay",
    )


def _catalog_slice(
    catalog: AssembledSemanticCatalog,
    tables: tuple[str, ...],
) -> tuple[tuple[CatalogDocument, ...], tuple[Relationship, ...]]:
    by_table = {str(document.table): document for document in catalog.documents}
    try:
        documents = tuple(by_table[table] for table in tables)
    except KeyError as error:
        raise VerificationEvaluationError("M12 eval table is absent from M6 catalog") from error
    selected = set(tables)
    relationships = tuple(
        relationship
        for relationship in catalog.relationships
        if str(relationship.from_table) in selected and str(relationship.to_table) in selected
    )
    return documents, relationships


def _admit(plan: QueryPlan, *, context_fingerprint: str) -> GuardedQuery:
    outcome = SQLAdmissionService(
        guard=SQLGuard(analytics_schema="data_agent"),
        explain_provider=_StaticExplainProvider(),
        explain_policy=ExplainPolicy(max_estimated_rows_per_access=100),
    ).admit(plan, planner_context_fingerprint=context_fingerprint)
    if outcome.guarded_query is None:
        raise VerificationEvaluationError("constructed M12 eval plan failed M10 admission")
    return outcome.guarded_query


def _bundle(
    catalog: AssembledSemanticCatalog,
    *,
    requirement: RequirementState,
    plan: QueryPlan,
    result: ExecutionResult,
) -> _EvidenceBundle:
    table_order = tuple(str(table) for table in plan.tables)
    documents, relationships = _catalog_slice(catalog, table_order)
    context = PlannerContext(
        requirement=requirement,
        allowed_tables=table_order,
        documents=documents,
        relationships=relationships,
        identity=PlannerCatalogIdentity(
            catalog_fingerprint=catalog.catalog_fingerprint,
            generated_schema_fingerprint=catalog.generated_metadata_fingerprint,
            semantic_revision=catalog.semantic_revision,
            retrieval_index_fingerprint="0" * 64,
        ),
    )
    trace = PlanningTrace(
        context=context,
        planner_context_fingerprint=planner_context_fingerprint(context),
        plan=plan,
        prompt_version=PLANNER_PROMPT_VERSION,
        model_fingerprint=None,
        runtime_version=None,
        retrieval_index_fingerprint=context.identity.retrieval_index_fingerprint,
        allowed_tables=table_order,
    )
    guarded_query = _admit(
        plan,
        context_fingerprint=trace.planner_context_fingerprint,
    )
    timestamp = datetime(2026, 8, 26, tzinfo=UTC)
    metadata = ExecutionMetadata(
        version=EXECUTION_METADATA_VERSION,
        execution_id="m12-eval-execution",
        guarded_query_fingerprint=guarded_query.capability_fingerprint,
        sql_digest=guarded_query.sql_digest,
        query_plan_fingerprint=guarded_query.query_plan_fingerprint,
        planner_context_fingerprint=guarded_query.planner_context_fingerprint,
        execution_namespace=guarded_query.execution_namespace,
        guard_policy_version=guarded_query.guard_policy_version,
        explain_policy_version=guarded_query.explain_policy_version,
        physical_tables=tuple(table.qualified_name for table in guarded_query.physical_tables),
        database_schema=guarded_query.execution_namespace,
        database_principal_class="ANALYTICS_READONLY",
        max_execution_time_ms=5_000,
        client_read_timeout_seconds=10,
        max_result_rows=1_000,
        max_result_bytes=8_388_608,
        result_byte_accounting_version=RESULT_BYTE_ACCOUNTING_VERSION,
        result_fingerprint_version=RESULT_FINGERPRINT_VERSION,
        result_fingerprint=execution_result_fingerprint(result),
        started_at=timestamp,
        completed_at=timestamp,
        duration_ms=result.duration_ms,
        execution_attempt_count=1,
        returned_row_count=result.returned_row_count,
        returned_result_bytes=100,
        truncated=result.truncated,
        outcome=ExecutionOutcome.SUCCEEDED,
    )
    return _EvidenceBundle(
        planning_trace=trace,
        guarded_query=guarded_query,
        execution_metadata=metadata,
        execution_result=result,
    )


def build_constructed_verification_evidence(
    catalog: AssembledSemanticCatalog,
    *,
    requirement: RequirementState | None = None,
    plan: QueryPlan | None = None,
    result: ExecutionResult | None = None,
) -> ConstructedVerificationEvidence:
    """Public provider-free coherent evidence fixture shared by later eval layers."""

    return _bundle(
        catalog,
        requirement=requirement or _requirement(),
        plan=plan or _plan(),
        result=result or _result(),
    )


def _case_bundle(
    catalog: AssembledSemanticCatalog,
    mutation: VerificationMutation,
) -> _EvidenceBundle:
    if mutation == "FROZEN_SIMPLE_GMV":
        return _bundle(
            catalog,
            requirement=_frozen_requirement(
                metric_term="下单总金额 GMV",
                metric="gmv",
                include_all_time=True,
            ),
            plan=_frozen_plan(
                intent="Calculate total GMV by channel.",
                tables=("fact_order", "dim_channel"),
                sql=(
                    "SELECT d.code AS channel_code, d.name AS channel_name, "
                    "SUM(o.total_amount) AS gmv FROM fact_order AS o "
                    "JOIN dim_channel AS d ON o.channel_id = d.id "
                    "GROUP BY d.code, d.name ORDER BY gmv DESC"
                ),
                columns=(
                    ("channel_code", "dimension"),
                    ("channel_name", "dimension"),
                    ("gmv", "metric"),
                ),
            ),
            result=_result(
                columns=("channel_code", "channel_name", "gmv"),
                rows=[["social", "社交媒体", Decimal("860.00")]],
            ),
        )
    if mutation == "FROZEN_SIMPLE_PAID_AMOUNT":
        return _bundle(
            catalog,
            requirement=_frozen_requirement(
                metric_term="实际支付金额",
                metric="paid_amount",
                include_all_time=True,
            ),
            plan=_frozen_plan(
                intent="Calculate paid amount by day.",
                tables=("fact_order",),
                sql=(
                    "SELECT DATE(fact_order.paid_at) AS period, "
                    "SUM(fact_order.paid_amount) AS paid_amount FROM fact_order "
                    "WHERE fact_order.status IN ('PAID', 'COMPLETED') "
                    "AND fact_order.paid_at IS NOT NULL "
                    "GROUP BY DATE(fact_order.paid_at) ORDER BY period ASC"
                ),
                columns=(("period", "time bucket"), ("paid_amount", "metric")),
            ),
            result=_result(
                columns=("period", "paid_amount"),
                rows=[[date(2026, 8, 23), Decimal("90.00")]],
            ),
        )
    if mutation == "FROZEN_SIMPLE_PAYMENT_ATTEMPTS":
        return _bundle(
            catalog,
            requirement=_frozen_requirement(
                metric_term="支付尝试次数",
                metric="payment_attempt_count",
                include_all_time=True,
            ),
            plan=_frozen_plan(
                intent="Calculate payment attempts by day.",
                tables=("fact_payment_transaction",),
                sql=(
                    "SELECT DATE(fpt.attempted_at) AS period, "
                    "COUNT(*) AS payment_attempt_count "
                    "FROM fact_payment_transaction AS fpt "
                    "WHERE fpt.status = 'SUCCESS' "
                    "GROUP BY DATE(fpt.attempted_at) ORDER BY period ASC"
                ),
                columns=(
                    ("period", "time bucket"),
                    ("payment_attempt_count", "metric"),
                ),
            ),
            result=_result(
                columns=("period", "payment_attempt_count"),
                rows=[[date(2026, 8, 23), 1]],
            ),
        )
    if mutation == "FROZEN_JOIN_NET_REVENUE":
        return _bundle(
            catalog,
            requirement=_frozen_requirement(metric_term="净收入", metric="net_revenue"),
            plan=_frozen_plan(
                intent="Calculate net revenue by channel.",
                tables=("fact_order", "dim_channel", "fact_refund"),
                sql=(
                    "SELECT dc.code AS channel_code, dc.name AS channel_name, "
                    "SUM(COALESCE(fo.paid_amount, 0)) - "
                    "COALESCE(SUM(fr.refund_amount), 0) AS net_revenue "
                    "FROM fact_order AS fo "
                    "JOIN dim_channel AS dc ON fo.channel_id = dc.id "
                    "LEFT JOIN fact_refund AS fr "
                    "ON fo.id = fr.order_id AND fr.status = 'SUCCESS' "
                    "WHERE fo.status IN ('PAID', 'COMPLETED') "
                    "GROUP BY dc.code, dc.name ORDER BY net_revenue DESC"
                ),
                columns=(
                    ("channel_code", "dimension"),
                    ("channel_name", "dimension"),
                    ("net_revenue", "metric"),
                ),
            ),
            result=_result(
                columns=("channel_code", "channel_name", "net_revenue"),
                rows=[["organic", "自然流量", Decimal("740.00")]],
            ),
        )
    if mutation == "FROZEN_AGG_GMV_CHANNEL":
        return _bundle(
            catalog,
            requirement=_frozen_requirement(
                metric_term="gmv",
                metric="gmv",
                dimension_term="order_channel",
                dimension="channel",
            ),
            plan=_frozen_plan(
                intent="Calculate GMV by order channel.",
                tables=("fact_order", "dim_channel"),
                sql=(
                    "SELECT dc.name AS channel, SUM(fo.total_amount) AS gmv "
                    "FROM fact_order AS fo "
                    "JOIN dim_channel AS dc ON fo.channel_id = dc.id "
                    "WHERE fo.status IN ('PAID', 'COMPLETED') "
                    "GROUP BY dc.id, dc.name ORDER BY gmv DESC"
                ),
                columns=(("channel", "dimension"), ("gmv", "metric")),
            ),
            result=_result(
                columns=("channel", "gmv"),
                rows=[["社交媒体", Decimal("720.00")]],
            ),
        )
    if mutation == "FROZEN_AGG_ORDERS_CHANNEL":
        return _bundle(
            catalog,
            requirement=_frozen_requirement(
                metric_term="订单数",
                metric="order_count",
                dimension_term="订单归属渠道",
                dimension="channel",
            ),
            plan=_frozen_plan(
                intent="Calculate order count by order channel.",
                tables=("fact_order", "dim_channel"),
                sql=(
                    "SELECT dc.name AS channel, COUNT(fo.id) AS order_count "
                    "FROM fact_order AS fo "
                    "JOIN dim_channel AS dc ON fo.channel_id = dc.id "
                    "GROUP BY dc.id, dc.name ORDER BY order_count DESC"
                ),
                columns=(("channel", "dimension"), ("order_count", "metric")),
            ),
            result=_result(
                columns=("channel", "order_count"),
                rows=[["社交媒体", 4]],
            ),
        )
    if mutation == "MISSING_METRIC":
        return _bundle(
            catalog,
            requirement=_requirement(dimension=None, grain=None, include_time=False),
            plan=_plan(
                sql="SELECT id AS order_id FROM fact_order WHERE id = 1",
                tables=("fact_order",),
                columns=("order_id",),
            ),
            result=_result(columns=("order_id",), rows=[[1]]),
        )
    if mutation == "MISSING_DIMENSION":
        return _bundle(
            catalog,
            requirement=_requirement(metric=None, grain=None, include_time=False),
            plan=_plan(
                sql="SELECT id AS order_id FROM fact_order WHERE id = 1",
                tables=("fact_order",),
                columns=("order_id",),
            ),
            result=_result(columns=("order_id",), rows=[[1]]),
        )
    if mutation == "MISSING_PERIOD":
        return _bundle(
            catalog,
            requirement=_requirement(dimension=None),
            plan=_plan(
                sql="SELECT SUM(paid_amount) AS paid_amount FROM fact_order",
                tables=("fact_order",),
                columns=("paid_amount",),
            ),
            result=_result(columns=("paid_amount",), rows=[[Decimal("180.00")]]),
        )
    if mutation == "WRONG_METRIC_SOURCE":
        return _bundle(
            catalog,
            requirement=_requirement(),
            plan=_plan(sql=_VALID_SQL.replace("SUM(o.paid_amount)", "SUM(o.total_amount)")),
            result=_result(),
        )
    if mutation == "INVALID_JOIN":
        return _bundle(
            catalog,
            requirement=_requirement(),
            plan=_plan(sql=_VALID_SQL.replace("o.user_id = u.id", "o.id = u.id")),
            result=_result(),
        )
    if mutation == "NEGATIVE_COUNT":
        return _bundle(
            catalog,
            requirement=_requirement(
                metric="order_count", dimension=None, grain=None, include_time=False
            ),
            plan=_plan(
                sql="SELECT COUNT(*) AS order_count FROM fact_order",
                tables=("fact_order",),
                columns=("order_count",),
            ),
            result=_result(columns=("order_count",), rows=[[-1]]),
        )

    bundle = _bundle(
        catalog,
        requirement=_requirement(),
        plan=_plan(),
        result=(
            _result(
                rows=[
                    [date(2026, 8, 1), "广东", Decimal("100.00")],
                    [date(2026, 8, 1), "广东", Decimal("80.00")],
                ]
            )
            if mutation == "DUPLICATE_GROUP_KEYS"
            else _result(truncated=mutation == "TRUNCATED")
        ),
    )
    if mutation == "COLUMN_MISMATCH":
        return _bundle(
            catalog,
            requirement=_requirement(),
            plan=_plan(),
            result=_result(
                columns=("province", "period", "paid_amount"),
                rows=[
                    ["广东", date(2026, 8, 1), Decimal("100.00")],
                    ["广东", date(2026, 8, 2), Decimal("80.00")],
                ],
            ),
        )
    if mutation == "PLAN_IDENTITY_MISMATCH":
        changed_plan = bundle.planning_trace.plan.model_copy(update={"intent": "tampered plan"})
        return replace(
            bundle,
            planning_trace=replace(bundle.planning_trace, plan=changed_plan),
        )
    if mutation == "RELATIONSHIP_CONTEXT_MISMATCH":
        original = bundle.planning_trace.context
        changed_relationship = original.relationships[0].model_copy(update={"from_column": "id"})
        changed_context = original.model_copy(
            update={
                "relationships": (
                    changed_relationship,
                    *original.relationships[1:],
                )
            }
        )
        return replace(
            bundle,
            planning_trace=replace(bundle.planning_trace, context=changed_context),
        )
    if mutation == "DOCUMENT_CONTEXT_MISMATCH":
        original = bundle.planning_trace.context
        order_document = original.documents[0]
        changed_columns = [
            column.model_copy(update={"aliases": [*column.aliases, "tampered-alias"]})
            if str(column.name) == "paid_amount"
            else column
            for column in order_document.columns
        ]
        changed_document = order_document.model_copy(update={"columns": changed_columns})
        changed_context = original.model_copy(
            update={"documents": (changed_document, *original.documents[1:])}
        )
        return replace(
            bundle,
            planning_trace=replace(bundle.planning_trace, context=changed_context),
        )
    if mutation == "CAPABILITY_METADATA_MISMATCH":
        return replace(
            bundle,
            execution_metadata=replace(
                bundle.execution_metadata,
                guarded_query_fingerprint="f" * 64,
            ),
        )
    if mutation == "RESULT_FINGERPRINT_MISMATCH":
        different_result = _result(
            rows=[
                [date(2026, 8, 1), "广东", Decimal("999.00")],
                [date(2026, 8, 2), "广东", Decimal("80.00")],
            ]
        )
        return replace(bundle, execution_result=different_result)
    return bundle


def _actual_decision(trace: VerificationTrace) -> ExpectedVerificationDecision:
    failures = {check.category for check in trace.result.checks if not check.passed}
    if not failures:
        return "PASS"
    if "STRUCTURAL" in failures:
        return "STRUCTURAL_FAILURE"
    if "SEMANTIC" in failures:
        return "SEMANTIC_FAILURE"
    return "EMPIRICAL_FAILURE"


def _evaluate_case(
    catalog: AssembledSemanticCatalog,
    case: VerificationEvalCase,
) -> VerificationEvalCaseResult:
    bundle = _case_bundle(catalog, case.mutation)
    try:
        context = build_verification_context(
            planning_trace=bundle.planning_trace,
            guarded_query=bundle.guarded_query,
            execution_metadata=bundle.execution_metadata,
            execution_result=bundle.execution_result,
        )
        trace = DeterministicVerifier().verify(context)
    except VerificationIntegrityError:
        actual: ExpectedVerificationDecision = "INTEGRITY_ERROR"
        failed_categories: tuple[str, ...] = ()
        applied = 0
        not_applicable = 0
        unsupported = 0
    else:
        actual = _actual_decision(trace)
        failed_categories = tuple(
            sorted({check.category for check in trace.result.checks if not check.passed})
        )
        applied = len(trace.applied_checks)
        not_applicable = sum(
            gap.disposition is CoverageDisposition.NOT_APPLICABLE for gap in trace.coverage_gaps
        )
        unsupported = sum(
            gap.disposition is CoverageDisposition.UNSUPPORTED for gap in trace.coverage_gaps
        )
    return VerificationEvalCaseResult(
        id=case.id,
        mutation=case.mutation,
        expected=case.expected,
        actual=actual,
        failed_categories=failed_categories,
        applied_check_count=applied,
        not_applicable_gap_count=not_applicable,
        unsupported_gap_count=unsupported,
        verified_oracle_regression=case.verified_oracle_regression,
        passed=actual == case.expected,
    )


def _category_accuracy(
    results: tuple[VerificationEvalCaseResult, ...],
    expected_failure: ExpectedVerificationDecision,
) -> float:
    applicable = [result for result in results if result.expected in {"PASS", expected_failure}]
    return sum(result.actual == result.expected for result in applicable) / len(applicable)


def run_verification_evaluation(
    *,
    suite: VerificationEvalSuite,
    suite_fingerprint: str,
    catalog: AssembledSemanticCatalog,
) -> VerificationEvalReport:
    results = tuple(_evaluate_case(catalog, case) for case in suite.cases)
    negative = [result for result in results if result.expected != "PASS"]
    positive = [result for result in results if result.expected == "PASS"]
    integrity = [result for result in results if result.expected == "INTEGRITY_ERROR"]
    context_substitution = [
        result
        for result in results
        if result.mutation in {"RELATIONSHIP_CONTEXT_MISMATCH", "DOCUMENT_CONTEXT_MISMATCH"}
    ]
    truncation = [result for result in results if result.mutation == "TRUNCATED"]
    oracle_regressions = [result for result in results if result.verified_oracle_regression]
    applied = sum(result.applied_check_count for result in results)
    unsupported = sum(result.unsupported_gap_count for result in results)
    metrics = VerificationEvalMetrics(
        case_count=len(results),
        structural_decision_accuracy=_category_accuracy(results, "STRUCTURAL_FAILURE"),
        semantic_decision_accuracy=_category_accuracy(results, "SEMANTIC_FAILURE"),
        empirical_decision_accuracy=_category_accuracy(results, "EMPIRICAL_FAILURE"),
        false_accept_rate=sum(result.actual == "PASS" for result in negative) / len(negative),
        false_reject_rate=sum(result.actual != "PASS" for result in positive) / len(positive),
        identity_mismatch_rejection=sum(result.actual == "INTEGRITY_ERROR" for result in integrity)
        / len(integrity),
        planner_context_substitution_rejection=sum(
            result.actual == "INTEGRITY_ERROR" for result in context_substitution
        )
        / len(context_substitution),
        truncation_rejection=sum(result.actual == "STRUCTURAL_FAILURE" for result in truncation)
        / len(truncation),
        verified_oracle_mismatch_count=sum(
            result.actual == "PASS" for result in oracle_regressions
        ),
        verification_coverage=applied / (applied + unsupported),
    )
    return VerificationEvalReport(
        identity=VerificationEvalIdentity(
            suite_version=suite.version,
            suite_fingerprint=suite_fingerprint,
            verification_policy_version=VERIFICATION_POLICY_VERSION,
            execution_metadata_version=EXECUTION_METADATA_VERSION,
            result_fingerprint_version=RESULT_FINGERPRINT_VERSION,
            planner_context_fingerprint_version=PLANNER_CONTEXT_FINGERPRINT_VERSION,
            sql_guard_policy_version=SQL_GUARD_POLICY_VERSION,
            explain_policy_version=EXPLAIN_POLICY_VERSION,
            catalog_fingerprint=catalog.catalog_fingerprint,
            generated_schema_fingerprint=catalog.generated_metadata_fingerprint,
            semantic_revision=catalog.semantic_revision,
        ),
        metrics=metrics,
        cases=results,
        passed=all(result.passed for result in results)
        and metrics.structural_decision_accuracy == 1.0
        and metrics.semantic_decision_accuracy == 1.0
        and metrics.empirical_decision_accuracy == 1.0
        and metrics.false_accept_rate == 0.0
        and metrics.false_reject_rate == 0.0
        and metrics.identity_mismatch_rejection == 1.0
        and metrics.planner_context_substitution_rejection == 1.0
        and metrics.truncation_rejection == 1.0
        and metrics.verified_oracle_mismatch_count == 0,
    )


def write_verification_eval_report(
    report: VerificationEvalReport,
    *,
    output_path: Path = VERIFICATION_REPORT_PATH,
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


def evaluate_current_verification() -> VerificationEvalReport:
    suite, suite_fingerprint = load_verification_eval_suite()
    report = run_verification_evaluation(
        suite=suite,
        suite_fingerprint=suite_fingerprint,
        catalog=load_assembled_catalog(),
    )
    write_verification_eval_report(report)
    return report


def format_verification_eval_summary(report: VerificationEvalReport) -> str:
    metrics = report.metrics
    status = "PASS" if report.passed else "FAIL"
    return (
        f"Verification eval {status}: cases={metrics.case_count}, "
        f"structural={metrics.structural_decision_accuracy:.3f}, "
        f"semantic={metrics.semantic_decision_accuracy:.3f}, "
        f"empirical={metrics.empirical_decision_accuracy:.3f}, "
        f"false_accept={metrics.false_accept_rate:.3f}, "
        f"false_reject={metrics.false_reject_rate:.3f}, "
        f"identity={metrics.identity_mismatch_rejection:.3f}, "
        f"context_identity={metrics.planner_context_substitution_rejection:.3f}, "
        f"truncation={metrics.truncation_rejection:.3f}, "
        f"verified_oracle_mismatch={metrics.verified_oracle_mismatch_count}, "
        f"coverage={metrics.verification_coverage:.3f}"
    )
