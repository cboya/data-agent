import asyncio
import os

import pytest

from data_agent.config import Settings
from data_agent.contracts.requirement import (
    MetricRequirement,
    RequirementState,
    RequirementStatus,
    ResolutionStatus,
    TimeRange,
)
from data_agent.contracts.retrieval import RetrievalHit, RetrievalResult
from data_agent.planning.runtime import load_current_planner_runtime

pytestmark = [
    pytest.mark.integration,
    pytest.mark.ollama,
    pytest.mark.skipif(
        os.environ.get("RUN_OLLAMA_INTEGRATION") != "1",
        reason="set RUN_OLLAMA_INTEGRATION=1 to exercise structured planning",
    ),
]


def test_real_ollama_produces_bound_mysql_query_plan() -> None:
    settings = Settings()  # type: ignore[call-arg]
    runtime = asyncio.run(load_current_planner_runtime(settings))
    tables = (
        "fact_order",
        "fact_payment_transaction",
        "fact_order_item",
        "fact_refund",
        "dim_channel",
        "dim_user",
        "dim_product",
    )
    selected = set(tables)
    retrieval = RetrievalResult(
        version="v0.1",
        query="最近30天每日实际支付金额",
        hits=[
            RetrievalHit(
                table=table,
                lexical_rank=rank if rank <= 4 else None,
                semantic_rank=rank if rank <= 4 else None,
                fused_score=1.0 / rank if rank <= 4 else 0.0,
                source="SEED" if rank <= 4 else "GRAPH_EXPANSION",
            )
            for rank, table in enumerate(tables, start=1)
        ],
        relationships=[
            relationship
            for relationship in runtime.retrieval.authority.assembled.relationships
            if str(relationship.from_table) in selected and str(relationship.to_table) in selected
        ],
        index_fingerprint=runtime.retrieval.index.fingerprint,
    )
    requirement = RequirementState(
        version="v0.1",
        goal="最近30天每日实际支付金额, 输出 period 和 paid_amount",
        metrics=[
            MetricRequirement(
                term="实际支付金额",
                resolved_name="paid_amount",
                status=ResolutionStatus.CONFIRMED,
            )
        ],
        time_range=TimeRange(kind="RELATIVE", value="last_30_days"),
        grain="day",
        status=RequirementStatus.READY,
    )

    trace = asyncio.run(
        runtime.planner.plan(
            requirement=requirement,
            retrieval=retrieval,
            catalog=runtime.retrieval.authority.assembled,
            expected_retrieval_index_fingerprint=runtime.retrieval.index.fingerprint,
        )
    )

    assert trace.plan.tables == ["fact_order"]
    assert {str(column.name) for column in trace.plan.expected_columns} >= {
        "period",
        "paid_amount",
    }
    assert ".paid_amount" in trace.plan.sql
    assert ".paid_at" in trace.plan.sql
    assert "DATE('now'" not in trace.plan.sql
    assert trace.model_fingerprint == runtime.retrieval.diagnostics.chat.value
