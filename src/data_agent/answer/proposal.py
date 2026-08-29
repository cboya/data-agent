"""Narrow provider-facing answer grammar; never a fact envelope."""

from __future__ import annotations

import hashlib
import json
from typing import Literal, Self

from pydantic import Field, model_validator

from data_agent.contracts.base import ContractModel, NonEmptyString


class CellReference(ContractModel):
    row_index: int = Field(ge=0)
    column_index: int = Field(ge=0)


class AnswerProposal(ContractModel):
    version: Literal["v0.1"] = "v0.1"
    answer: NonEmptyString = Field(max_length=4_000)
    evidence_refs: list[CellReference] = Field(max_length=128)

    @model_validator(mode="after")
    def evidence_references_are_unique(self) -> Self:
        keys = [(value.row_index, value.column_index) for value in self.evidence_refs]
        if len(keys) != len(set(keys)):
            raise ValueError("answer evidence references must be unique")
        return self


def answer_proposal_fingerprint(proposal: AnswerProposal) -> str:
    canonical = json.dumps(
        proposal.model_dump(mode="json"),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
