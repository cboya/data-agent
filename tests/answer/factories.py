"""Coherent final-branch fixtures and a provider-neutral answer double."""

from __future__ import annotations

from pydantic import BaseModel

from data_agent.answer.context import AnswerSynthesisContext, build_answer_synthesis_context
from data_agent.answer.proposal import AnswerProposal
from data_agent.verification.context import build_verification_context
from data_agent.verification.service import DeterministicVerifier
from tests.verification.factories import EvidenceBundle, evidence_bundle


def valid_answer_context(
    *,
    bundle: EvidenceBundle | None = None,
    session_id: str = "session-m14",
    run_id: str = "run-m14",
) -> AnswerSynthesisContext:
    actual = bundle or evidence_bundle()
    verification = DeterministicVerifier().verify(
        build_verification_context(
            planning_trace=actual.planning_trace,
            guarded_query=actual.guarded_query,
            execution_metadata=actual.execution_metadata,
            execution_result=actual.execution_result,
        )
    )
    assert verification.result.status == "PASSED"
    return build_answer_synthesis_context(
        session_id=session_id,
        run_id=run_id,
        planning_trace=actual.planning_trace,
        guarded_query=actual.guarded_query,
        execution_metadata=actual.execution_metadata,
        execution_result=actual.execution_result,
        verification_trace=verification,
    )


class FixedAnswerModel:
    def __init__(
        self,
        proposal: AnswerProposal,
        *,
        error: Exception | None = None,
    ) -> None:
        self._proposal = proposal
        self._error = error
        self.calls: list[tuple[list[dict[str, str]], type[BaseModel], str]] = []

    async def structured[StructuredResultT: BaseModel](
        self,
        *,
        messages: list[dict[str, str]],
        response_type: type[StructuredResultT],
        purpose: str,
    ) -> StructuredResultT:
        self.calls.append((messages, response_type, purpose))
        if self._error is not None:
            raise self._error
        return response_type.model_validate(self._proposal.model_dump(mode="json"))
