"""Coherent constructed M9→M11 evidence for focused M12 tests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from data_agent.contracts.catalog import (
    Cardinality,
    CatalogColumn,
    CatalogDocument,
    Relationship,
)
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
from data_agent.planning.context import PlannerCatalogIdentity, PlannerContext
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
from data_agent.sql_guard.explain import ExplainPolicy
from data_agent.sql_guard.guard import SQLGuard
from data_agent.sql_guard.service import SQLAdmissionService

_GENERATED_FINGERPRINT = "1" * 64
_SEMANTIC_REVISION = "2" * 64
_CATALOG_FINGERPRINT = "3" * 64
_RETRIEVAL_FINGERPRINT = "4" * 64


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


def _document(table: str, columns: list[tuple[str, list[str]]]) -> CatalogDocument:
    return CatalogDocument(
        version="v0.1",
        table=table,
        aliases=[],
        description=f"Governed {table}",
        business_rules=[],
        columns=[
            CatalogColumn(
                name=name,
                data_type="test",
                description=f"Governed {name}",
                aliases=aliases,
            )
            for name, aliases in columns
        ],
        typical_use_cases=[],
        generated_metadata_fingerprint=_GENERATED_FINGERPRINT,
        semantic_revision=_SEMANTIC_REVISION,
    )


DOCUMENTS = (
    _document(
        "fact_order",
        [
            ("id", []),
            ("user_id", []),
            ("paid_at", []),
            ("paid_amount", ["支付金额", "实付金额"]),
            ("total_amount", ["下单金额"]),
        ],
    ),
    _document("dim_user", [("id", []), ("region_id", [])]),
    _document("dim_region", [("id", []), ("province", ["省份"])]),
)

RELATIONSHIPS = (
    Relationship(
        version="v0.1",
        from_table="fact_order",
        from_column="user_id",
        to_table="dim_user",
        to_column="id",
        cardinality=Cardinality.MANY_TO_ONE,
        description="Order user",
        curated=True,
    ),
    Relationship(
        version="v0.1",
        from_table="dim_user",
        from_column="region_id",
        to_table="dim_region",
        to_column="id",
        cardinality=Cardinality.MANY_TO_ONE,
        description="User region",
        curated=True,
    ),
)

VALID_SQL = (
    "SELECT DATE(o.paid_at) AS period, r.province AS province, "
    "SUM(o.paid_amount) AS paid_amount FROM fact_order AS o "
    "JOIN dim_user AS u ON o.user_id = u.id "
    "JOIN dim_region AS r ON u.region_id = r.id "
    "WHERE o.paid_at >= DATE_SUB(CURRENT_DATE, INTERVAL 30 DAY) "
    "GROUP BY DATE(o.paid_at), r.province"
)


def ready_requirement() -> RequirementState:
    return RequirementState(
        version="v0.1",
        goal="Daily paid amount by province",
        metrics=[
            MetricRequirement(
                term="paid amount",
                resolved_name="paid_amount",
                status=ResolutionStatus.CONFIRMED,
            )
        ],
        dimensions=[
            DimensionRequirement(
                term="province",
                resolved_name="province",
                status=ResolutionStatus.CONFIRMED,
            )
        ],
        time_range=TimeRange(kind="RELATIVE", value="last_30_days"),
        grain="day",
        status=RequirementStatus.READY,
    )


def valid_plan(*, sql: str = VALID_SQL) -> QueryPlan:
    return QueryPlan(
        version="v0.1",
        intent="Daily paid amount by province",
        tables=["fact_order", "dim_user", "dim_region"],
        assumptions=[],
        sql=sql,
        expected_columns=[
            ExpectedColumn(name="period", semantic_role="day"),
            ExpectedColumn(name="province", semantic_role="dimension"),
            ExpectedColumn(name="paid_amount", semantic_role="metric"),
        ],
        explanation="Constructed deterministic verification evidence",
    )


def valid_result() -> ExecutionResult:
    return ExecutionResult(
        version="v0.1",
        columns=["period", "province", "paid_amount"],
        rows=[
            [date(2026, 8, 1), "广东", Decimal("100.00")],
            [date(2026, 8, 2), "广东", Decimal("80.00")],
        ],
        returned_row_count=2,
        duration_ms=12,
        truncated=False,
    )


def _guarded_query(plan: QueryPlan) -> GuardedQuery:
    outcome = SQLAdmissionService(
        guard=SQLGuard(analytics_schema="data_agent"),
        explain_provider=_StaticExplainProvider(),
        explain_policy=ExplainPolicy(max_estimated_rows_per_access=100),
    ).admit(plan)
    assert outcome.guarded_query is not None
    return outcome.guarded_query


@dataclass(frozen=True)
class EvidenceBundle:
    planning_trace: PlanningTrace
    guarded_query: GuardedQuery
    execution_metadata: ExecutionMetadata
    execution_result: ExecutionResult


def evidence_bundle(
    *,
    requirement: RequirementState | None = None,
    plan: QueryPlan | None = None,
    result: ExecutionResult | None = None,
    documents: tuple[CatalogDocument, ...] = DOCUMENTS,
    relationships: tuple[Relationship, ...] = RELATIONSHIPS,
    metadata_overrides: dict[str, Any] | None = None,
) -> EvidenceBundle:
    actual_requirement = requirement or ready_requirement()
    actual_plan = plan or valid_plan()
    actual_result = result or valid_result()
    context = PlannerContext(
        requirement=actual_requirement,
        allowed_tables=tuple(str(document.table) for document in documents),
        documents=documents,
        relationships=relationships,
        identity=PlannerCatalogIdentity(
            catalog_fingerprint=_CATALOG_FINGERPRINT,
            generated_schema_fingerprint=_GENERATED_FINGERPRINT,
            semantic_revision=_SEMANTIC_REVISION,
            retrieval_index_fingerprint=_RETRIEVAL_FINGERPRINT,
        ),
    )
    trace = PlanningTrace(
        context=context,
        plan=actual_plan,
        prompt_version=PLANNER_PROMPT_VERSION,
        model_fingerprint="5" * 64,
        runtime_version="constructed",
        retrieval_index_fingerprint=_RETRIEVAL_FINGERPRINT,
        allowed_tables=tuple(str(document.table) for document in documents),
    )
    query = _guarded_query(actual_plan)
    timestamp = datetime(2026, 8, 26, tzinfo=UTC)
    values: dict[str, Any] = {
        "version": EXECUTION_METADATA_VERSION,
        "execution_id": "m12-constructed-execution",
        "guarded_query_fingerprint": query.capability_fingerprint,
        "sql_digest": query.sql_digest,
        "query_plan_fingerprint": query.query_plan_fingerprint,
        "execution_namespace": query.execution_namespace,
        "guard_policy_version": query.guard_policy_version,
        "explain_policy_version": query.explain_policy_version,
        "physical_tables": tuple(table.qualified_name for table in query.physical_tables),
        "database_schema": query.execution_namespace,
        "database_principal_class": "ANALYTICS_READONLY",
        "max_execution_time_ms": 5_000,
        "client_read_timeout_seconds": 10,
        "max_result_rows": 1_000,
        "max_result_bytes": 8_388_608,
        "result_byte_accounting_version": RESULT_BYTE_ACCOUNTING_VERSION,
        "result_fingerprint_version": RESULT_FINGERPRINT_VERSION,
        "result_fingerprint": execution_result_fingerprint(actual_result),
        "started_at": timestamp,
        "completed_at": timestamp,
        "duration_ms": actual_result.duration_ms,
        "execution_attempt_count": 1,
        "returned_row_count": actual_result.returned_row_count,
        "returned_result_bytes": 100,
        "truncated": actual_result.truncated,
        "outcome": ExecutionOutcome.SUCCEEDED,
        "error_code": None,
        "error_detail": None,
    }
    values.update(metadata_overrides or {})
    return EvidenceBundle(
        planning_trace=trace,
        guarded_query=query,
        execution_metadata=ExecutionMetadata(**values),
        execution_result=actual_result,
    )
