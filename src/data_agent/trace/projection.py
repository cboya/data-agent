"""Bounded, row-free projections from M8-M14 stage evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from data_agent.answer.prompt import ANSWER_PROMPT_VERSION
from data_agent.answer.service import AnswerSynthesisResult
from data_agent.contracts.execution import ExecutionResult
from data_agent.dialogue.prompt import DIALOGUE_PROMPT_VERSION
from data_agent.dialogue.service import PreparedDialogueTurn
from data_agent.planning.service import PlanningTrace
from data_agent.query_runtime.evidence import ExecutionMetadata
from data_agent.repair.evidence import RepairFailure, RepairTrace
from data_agent.retrieval.service import RetrievalTrace
from data_agent.sql_guard.capability import GuardedQuery, query_plan_fingerprint
from data_agent.sql_guard.service import SQLAdmissionOutcome
from data_agent.verification.evidence import VerificationTrace


def evidence_fingerprint(value: BaseModel | Mapping[str, Any]) -> str:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else dict(value)
    canonical = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def dialogue_payload(prepared: PreparedDialogueTurn) -> dict[str, Any]:
    outcome = prepared.outcome
    return {
        "outcome": (
            "CANNOT_RESOLVE" if outcome.decision.action.value == "CANNOT_RESOLVE" else "SUCCEEDED"
        ),
        "action": outcome.decision.action.value,
        "prompt_version": DIALOGUE_PROMPT_VERSION,
        "requirement_status": outcome.requirement.status.value,
        "requirement_fingerprint": evidence_fingerprint(outcome.requirement),
        "requirement_version": str(outcome.requirement.version),
        "user_message_id": str(prepared.user_message.id),
        "assistant_message_id": (
            None if prepared.assistant_message is None else str(prepared.assistant_message.id)
        ),
    }


def retrieval_payload(trace: RetrievalTrace) -> dict[str, Any]:
    return {
        "outcome": "SUCCEEDED",
        "index_fingerprint": str(trace.result.index_fingerprint),
        "result_fingerprint": evidence_fingerprint(trace.result),
        "seed_tables": [str(hit.table) for hit in trace.seed_hits],
        "selected_tables": [str(hit.table) for hit in trace.result.hits],
        "graph_expansion_count": len(trace.graph_expansions),
        "ranks": [
            {
                "table": str(hit.table),
                "source": hit.source,
                "lexical_rank": hit.lexical_rank,
                "semantic_rank": hit.semantic_rank,
            }
            for hit in trace.result.hits
        ],
    }


def planning_payload(trace: PlanningTrace, *, outcome: str = "SUCCEEDED") -> dict[str, Any]:
    return {
        "outcome": outcome,
        "planner_context_fingerprint": trace.planner_context_fingerprint,
        "query_plan_fingerprint": query_plan_fingerprint(trace.plan),
        "retrieval_index_fingerprint": trace.retrieval_index_fingerprint,
        "prompt_version": trace.prompt_version,
        "model_fingerprint": trace.model_fingerprint,
        "runtime_version": trace.runtime_version,
        "allowed_tables": list(trace.allowed_tables),
        "planned_tables": [str(table) for table in trace.plan.tables],
    }


def admission_payload(outcome: SQLAdmissionOutcome) -> dict[str, Any]:
    guarded = outcome.guarded_query
    candidate = outcome.guard.candidate
    return {
        "outcome": "SUCCEEDED" if guarded is not None else "FAILED",
        "guard_status": outcome.guard.result.status.value,
        "guard_violations": [str(value) for value in outcome.guard.result.violations],
        "parse_succeeded": outcome.guard.parse_succeeded,
        "table_scope_compliant": outcome.guard.table_scope_compliant,
        "referenced_tables": [str(value) for value in outcome.guard.result.referenced_tables],
        "candidate_capability_fingerprint": (
            None if candidate is None else candidate.capability_fingerprint
        ),
        "guarded_query_fingerprint": (None if guarded is None else guarded.capability_fingerprint),
        "sql_digest": None if candidate is None else candidate.sql_digest,
        "guard_policy_version": None if candidate is None else candidate.guard_policy_version,
        "explain_policy_version": (None if guarded is None else guarded.explain_policy_version),
        "explain_accepted": (
            None if outcome.explain_result is None else outcome.explain_result.accepted
        ),
        "explain_rejection_reason": (
            None if outcome.explain_result is None else outcome.explain_result.rejection_reason
        ),
    }


def admission_failure_payload(failure: RepairFailure) -> dict[str, Any]:
    return {
        "outcome": "FAILED",
        "failure_stage": failure.stage.value,
        "failure_category": failure.category.value,
        "failure_code": str(failure.code),
        "query_plan_fingerprint": failure.query_plan_fingerprint,
        "planner_context_fingerprint": failure.planner_context_fingerprint,
        "guarded_query_fingerprint": failure.guarded_query_fingerprint,
    }


def admitted_query_payload(guarded: GuardedQuery) -> dict[str, Any]:
    return {
        "outcome": "SUCCEEDED",
        "guard_status": guarded.guard_result.status.value,
        "guard_violations": [],
        "parse_succeeded": True,
        "table_scope_compliant": True,
        "referenced_tables": [str(value) for value in guarded.guard_result.referenced_tables],
        "candidate_capability_fingerprint": None,
        "guarded_query_fingerprint": guarded.capability_fingerprint,
        "sql_digest": guarded.sql_digest,
        "guard_policy_version": guarded.guard_policy_version,
        "explain_policy_version": guarded.explain_policy_version,
        "explain_accepted": True,
        "explain_rejection_reason": None,
    }


def execution_payload(
    metadata: ExecutionMetadata | None,
    *,
    result: ExecutionResult | None = None,
    guarded: GuardedQuery | None = None,
    failure: RepairFailure | None = None,
) -> dict[str, Any]:
    if metadata is None:
        return {
            "outcome": "FAILED",
            "failure_code": None if failure is None else str(failure.code),
            "guarded_query_fingerprint": (
                None if guarded is None else guarded.capability_fingerprint
            ),
            "sql_digest": None if guarded is None else guarded.sql_digest,
        }
    return {
        "outcome": metadata.outcome.value,
        "columns": [] if result is None else [str(column) for column in result.columns],
        "execution_metadata_version": metadata.version,
        "execution_id": metadata.execution_id,
        "guarded_query_fingerprint": metadata.guarded_query_fingerprint,
        "query_plan_fingerprint": metadata.query_plan_fingerprint,
        "planner_context_fingerprint": metadata.planner_context_fingerprint,
        "sql_digest": metadata.sql_digest,
        "execution_namespace": metadata.execution_namespace,
        "principal_class": metadata.database_principal_class,
        "result_fingerprint_version": metadata.result_fingerprint_version,
        "result_fingerprint": metadata.result_fingerprint,
        "returned_row_count": metadata.returned_row_count,
        "returned_result_bytes": metadata.returned_result_bytes,
        "truncated": metadata.truncated,
        "execution_attempt_count": metadata.execution_attempt_count,
        "error_code": metadata.error_code,
    }


def verification_payload(
    trace: VerificationTrace | None,
    *,
    failure: RepairFailure | None = None,
) -> dict[str, Any]:
    if trace is None:
        return {
            "outcome": "FAILED",
            "failure_code": None if failure is None else str(failure.code),
            "failure_category": None if failure is None else failure.category.value,
        }
    return {
        "outcome": trace.result.status,
        "verification_policy_version": str(trace.verification_policy_version),
        "evidence": trace.evidence.model_dump(mode="json"),
        "applied_checks": [str(value) for value in trace.applied_checks],
        "failed_checks": [
            {
                "name": str(check.name),
                "category": check.category,
                "detail": check.detail,
            }
            for check in trace.result.checks
            if not check.passed
        ],
        "coverage_gaps": [
            {
                "name": str(gap.name),
                "category": gap.category,
                "disposition": gap.disposition.value,
            }
            for gap in trace.coverage_gaps
        ],
    }


def repair_payload(trace: RepairTrace) -> dict[str, Any]:
    return trace.model_dump(mode="json")


def synthesis_payload(
    synthesis: AnswerSynthesisResult | None,
    *,
    assistant_message_id: str | None = None,
    error_code: str | None = None,
) -> dict[str, Any]:
    if synthesis is None:
        return {
            "outcome": "FAILED",
            "prompt_version": ANSWER_PROMPT_VERSION,
            "error_code": error_code,
        }
    refs = [
        {"row_index": ref.row_index, "column_index": ref.column_index}
        for ref in synthesis.evidence_refs
    ]
    return {
        "outcome": "SUCCEEDED",
        "prompt_version": ANSWER_PROMPT_VERSION,
        "mode": synthesis.mode.value,
        "limitation": synthesis.reason,
        "evidence_refs": refs,
        "evidence_refs_fingerprint": evidence_fingerprint({"refs": refs}),
        "answer_proposal_fingerprint": synthesis.proposal_fingerprint,
        "assistant_message_id": assistant_message_id,
    }
