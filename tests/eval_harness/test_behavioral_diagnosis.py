from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic import ValidationError

from data_agent.contracts.query import ExpectedColumn, QueryPlan
from data_agent.contracts.requirement import (
    DimensionRequirement,
    RequirementState,
    RequirementStatus,
    ResolutionStatus,
)
from data_agent.verification.evidence import VerificationTrace
from eval_harness.behavioral_diagnosis import (
    _FALSE_ACCEPT_SCENARIOS,
    DIAGNOSIS_JSON_PATH,
    BehavioralDiagnosisReport,
    M8ReplayCase,
    M8ReplaySummary,
    M8ReplayTurn,
    StructuredModelCallOutcome,
    _classify_m8_case,
    _forensic_ownership,
)
from eval_harness.loader import load_golden


def _turn(
    *,
    standalone_action: str | None,
    status: str = "SUCCEEDED",
    error: str | None = None,
) -> M8ReplayTurn:
    return M8ReplayTurn(
        turn_number=1,
        user_message="统计订单数",
        expected_action="READY",
        original_stored_e2e_action="ASK_CLARIFICATION",
        standalone_m8_action=standalone_action,
        blockers=(),
        structured_dialogue_proposal=None,
        normalized_dialogue_decision=None,
        requirement_patch=None,
        merged_requirement_state=None,
        structured_model_call_outcome=StructuredModelCallOutcome(
            purpose="dialogue-understanding-v0.20",
            response_type="DialogueProposal",
            status=cast(Any, status),
            duration_ms=1,
        ),
        normalization_or_policy_error=error,
        prompt_model_environment_identity="a" * 64,
    )


@pytest.mark.parametrize(
    ("turn", "expected"),
    [
        (_turn(standalone_action="ASK_CLARIFICATION"), "STANDALONE_M8_ALSO_CLARIFIES"),
        (_turn(standalone_action="READY"), "STANDALONE_READY_E2E_CLARIFIED"),
        (
            _turn(standalone_action=None, status="TIMEOUT"),
            "STANDALONE_STRUCTURED_MODEL_FAILURE",
        ),
        (
            _turn(standalone_action=None, error="ValueError: normalization failed"),
            "STANDALONE_STRUCTURED_MODEL_FAILURE",
        ),
        (_turn(standalone_action="CANNOT_RESOLVE"), "SPEC_ORACLE_REVIEW_REQUIRED"),
    ],
)
def test_m8_case_classification_is_exclusive(
    turn: M8ReplayTurn,
    expected: str,
) -> None:
    assert _classify_m8_case((turn,)) == expected


def test_m8_summary_requires_exact_35_case_partition() -> None:
    case = M8ReplayCase(
        case_id="case-1",
        classification="STANDALONE_M8_ALSO_CLARIFIES",
        turns=(_turn(standalone_action="ASK_CLARIFICATION"),),
    )

    with pytest.raises(ValidationError, match="at least 35"):
        M8ReplaySummary(
            case_count=35,
            classification_counts={"STANDALONE_M8_ALSO_CLARIFIES": 35},
            blocker_field_distribution={},
            cases=(case,),
        )


def test_false_accept_scope_is_exactly_four_grain_and_two_shape_cases() -> None:
    assert len(_FALSE_ACCEPT_SCENARIOS) == 6
    assert list(_FALSE_ACCEPT_SCENARIOS.values()).count("EXTRA_GRAIN") == 4
    assert list(_FALSE_ACCEPT_SCENARIOS.values()).count("OUTPUT_SHAPE") == 2


def test_extra_grain_false_accept_is_owned_by_m9_and_m12() -> None:
    suite, _ = load_golden()
    case = next(value for value in suite.cases if value.id == "simple-gmv")
    requirement = RequirementState(
        version="v0.1",
        status=RequirementStatus.READY,
    )
    plan = QueryPlan(
        version="v0.1",
        intent="GMV",
        tables=["fact_order", "dim_channel"],
        sql="SELECT channel, SUM(total_amount) AS gmv FROM fact_order GROUP BY channel",
        expected_columns=[ExpectedColumn(name="channel"), ExpectedColumn(name="gmv")],
    )
    verification = cast(
        VerificationTrace,
        SimpleNamespace(result=SimpleNamespace(status="PASSED")),
    )

    owner, _, divergence, milestones = _forensic_ownership(
        case=case,
        scenario="EXTRA_GRAIN",
        requirement=requirement,
        plan=plan,
        execution_columns=("channel", "gmv"),
        verification=verification,
        oracle_passed=False,
    )

    assert owner == "BOTH_M9_AND_M12"
    assert divergence == "QueryPlan"
    assert milestones == ("M9", "M12")


