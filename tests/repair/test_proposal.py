"""Evidence-driven provider grammar stays narrower than public QueryPlan v0.1."""

import pytest
from pydantic import ValidationError

from data_agent.contracts.query import QueryPlan
from data_agent.repair.proposal import RepairPlanProposal
from tests.verification.factories import valid_plan


def test_provider_proposal_requires_output_shape_then_normalizes_public_contract() -> None:
    plan = valid_plan()
    proposal = RepairPlanProposal.model_validate(plan.model_dump(mode="json"))

    assert proposal.to_query_plan() == plan
    assert isinstance(proposal.to_query_plan(), QueryPlan)


def test_provider_proposal_rejects_omitted_expected_columns() -> None:
    payload = valid_plan().model_dump(mode="json")
    payload["expected_columns"] = []

    with pytest.raises(ValidationError, match="expected_columns"):
        RepairPlanProposal.model_validate(payload)
