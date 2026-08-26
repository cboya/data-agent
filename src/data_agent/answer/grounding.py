"""Conservative deterministic grounding for result-number claims and cell references."""

from __future__ import annotations

import math
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from data_agent.answer.context import AnswerSynthesisContext
from data_agent.answer.errors import AnswerGroundingError
from data_agent.answer.proposal import AnswerProposal

_NUMBER_PATTERN = re.compile(r"(?<![A-Za-z0-9_.])[-+]?\d[\d,]*(?:\.\d+)?%?(?![A-Za-z0-9_.])")
ANSWER_GROUNDING_POLICY_VERSION = "answer-grounding-v0.2"


def _number_tokens(value: str) -> tuple[str, ...]:
    return tuple(match.group(0) for match in _NUMBER_PATTERN.finditer(value))


def _number_value(token: str) -> Decimal:
    raw = token.rstrip("%").replace(",", "")
    try:
        return Decimal(raw)
    except InvalidOperation as error:
        raise AnswerGroundingError(f"answer contains an invalid numeric token: {token}") from error


def _cell_number_tokens(value: object) -> tuple[str, ...]:
    if value is None or isinstance(value, bool):
        return ()
    if isinstance(value, int | Decimal):
        return (str(value),)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise AnswerGroundingError("referenced result contains a non-finite float")
        return (repr(value),)
    if isinstance(value, datetime):
        return _number_tokens(value.isoformat(timespec="microseconds"))
    if isinstance(value, date):
        return _number_tokens(value.isoformat())
    if isinstance(value, str):
        return _number_tokens(value)
    raise AnswerGroundingError(f"referenced result type is unsupported: {type(value).__name__}")


class AnswerGroundingPolicy:
    """Require positional evidence and reject ungrounded numeric language."""

    def validate(
        self,
        *,
        context: AnswerSynthesisContext,
        proposal: AnswerProposal,
    ) -> AnswerProposal:
        context.verify_integrity()
        result = context.execution_result
        references = {(value.row_index, value.column_index) for value in proposal.evidence_refs}
        for row_index, column_index in references:
            if row_index >= len(result.rows) or column_index >= len(result.columns):
                raise AnswerGroundingError("answer evidence reference is outside ExecutionResult")
        if result.rows and not references:
            raise AnswerGroundingError("non-empty result answer requires cell evidence")
        if not result.rows and references:
            raise AnswerGroundingError("empty result answer cannot cite a result cell")

        allowed_tokens: list[str] = []
        for row_index, column_index in references:
            allowed_tokens.extend(_cell_number_tokens(result.rows[row_index][column_index]))
        allowed_plain = [
            _number_value(token) for token in allowed_tokens if not token.endswith("%")
        ]
        allowed_percent = {
            token.replace(",", "") for token in allowed_tokens if token.endswith("%")
        }
        for token in _number_tokens(str(proposal.answer)):
            if token.endswith("%"):
                normalized = token.replace(",", "")
                if normalized not in allowed_percent:
                    raise AnswerGroundingError(
                        f"answer percentage is not an exact referenced result fact: {token}"
                    )
            elif _number_value(token) not in allowed_plain:
                raise AnswerGroundingError(
                    f"answer numeric fact is not grounded in referenced result evidence: {token}"
                )
        return proposal
