"""One-attempt replacement-plan branch with full M9-M12 revalidation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from data_agent.contracts.execution import ExecutionResult
from data_agent.contracts.query import QueryPlan
from data_agent.contracts.run import Run, RunStatus
from data_agent.model_runtime.ports import ChatModel
from data_agent.persistence.errors import PersistenceInvariantError, RepairAttemptsExhaustedError
from data_agent.persistence.ports import RunRepository
from data_agent.planning.context import planner_context_fingerprint
from data_agent.planning.errors import PlannerPolicyError
from data_agent.planning.policy import PlannerPolicy
from data_agent.planning.service import PlanningTrace
from data_agent.query_runtime.errors import RuntimeExecutionError
from data_agent.query_runtime.evidence import ExecutionMetadata
from data_agent.query_runtime.service import RuntimeExecutionEvidence
from data_agent.repair.errors import RepairIntegrityError
from data_agent.repair.evidence import (
    RepairFailure,
    RepairOutcomeKind,
    RepairStage,
    RepairTrace,
    repair_failure_fingerprint,
)
from data_agent.repair.policy import RepairEligibilityPolicy
from data_agent.repair.prompt import QUERY_REPAIR_PROMPT_VERSION, repair_messages
from data_agent.repair.proposal import RepairPlanProposal
from data_agent.sql_guard.capability import GuardedQuery, query_plan_fingerprint
from data_agent.sql_guard.service import SQLAdmissionService
from data_agent.verification.context import build_verification_context
from data_agent.verification.errors import VerificationIntegrityError
from data_agent.verification.evidence import VerificationTrace
from data_agent.verification.service import DeterministicVerifier


@dataclass(frozen=True)
class RepairPipelineOutcome:
    trace: RepairTrace
    run: Run
    replacement_planning_trace: PlanningTrace | None = None
    guarded_query: GuardedQuery | None = None
    execution_metadata: ExecutionMetadata | None = None
    execution_result: ExecutionResult | None = None
    verification_trace: VerificationTrace | None = None


class RepairQueryRuntime(Protocol):
    def execute_with_evidence(self, query: GuardedQuery) -> RuntimeExecutionEvidence: ...


_EXPECTED_RUN_STATUS = {
    RepairStage.SQL_GUARD: RunStatus.VALIDATING,
    RepairStage.EXPLAIN: RunStatus.VALIDATING,
    RepairStage.RUNTIME: RunStatus.EXECUTING,
    RepairStage.VERIFICATION: RunStatus.VERIFYING,
}


class BoundedRepairService:
    """Consume at most one durable attempt and create a fresh downstream evidence branch."""

    def __init__(
        self,
        *,
        chat_model: ChatModel,
        run_repository: RunRepository,
        admission: SQLAdmissionService,
        query_runtime: RepairQueryRuntime,
        verifier: DeterministicVerifier | None = None,
        planner_policy: PlannerPolicy | None = None,
        eligibility_policy: RepairEligibilityPolicy | None = None,
        max_attempts: int = 1,
        model_fingerprint: str | None = None,
        runtime_version: str | None = None,
    ) -> None:
        if max_attempts < 0:
            raise ValueError("repair-attempt bound cannot be negative")
        self._chat_model = chat_model
        self._runs = run_repository
        self._admission = admission
        self._query_runtime = query_runtime
        self._verifier = verifier or DeterministicVerifier()
        self._planner_policy = planner_policy or PlannerPolicy()
        self._eligibility = eligibility_policy or RepairEligibilityPolicy()
        self._max_attempts = max_attempts
        self._model_fingerprint = model_fingerprint
        self._runtime_version = runtime_version
        self._locks: dict[str, asyncio.Lock] = {}

    async def repair(
        self,
        *,
        run_id: str,
        original: PlanningTrace,
        failure: RepairFailure,
        occurred_at: datetime | None = None,
    ) -> RepairPipelineOutcome:
        self._verify_original_branch(run_id, original, failure)
        decision = self._eligibility.evaluate(failure)
        timestamp = occurred_at or datetime.now(UTC)
        if not decision.eligible:
            run = self._runs.get(run_id)
            if decision.terminal_status is not None:
                run = self._runs.transition(
                    run_id,
                    decision.terminal_status,
                    transitioned_at=timestamp,
                    error_code=str(failure.code),
                )
            return RepairPipelineOutcome(
                trace=self._trace(
                    original=original,
                    failure=failure,
                    eligible=False,
                    attempt=0,
                    outcome=RepairOutcomeKind.NOT_ELIGIBLE,
                ),
                run=run,
            )

        lock = self._locks.setdefault(run_id, asyncio.Lock())
        async with lock:
            return await self._repair_eligible(
                run_id=run_id,
                original=original,
                failure=failure,
                occurred_at=timestamp,
            )

    async def _repair_eligible(
        self,
        *,
        run_id: str,
        original: PlanningTrace,
        failure: RepairFailure,
        occurred_at: datetime,
    ) -> RepairPipelineOutcome:
        try:
            claimed = self._runs.claim_repair(
                run_id,
                max_attempts=self._max_attempts,
                expected_status=_EXPECTED_RUN_STATUS[failure.stage],
            )
        except RepairAttemptsExhaustedError:
            current = self._runs.get(run_id)
            if self._max_attempts == 0 and current.status in {
                RunStatus.VALIDATING,
                RunStatus.EXECUTING,
                RunStatus.VERIFYING,
            }:
                current = self._runs.transition(
                    run_id,
                    RunStatus.REPAIR_EXHAUSTED,
                    transitioned_at=occurred_at,
                    error_code="REPAIR_EXHAUSTED",
                )
            return RepairPipelineOutcome(
                trace=self._trace(
                    original=original,
                    failure=failure,
                    eligible=True,
                    attempt=min(current.repair_count, self._max_attempts),
                    outcome=RepairOutcomeKind.EXHAUSTED,
                ),
                run=current,
            )
        except PersistenceInvariantError as error:
            raise RepairIntegrityError(
                "repair failure stage does not match the source Run lifecycle state"
            ) from error

        attempt = claimed.repair_count
        try:
            provider_proposal = await self._chat_model.structured(
                messages=repair_messages(
                    context=original.context,
                    previous_plan=original.plan,
                    failure=failure,
                ),
                response_type=RepairPlanProposal,
                purpose=QUERY_REPAIR_PROMPT_VERSION,
            )
            proposal = provider_proposal.to_query_plan()
        except Exception:
            terminal = self._exhaust(run_id, occurred_at, "REPAIR_MODEL_FAILED")
            return RepairPipelineOutcome(
                trace=self._trace(
                    original=original,
                    failure=failure,
                    eligible=True,
                    attempt=attempt,
                    outcome=RepairOutcomeKind.MODEL_FAILED,
                ),
                run=terminal,
            )

        try:
            replacement = self._accept_replacement(original, proposal)
        except PlannerPolicyError:
            terminal = self._exhaust(run_id, occurred_at, "REPAIR_PLAN_POLICY_FAILED")
            return RepairPipelineOutcome(
                trace=self._trace(
                    original=original,
                    failure=failure,
                    eligible=True,
                    attempt=attempt,
                    outcome=RepairOutcomeKind.POLICY_FAILED,
                    replacement=proposal,
                ),
                run=terminal,
            )

        admission = self._admission.admit(
            replacement.plan,
            planner_context_fingerprint=replacement.planner_context_fingerprint,
        )
        if admission.guarded_query is None:
            terminal = self._exhaust(run_id, occurred_at, "REPAIR_ADMISSION_FAILED")
            return RepairPipelineOutcome(
                trace=self._trace(
                    original=original,
                    failure=failure,
                    eligible=True,
                    attempt=attempt,
                    outcome=RepairOutcomeKind.ADMISSION_FAILED,
                    replacement=replacement.plan,
                ),
                run=terminal,
                replacement_planning_trace=replacement,
            )

        query = admission.guarded_query
        executing = self._runs.transition(
            run_id,
            RunStatus.EXECUTING,
            transitioned_at=occurred_at,
        )
        try:
            execution = self._query_runtime.execute_with_evidence(query)
        except RuntimeExecutionError:
            terminal = self._exhaust(run_id, occurred_at, "REPAIR_EXECUTION_FAILED")
            return RepairPipelineOutcome(
                trace=self._trace(
                    original=original,
                    failure=failure,
                    eligible=True,
                    attempt=attempt,
                    outcome=RepairOutcomeKind.EXECUTION_FAILED,
                    replacement=replacement.plan,
                ),
                run=terminal,
                replacement_planning_trace=replacement,
                guarded_query=query,
            )
        verifying = self._runs.transition(
            executing.id,
            RunStatus.VERIFYING,
            transitioned_at=occurred_at,
        )
        try:
            verification = self._verifier.verify(
                build_verification_context(
                    planning_trace=replacement,
                    guarded_query=query,
                    execution_metadata=execution.metadata,
                    execution_result=execution.result,
                )
            )
        except VerificationIntegrityError:
            terminal = self._exhaust(run_id, occurred_at, "REPAIR_VERIFICATION_INTEGRITY")
            return RepairPipelineOutcome(
                trace=self._trace(
                    original=original,
                    failure=failure,
                    eligible=True,
                    attempt=attempt,
                    outcome=RepairOutcomeKind.VERIFICATION_FAILED,
                    replacement=replacement.plan,
                ),
                run=terminal,
                replacement_planning_trace=replacement,
                guarded_query=query,
                execution_metadata=execution.metadata,
                execution_result=execution.result,
            )
        if verification.result.status != "PASSED":
            terminal = self._exhaust(run_id, occurred_at, "REPAIR_VERIFICATION_FAILED")
            return RepairPipelineOutcome(
                trace=self._trace(
                    original=original,
                    failure=failure,
                    eligible=True,
                    attempt=attempt,
                    outcome=RepairOutcomeKind.VERIFICATION_FAILED,
                    replacement=replacement.plan,
                ),
                run=terminal,
                replacement_planning_trace=replacement,
                guarded_query=query,
                execution_metadata=execution.metadata,
                execution_result=execution.result,
                verification_trace=verification,
            )
        ready_for_synthesis = self._runs.transition(
            verifying.id,
            RunStatus.SYNTHESIZING,
            transitioned_at=occurred_at,
        )
        return RepairPipelineOutcome(
            trace=self._trace(
                original=original,
                failure=failure,
                eligible=True,
                attempt=attempt,
                outcome=RepairOutcomeKind.SUCCEEDED,
                replacement=replacement.plan,
                verification=verification,
            ),
            run=ready_for_synthesis,
            replacement_planning_trace=replacement,
            guarded_query=query,
            execution_metadata=execution.metadata,
            execution_result=execution.result,
            verification_trace=verification,
        )

    def _accept_replacement(
        self,
        original: PlanningTrace,
        proposal: QueryPlan,
    ) -> PlanningTrace:
        plan = self._planner_policy.validate(proposal, context=original.context)
        return PlanningTrace(
            context=original.context,
            planner_context_fingerprint=original.planner_context_fingerprint,
            plan=plan,
            prompt_version=QUERY_REPAIR_PROMPT_VERSION,
            model_fingerprint=self._model_fingerprint,
            runtime_version=self._runtime_version,
            retrieval_index_fingerprint=original.retrieval_index_fingerprint,
            allowed_tables=original.allowed_tables,
        )

    def _verify_original_branch(
        self,
        run_id: str,
        original: PlanningTrace,
        failure: RepairFailure,
    ) -> None:
        if run_id != failure.source_run_id:
            raise RepairIntegrityError("repair failure does not belong to the supplied source Run")
        actual_context = planner_context_fingerprint(original.context)
        actual_plan = query_plan_fingerprint(original.plan)
        if (
            actual_context != original.planner_context_fingerprint
            or actual_context != failure.planner_context_fingerprint
            or actual_plan != failure.query_plan_fingerprint
        ):
            raise RepairIntegrityError("repair failure does not match the original M9 branch")

    def _exhaust(self, run_id: str, occurred_at: datetime, error_code: str) -> Run:
        return self._runs.transition(
            run_id,
            RunStatus.REPAIR_EXHAUSTED,
            transitioned_at=occurred_at,
            error_code=error_code,
        )

    def _trace(
        self,
        *,
        original: PlanningTrace,
        failure: RepairFailure,
        eligible: bool,
        attempt: int,
        outcome: RepairOutcomeKind,
        replacement: QueryPlan | None = None,
        verification: VerificationTrace | None = None,
    ) -> RepairTrace:
        return RepairTrace(
            source_run_id=failure.source_run_id,
            prompt_version=QUERY_REPAIR_PROMPT_VERSION,
            attempt=attempt,
            max_attempts=self._max_attempts,
            eligible=eligible,
            failure_fingerprint=repair_failure_fingerprint(failure),
            original_query_plan_fingerprint=query_plan_fingerprint(original.plan),
            replacement_query_plan_fingerprint=(
                None if replacement is None else query_plan_fingerprint(replacement)
            ),
            planner_context_fingerprint=original.planner_context_fingerprint,
            model_fingerprint=self._model_fingerprint,
            runtime_version=self._runtime_version,
            outcome=outcome,
            final_verification_evidence=(None if verification is None else verification.evidence),
        )
