from __future__ import annotations

import pytest

from data_agent.answer.context import build_answer_synthesis_context
from data_agent.answer.errors import AnswerIntegrityError
from data_agent.contracts.verification import CheckResult, VerificationResult
from data_agent.verification.context import build_verification_context
from data_agent.verification.evidence import VerificationTrace
from data_agent.verification.service import DeterministicVerifier
from tests.answer.factories import valid_answer_context
from tests.verification.factories import evidence_bundle


def test_builder_accepts_one_coherent_passed_branch() -> None:
    context = valid_answer_context()

    context.verify_integrity()
    assert context.verification_trace.result.status == "PASSED"
    assert context.repair_trace is None


def test_builder_rejects_failed_verification() -> None:
    bundle = evidence_bundle()
    passed = DeterministicVerifier().verify(
        build_verification_context(
            planning_trace=bundle.planning_trace,
            guarded_query=bundle.guarded_query,
            execution_metadata=bundle.execution_metadata,
            execution_result=bundle.execution_result,
        )
    )
    failed = VerificationTrace(
        evidence=passed.evidence,
        applied_checks=("forced_failure",),
        coverage_gaps=passed.coverage_gaps,
        result=VerificationResult(
            version="v0.1",
            status="FAILED",
            checks=[
                CheckResult(
                    name="forced_failure",
                    category="EMPIRICAL",
                    passed=False,
                    detail="constructed failure",
                )
            ],
        ),
    )

    with pytest.raises(AnswerIntegrityError, match="failed verification"):
        build_answer_synthesis_context(
            session_id="session-m14",
            run_id="run-m14",
            planning_trace=bundle.planning_trace,
            guarded_query=bundle.guarded_query,
            execution_metadata=bundle.execution_metadata,
            execution_result=bundle.execution_result,
            verification_trace=failed,
        )


def test_builder_rejects_verification_from_a_different_result() -> None:
    first = evidence_bundle()
    second = evidence_bundle(metadata_overrides={"execution_id": "different-execution"})
    second_trace = DeterministicVerifier().verify(
        build_verification_context(
            planning_trace=second.planning_trace,
            guarded_query=second.guarded_query,
            execution_metadata=second.execution_metadata,
            execution_result=second.execution_result,
        )
    )

    with pytest.raises(AnswerIntegrityError, match="M12 verification evidence"):
        build_answer_synthesis_context(
            session_id="session-m14",
            run_id="run-m14",
            planning_trace=first.planning_trace,
            guarded_query=first.guarded_query,
            execution_metadata=first.execution_metadata,
            execution_result=first.execution_result,
            verification_trace=second_trace,
        )
