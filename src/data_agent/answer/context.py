"""Integrity-checked M14 context for exactly one final M9-M12 branch."""

from __future__ import annotations

from dataclasses import dataclass, field

from data_agent.answer.errors import AnswerIntegrityError
from data_agent.contracts.execution import ExecutionResult
from data_agent.contracts.requirement import RequirementState, RequirementStatus
from data_agent.planning.service import PlanningTrace
from data_agent.query_runtime.evidence import ExecutionMetadata
from data_agent.repair.evidence import RepairOutcomeKind, RepairTrace
from data_agent.sql_guard.capability import GuardedQuery, query_plan_fingerprint
from data_agent.verification.context import build_verification_context
from data_agent.verification.evidence import VerificationEvidenceIdentity, VerificationTrace

_ANSWER_CONTEXT_TOKEN = object()


def _verification_identity(metadata: ExecutionMetadata) -> VerificationEvidenceIdentity:
    if metadata.result_fingerprint is None:
        raise AnswerIntegrityError("answer evidence has no execution-result fingerprint")
    return VerificationEvidenceIdentity(
        query_plan_fingerprint=metadata.query_plan_fingerprint,
        guarded_query_fingerprint=metadata.guarded_query_fingerprint,
        execution_id=metadata.execution_id,
        sql_digest=metadata.sql_digest,
        execution_namespace=metadata.execution_namespace,
        result_fingerprint_version=metadata.result_fingerprint_version,
        result_fingerprint=metadata.result_fingerprint,
    )


@dataclass(frozen=True)
class AnswerSynthesisContext:
    """One coherent PASSED branch; construct only through the builder below."""

    session_id: str
    run_id: str
    requirement: RequirementState
    planning_trace: PlanningTrace
    guarded_query: GuardedQuery
    execution_metadata: ExecutionMetadata
    execution_result: ExecutionResult
    verification_trace: VerificationTrace
    repair_trace: RepairTrace | None
    _token: object = field(repr=False, compare=False)

    def verify_integrity(self) -> None:
        if self._token is not _ANSWER_CONTEXT_TOKEN:
            raise AnswerIntegrityError(
                "AnswerSynthesisContext can only be built from validated pipeline evidence"
            )
        if not self.session_id.strip() or not self.run_id.strip():
            raise AnswerIntegrityError("answer context requires session and Run identities")
        if self.requirement.status is not RequirementStatus.READY:
            raise AnswerIntegrityError("answer synthesis requires a READY RequirementState")
        if self.requirement != self.planning_trace.context.requirement:
            raise AnswerIntegrityError("answer requirement does not match final planning evidence")
        try:
            verified = build_verification_context(
                planning_trace=self.planning_trace,
                guarded_query=self.guarded_query,
                execution_metadata=self.execution_metadata,
                execution_result=self.execution_result,
            )
            verified.verify_integrity()
        except Exception as error:
            raise AnswerIntegrityError("answer branch failed M9-M11 identity validation") from error
        if self.verification_trace.result.status != "PASSED":
            raise AnswerIntegrityError("failed verification cannot enter answer synthesis")
        expected_verification = _verification_identity(self.execution_metadata)
        if self.verification_trace.evidence != expected_verification:
            raise AnswerIntegrityError("answer branch does not match M12 verification evidence")
        if self.repair_trace is not None:
            if self.repair_trace.outcome is not RepairOutcomeKind.SUCCEEDED:
                raise AnswerIntegrityError("answer context cannot use an unsuccessful repair trace")
            if self.repair_trace.source_run_id != self.run_id:
                raise AnswerIntegrityError("repair trace belongs to a different Run")
            if (
                self.repair_trace.replacement_query_plan_fingerprint
                != query_plan_fingerprint(self.planning_trace.plan)
                or self.repair_trace.planner_context_fingerprint
                != self.planning_trace.planner_context_fingerprint
                or self.repair_trace.final_verification_evidence != self.verification_trace.evidence
            ):
                raise AnswerIntegrityError("repair trace does not bind the final verified branch")


def build_answer_synthesis_context(
    *,
    session_id: str,
    run_id: str,
    planning_trace: PlanningTrace,
    guarded_query: GuardedQuery,
    execution_metadata: ExecutionMetadata,
    execution_result: ExecutionResult,
    verification_trace: VerificationTrace,
    repair_trace: RepairTrace | None = None,
) -> AnswerSynthesisContext:
    context = AnswerSynthesisContext(
        session_id=session_id,
        run_id=run_id,
        requirement=planning_trace.context.requirement,
        planning_trace=planning_trace,
        guarded_query=guarded_query,
        execution_metadata=execution_metadata,
        execution_result=execution_result,
        verification_trace=verification_trace,
        repair_trace=repair_trace,
        _token=_ANSWER_CONTEXT_TOKEN,
    )
    context.verify_integrity()
    return context
