"""One-shot grounded answer synthesis with explicit oversized-result fallback."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from data_agent.answer.context import AnswerSynthesisContext
from data_agent.answer.grounding import AnswerGroundingPolicy
from data_agent.answer.prompt import ANSWER_PROMPT_VERSION, answer_messages
from data_agent.answer.proposal import (
    AnswerProposal,
    CellReference,
    answer_proposal_fingerprint,
)
from data_agent.model_runtime.ports import ChatModel


class AnswerSynthesisMode(StrEnum):
    MODEL = "MODEL"
    DETERMINISTIC_FALLBACK = "DETERMINISTIC_FALLBACK"


@dataclass(frozen=True)
class AnswerSynthesisResult:
    answer: str
    evidence_refs: tuple[CellReference, ...]
    mode: AnswerSynthesisMode
    reason: str | None = None
    proposal_fingerprint: str | None = None


class AnswerSynthesizer:
    def __init__(
        self,
        *,
        chat_model: ChatModel,
        grounding_policy: AnswerGroundingPolicy | None = None,
        max_context_rows: int = 100,
        max_context_bytes: int = 131_072,
    ) -> None:
        if min(max_context_rows, max_context_bytes) < 1:
            raise ValueError("answer synthesis bounds must be positive")
        self._chat_model = chat_model
        self._grounding = grounding_policy or AnswerGroundingPolicy()
        self._max_context_rows = max_context_rows
        self._max_context_bytes = max_context_bytes

    async def synthesize(self, context: AnswerSynthesisContext) -> AnswerSynthesisResult:
        if not isinstance(context, AnswerSynthesisContext):
            raise TypeError("answer synthesizer accepts AnswerSynthesisContext only")
        context.verify_integrity()
        messages = answer_messages(context)
        if (
            context.execution_result.returned_row_count > self._max_context_rows
            or len(messages[1]["content"].encode("utf-8")) > self._max_context_bytes
        ):
            return AnswerSynthesisResult(
                answer="查询已成功并通过当前验证, 请查看返回的数据表。",
                evidence_refs=(),
                mode=AnswerSynthesisMode.DETERMINISTIC_FALLBACK,
                reason="RESULT_TOO_LARGE",
            )
        proposal = await self._chat_model.structured(
            messages=messages,
            response_type=AnswerProposal,
            purpose=ANSWER_PROMPT_VERSION,
        )
        grounded = self._grounding.validate(context=context, proposal=proposal)
        return AnswerSynthesisResult(
            answer=str(grounded.answer),
            evidence_refs=tuple(grounded.evidence_refs),
            mode=AnswerSynthesisMode.MODEL,
            proposal_fingerprint=answer_proposal_fingerprint(proposal),
        )
