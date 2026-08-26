from __future__ import annotations

import asyncio

import pytest

from data_agent.answer.errors import AnswerGroundingError
from data_agent.answer.proposal import AnswerProposal, CellReference
from data_agent.answer.service import AnswerSynthesisMode, AnswerSynthesizer
from tests.answer.factories import FixedAnswerModel, valid_answer_context


def test_synthesizer_makes_one_model_call_and_returns_grounded_language() -> None:
    model = FixedAnswerModel(
        AnswerProposal(
            answer="首日广东实付金额为 100.00。",
            evidence_refs=[CellReference(row_index=0, column_index=2)],
        )
    )

    result = asyncio.run(AnswerSynthesizer(chat_model=model).synthesize(valid_answer_context()))

    assert result.mode is AnswerSynthesisMode.MODEL
    assert result.answer == "首日广东实付金额为 100.00。"
    assert len(model.calls) == 1


def test_grounding_failure_has_no_model_retry() -> None:
    model = FixedAnswerModel(
        AnswerProposal(
            answer="首日广东实付金额为 999.00。",
            evidence_refs=[CellReference(row_index=0, column_index=2)],
        )
    )

    with pytest.raises(AnswerGroundingError):
        asyncio.run(AnswerSynthesizer(chat_model=model).synthesize(valid_answer_context()))

    assert len(model.calls) == 1


def test_oversized_context_uses_deterministic_zero_call_fallback() -> None:
    model = FixedAnswerModel(AnswerProposal(answer="不应调用", evidence_refs=[]))

    result = asyncio.run(
        AnswerSynthesizer(chat_model=model, max_context_rows=1).synthesize(valid_answer_context())
    )

    assert result.mode is AnswerSynthesisMode.DETERMINISTIC_FALLBACK
    assert result.reason == "RESULT_TOO_LARGE"
    assert model.calls == []
