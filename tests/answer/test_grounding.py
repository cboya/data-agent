from __future__ import annotations

import pytest

from data_agent.answer.errors import AnswerGroundingError
from data_agent.answer.grounding import AnswerGroundingPolicy
from data_agent.answer.proposal import AnswerProposal, CellReference
from data_agent.contracts.execution import ExecutionResult
from tests.answer.factories import valid_answer_context
from tests.verification.factories import evidence_bundle


def test_exact_decimal_claim_requires_and_accepts_positional_evidence() -> None:
    proposal = AnswerProposal(
        answer="广东在首日的实付金额是 100.00。",
        evidence_refs=[CellReference(row_index=0, column_index=2)],
    )

    validated = AnswerGroundingPolicy().validate(context=valid_answer_context(), proposal=proposal)

    assert validated == proposal


def test_ungrounded_number_fails_closed() -> None:
    proposal = AnswerProposal(
        answer="广东在首日的实付金额是 999.00。",
        evidence_refs=[CellReference(row_index=0, column_index=2)],
    )

    with pytest.raises(AnswerGroundingError, match="not grounded"):
        AnswerGroundingPolicy().validate(context=valid_answer_context(), proposal=proposal)


def test_request_scope_number_cannot_be_reused_as_result_fact() -> None:
    proposal = AnswerProposal(
        answer="实际支付金额是 30。",
        evidence_refs=[CellReference(row_index=0, column_index=2)],
    )

    with pytest.raises(AnswerGroundingError, match="referenced result evidence"):
        AnswerGroundingPolicy().validate(context=valid_answer_context(), proposal=proposal)


def test_derived_percentage_is_not_authorized_by_source_cells() -> None:
    proposal = AnswerProposal(
        answer="实付金额下降了 20%。",
        evidence_refs=[
            CellReference(row_index=0, column_index=2),
            CellReference(row_index=1, column_index=2),
        ],
    )

    with pytest.raises(AnswerGroundingError, match="percentage"):
        AnswerGroundingPolicy().validate(context=valid_answer_context(), proposal=proposal)


def test_out_of_range_cell_reference_fails_closed() -> None:
    proposal = AnswerProposal(
        answer="实付金额是 100.00。",
        evidence_refs=[CellReference(row_index=0, column_index=9)],
    )

    with pytest.raises(AnswerGroundingError, match="outside"):
        AnswerGroundingPolicy().validate(context=valid_answer_context(), proposal=proposal)


def test_non_empty_result_requires_evidence_even_without_numeric_claim() -> None:
    proposal = AnswerProposal(answer="结果显示广东有记录。", evidence_refs=[])

    with pytest.raises(AnswerGroundingError, match="requires cell evidence"):
        AnswerGroundingPolicy().validate(context=valid_answer_context(), proposal=proposal)


def test_empty_result_cannot_repeat_numeric_scope_literal_without_cell_reference() -> None:
    empty = ExecutionResult(
        version="v0.1",
        columns=["period", "province", "paid_amount"],
        rows=[],
        returned_row_count=0,
        duration_ms=1,
        truncated=False,
    )
    context = valid_answer_context(bundle=evidence_bundle(result=empty))
    proposal = AnswerProposal(
        answer="The verified query for the last 30 days returned no matching rows.",
        evidence_refs=[],
    )

    with pytest.raises(AnswerGroundingError, match="referenced result evidence"):
        AnswerGroundingPolicy().validate(context=context, proposal=proposal)


def test_empty_result_answer_without_numeric_literal_is_allowed() -> None:
    empty = ExecutionResult(
        version="v0.1",
        columns=["period", "province", "paid_amount"],
        rows=[],
        returned_row_count=0,
        duration_ms=1,
        truncated=False,
    )
    context = valid_answer_context(bundle=evidence_bundle(result=empty))
    proposal = AnswerProposal(
        answer="The verified query returned no matching rows.",
        evidence_refs=[],
    )

    assert AnswerGroundingPolicy().validate(context=context, proposal=proposal) == proposal
