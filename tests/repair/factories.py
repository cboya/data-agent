"""Coherent M13 test doubles over the real M9-M12 services."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime

from pydantic import BaseModel

from data_agent.contracts.base import AwareDateTime
from data_agent.contracts.query import QueryPlan
from data_agent.contracts.run import Run, RunStatus
from data_agent.persistence.errors import PersistenceInvariantError, RepairAttemptsExhaustedError
from data_agent.planning.service import PlanningTrace
from data_agent.query_runtime.evidence import (
    EXECUTION_METADATA_VERSION,
    RESULT_BYTE_ACCOUNTING_VERSION,
    RESULT_FINGERPRINT_VERSION,
    ExecutionMetadata,
    ExecutionOutcome,
    execution_result_fingerprint,
)
from data_agent.query_runtime.service import RuntimeExecutionEvidence
from data_agent.run_state import TERMINAL_RUN_STATUSES, RunStateMachine
from data_agent.sql_guard.capability import GuardedQuery, GuardedSQL
from tests.verification.factories import evidence_bundle, valid_plan, valid_result


def original_trace(plan: QueryPlan | None = None) -> PlanningTrace:
    trace = evidence_bundle().planning_trace
    return trace if plan is None else replace(trace, plan=plan)


class FixedRepairModel:
    def __init__(
        self,
        proposal: QueryPlan | None = None,
        *,
        error: Exception | None = None,
        started: asyncio.Event | None = None,
        release: asyncio.Event | None = None,
    ) -> None:
        self.proposal = proposal or valid_plan()
        self.error = error
        self.started = started
        self.release = release
        self.calls: list[tuple[list[dict[str, str]], type[BaseModel], str]] = []

    async def structured[StructuredResultT: BaseModel](
        self,
        *,
        messages: list[dict[str, str]],
        response_type: type[StructuredResultT],
        purpose: str,
    ) -> StructuredResultT:
        self.calls.append((messages, response_type, purpose))
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            await self.release.wait()
        if self.error is not None:
            raise self.error
        return response_type.model_validate(self.proposal.model_dump(mode="json"))


class StaticExplainProvider:
    def explain(self, candidate: GuardedSQL) -> str:
        accesses = [
            {
                "table_name": table.name,
                "access_type": "ALL",
                "rows_examined_per_scan": 10,
            }
            for table in candidate.physical_tables
        ]
        return json.dumps({"query_block": {"nested_loop": [{"table": item} for item in accesses]}})


class CoherentRuntime:
    def execute_with_evidence(self, query: GuardedQuery) -> RuntimeExecutionEvidence:
        result = valid_result()
        now = datetime(2026, 8, 26, tzinfo=UTC)
        metadata = ExecutionMetadata(
            version=EXECUTION_METADATA_VERSION,
            execution_id="m13-replacement-execution",
            guarded_query_fingerprint=query.capability_fingerprint,
            sql_digest=query.sql_digest,
            query_plan_fingerprint=query.query_plan_fingerprint,
            planner_context_fingerprint=query.planner_context_fingerprint,
            execution_namespace=query.execution_namespace,
            guard_policy_version=query.guard_policy_version,
            explain_policy_version=query.explain_policy_version,
            physical_tables=tuple(table.qualified_name for table in query.physical_tables),
            database_schema=query.execution_namespace,
            database_principal_class="ANALYTICS_READONLY",
            max_execution_time_ms=5_000,
            client_read_timeout_seconds=10,
            max_result_rows=1_000,
            max_result_bytes=8_388_608,
            result_byte_accounting_version=RESULT_BYTE_ACCOUNTING_VERSION,
            result_fingerprint_version=RESULT_FINGERPRINT_VERSION,
            result_fingerprint=execution_result_fingerprint(result),
            started_at=now,
            completed_at=now,
            duration_ms=result.duration_ms,
            execution_attempt_count=1,
            returned_row_count=result.returned_row_count,
            returned_result_bytes=100,
            truncated=False,
            outcome=ExecutionOutcome.SUCCEEDED,
        )
        return RuntimeExecutionEvidence(result=result, metadata=metadata)


class MemoryRunRepository:
    def __init__(
        self,
        *,
        run_id: str = "m13_run",
        status: RunStatus = RunStatus.VALIDATING,
        repair_count: int = 0,
    ) -> None:
        self.run = Run(
            id=run_id,
            session_id="m13_session",
            status=status,
            repair_count=repair_count,
            started_at=datetime(2026, 8, 26, tzinfo=UTC),
        )
        self.claim_count = 0

    def create(self, run: Run) -> Run:
        self.run = run
        return run

    def get(self, run_id: str) -> Run:
        assert run_id == self.run.id
        return self.run

    def transition(
        self,
        run_id: str,
        target: RunStatus,
        *,
        transitioned_at: AwareDateTime,
        error_code: str | None = None,
    ) -> Run:
        assert run_id == self.run.id
        RunStateMachine.transition(self.run.status, target)
        self.run = self.run.model_copy(
            update={
                "status": target,
                "completed_at": transitioned_at if target in TERMINAL_RUN_STATUSES else None,
                "error_code": error_code,
            }
        )
        RunStateMachine.require_consistent(self.run)
        return self.run

    def claim_repair(
        self,
        run_id: str,
        *,
        max_attempts: int,
        expected_status: RunStatus,
    ) -> Run:
        assert run_id == self.run.id
        if self.run.repair_count >= max_attempts:
            raise RepairAttemptsExhaustedError("repair bound exhausted")
        if self.run.status is not expected_status:
            raise PersistenceInvariantError("run does not match failure stage")
        self.claim_count += 1
        self.run = self.run.model_copy(
            update={
                "status": RunStatus.VALIDATING,
                "repair_count": self.run.repair_count + 1,
                "completed_at": None,
                "error_code": None,
            }
        )
        return self.run
