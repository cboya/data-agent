"""Deterministic M9 planner fixtures and provider-neutral doubles."""

from __future__ import annotations

from pydantic import BaseModel

from data_agent.catalog.semantic import AssembledSemanticCatalog
from data_agent.contracts.query import ExpectedColumn, QueryPlan
from data_agent.contracts.requirement import (
    MetricRequirement,
    RequirementState,
    RequirementStatus,
    ResolutionStatus,
    TimeRange,
)
from data_agent.contracts.retrieval import RetrievalHit, RetrievalResult
from tests.retrieval.factories import catalog

INDEX_FINGERPRINT = "d" * 64


def ready_requirement() -> RequirementState:
    return RequirementState(
        version="v0.1",
        goal="Daily actual paid amount",
        metrics=[
            MetricRequirement(
                term="actual paid amount",
                resolved_name="paid_amount",
                status=ResolutionStatus.CONFIRMED,
            )
        ],
        time_range=TimeRange(kind="RELATIVE", value="last_30_days"),
        grain="day",
        status=RequirementStatus.READY,
    )


def retrieval_result(
    tables: tuple[str, ...] = ("fact_order",),
    *,
    assembled: AssembledSemanticCatalog | None = None,
    index_fingerprint: str = INDEX_FINGERPRINT,
) -> RetrievalResult:
    authority = assembled or catalog()
    selected = set(tables)
    relationships = [
        relationship
        for relationship in authority.relationships
        if str(relationship.from_table) in selected and str(relationship.to_table) in selected
    ]
    return RetrievalResult(
        version="v0.1",
        query="daily actual paid amount",
        hits=[
            RetrievalHit(
                table=table,
                lexical_rank=index if index <= 4 else None,
                semantic_rank=index if index <= 4 else None,
                fused_score=1 / index if index <= 4 else 0,
                source="SEED" if index <= 4 else "GRAPH_EXPANSION",
            )
            for index, table in enumerate(tables, start=1)
        ],
        relationships=relationships,
        index_fingerprint=index_fingerprint,
    )


def paid_amount_plan(*, tables: list[str] | None = None, sql: str | None = None) -> QueryPlan:
    return QueryPlan(
        version="v0.1",
        intent="Daily actual paid amount for the last 30 days",
        tables=tables or ["fact_order"],
        assumptions=[],
        sql=(
            sql
            or "SELECT DATE(fact_order.paid_at) AS period, "
            "SUM(fact_order.paid_amount) AS paid_amount "
            "FROM fact_order GROUP BY DATE(fact_order.paid_at)"
        ),
        expected_columns=[
            ExpectedColumn(name="period", semantic_role="day"),
            ExpectedColumn(name="paid_amount", semantic_role="metric"),
        ],
        explanation="Uses paid_at and paid_amount at daily grain.",
    )


class FixedPlanModel:
    def __init__(self, *plans: QueryPlan) -> None:
        self._plans = list(plans)
        self.calls: list[tuple[list[dict[str, str]], type[BaseModel], str]] = []

    async def structured[StructuredResultT: BaseModel](
        self,
        *,
        messages: list[dict[str, str]],
        response_type: type[StructuredResultT],
        purpose: str,
    ) -> StructuredResultT:
        self.calls.append((messages, response_type, purpose))
        if not self._plans:
            raise AssertionError("fixed plan model has no remaining QueryPlan")
        return response_type.model_validate(self._plans.pop(0).model_dump(mode="json"))