def test_output_shape_missing_from_requirement_requires_upstream_contract_review() -> None:
    suite, _ = load_golden()
    case = next(value for value in suite.cases if value.id == "agg-gmv-channel")
    requirement = RequirementState(
        version="v0.1",
        dimensions=[
            DimensionRequirement(
                term="订单归属渠道",
                resolved_name="channel",
                status=ResolutionStatus.INFERRED,
            )
        ],
        status=RequirementStatus.READY,
    )
    plan = QueryPlan(
        version="v0.1",
        intent="channel GMV",
        tables=["fact_order", "dim_channel"],
        sql="SELECT channel, SUM(total_amount) AS gmv FROM fact_order GROUP BY channel",
        expected_columns=[ExpectedColumn(name="channel"), ExpectedColumn(name="gmv")],
    )
    verification = cast(
        VerificationTrace,
        SimpleNamespace(result=SimpleNamespace(status="PASSED")),
    )

    owner, _, divergence, milestones = _forensic_ownership(
        case=case,
        scenario="OUTPUT_SHAPE",
        requirement=requirement,
        plan=plan,
        execution_columns=("channel", "gmv"),
        verification=verification,
        oracle_passed=False,
    )

    assert owner == "ORACLE_SPEC_DEFECT_REQUIRING_HUMAN_REVIEW"
    assert divergence == "RequirementState"
    assert milestones == ("M8",)


def test_frozen_diagnosis_evidence_is_strict_and_exact() -> None:
    report = BehavioralDiagnosisReport.model_validate_json(
        DIAGNOSIS_JSON_PATH.read_text(encoding="utf-8")
    )

    assert report.fingerprint == (
        "1070e9346cdb441eb083299363d818e39cdde598815906e38437d1300b4ebc78"
    )
    assert report.m8_replay.classification_counts == {"STANDALONE_M8_ALSO_CLARIFIES": 35}
    assert report.m8_replay.blocker_field_distribution == {
        "dimension": 1,
        "grain": 8,
        "metric": 6,
        "time_range": 22,
    }
    turns = [turn for case in report.m8_replay.cases for turn in case.turns]
    assert len(turns) == 36
    assert all(turn.expected_action == "READY" for turn in turns)
    assert all(turn.original_stored_e2e_action == "ASK_CLARIFICATION" for turn in turns)
    assert all(turn.standalone_m8_action == "ASK_CLARIFICATION" for turn in turns)
    assert all(turn.structured_model_call_outcome.status == "SUCCEEDED" for turn in turns)
    assert all(turn.structured_dialogue_proposal is not None for turn in turns)
    assert all(turn.normalized_dialogue_decision is not None for turn in turns)
    assert all(turn.requirement_patch is not None for turn in turns)
    assert all(turn.merged_requirement_state is not None for turn in turns)
    assert all(turn.blockers for turn in turns)
    assert all(item.replay_reproduced_source_shape for item in report.false_accept_forensics)
    assert all(item.requirement_state is not None for item in report.false_accept_forensics)
    assert all(item.planner_context is not None for item in report.false_accept_forensics)
    assert all(item.query_plan is not None for item in report.false_accept_forensics)
    assert all(item.sql is not None for item in report.false_accept_forensics)
    assert all(item.execution_result is not None for item in report.false_accept_forensics)
    assert all(item.verification_trace is not None for item in report.false_accept_forensics)
    assert sum(item.ownership == "BOTH_M9_AND_M12" for item in report.false_accept_forensics) == 4
    assert (
        sum(
            item.ownership == "ORACLE_SPEC_DEFECT_REQUIRING_HUMAN_REVIEW"
            for item in report.false_accept_forensics
        )
        == 2
    )
    assert {item.case_id for item in report.false_accept_forensics} == set(_FALSE_ACCEPT_SCENARIOS)
