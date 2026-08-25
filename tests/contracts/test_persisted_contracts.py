from datetime import UTC, datetime, timedelta

import pytest
from pydantic import BaseModel, ValidationError

from data_agent.contracts import (
    Ambiguity,
    Artifact,
    ArtifactType,
    Cardinality,
    CatalogColumn,
    CatalogDocument,
    CheckResult,
    DialogueAction,
    DialogueDecision,
    DimensionRequirement,
    ExecutionResult,
    ExpectedColumn,
    ExplainResult,
    ExplainTableAccess,
    FilterRequirement,
    GuardStatus,
    Message,
    MessageRole,
    MetricRequirement,
    QueryPlan,
    Relationship,
    RequirementPatch,
    RequirementState,
    RequirementStatus,
    ResolutionStatus,
    RetrievalHit,
    RetrievalResult,
    Run,
    RunStatus,
    Session,
    SessionStatus,
    SQLGuardResult,
    TimeRange,
    VerificationResult,
)

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


def _requirement() -> RequirementState:
    return RequirementState(
        version="v0.1",
        goal="Summarize paid amount for the last 30 days",
        metrics=[
            MetricRequirement(
                term="实付金额",
                resolved_name="paid_amount",
                status=ResolutionStatus.CONFIRMED,
            )
        ],
        dimensions=[
            DimensionRequirement(
                term="地区",
                resolved_name="region_name",
                status=ResolutionStatus.CONFIRMED,
            )
        ],
        filters=[
            FilterRequirement(
                field_term="订单状态",
                operator="IN",
                value=["PAID", "COMPLETED"],
            )
        ],
        time_range=TimeRange(kind="RELATIVE", value="last 30 days"),
        unresolved=[
            Ambiguity(
                field="display_format",
                reason="Presentation does not affect query semantics",
                blocking=False,
            )
        ],
        status=RequirementStatus.READY,
    )


def _relationship() -> Relationship:
    return Relationship(
        version="v0.1",
        from_table="fact_order",
        from_column="user_id",
        to_table="dim_user",
        to_column="id",
        cardinality=Cardinality.MANY_TO_ONE,
        description="Each order belongs to one user",
        curated=True,
    )


@pytest.mark.parametrize(
    "contract",
    [
        Session(
            id="session-1",
            status=SessionStatus.ACTIVE,
            requirement=_requirement(),
            created_at=NOW,
            updated_at=NOW,
        ),
        Message(
            id="message-1",
            session_id="session-1",
            role=MessageRole.USER,
            content="最近 30 天的实付金额",
            created_at=NOW,
        ),
        _requirement(),
        RequirementPatch(
            version="v0.2",
            metrics_upsert=_requirement().metrics,
            unresolved_replace=[],
        ),
        DialogueDecision.model_validate(
            {
                "version": "v0.1",
                "patch": RequirementPatch(version="v0.2", unresolved_replace=[]).model_dump(
                    mode="json"
                ),
                "action": DialogueAction.READY,
                "question": None,
                "reason": "All blocking requirements are resolved",
            }
        ),
        CatalogDocument(
            version="v0.1",
            table="fact_order",
            description="Order-level facts",
            columns=[CatalogColumn(name="paid_amount", data_type="decimal(12,2)")],
            generated_metadata_fingerprint="schema-sha256",
            semantic_revision="semantic-v1",
        ),
        _relationship(),
        RetrievalResult(
            version="v0.1",
            query="最近 30 天实付金额",
            hits=[
                RetrievalHit(
                    table="fact_order",
                    semantic_rank=1,
                    fused_score=1.0,
                    source="SEED",
                )
            ],
            relationships=[_relationship()],
            index_fingerprint="index-sha256",
        ),
        QueryPlan(
            version="v0.1",
            intent="Sum paid amount",
            tables=["fact_order"],
            sql="SELECT SUM(paid_amount) AS paid_amount FROM fact_order",
            expected_columns=[ExpectedColumn(name="paid_amount", semantic_role="metric")],
        ),
        SQLGuardResult(
            status=GuardStatus.PASSED,
            referenced_tables=["fact_order"],
            violations=[],
        ),
        ExplainResult(
            accepted=True,
            accesses=[ExplainTableAccess(table="fact_order", access_type="ALL")],
        ),
        ExecutionResult(
            version="v0.1",
            columns=["paid_amount"],
            rows=[["1545.00"]],
            returned_row_count=1,
            duration_ms=4,
            truncated=False,
        ),
        VerificationResult(
            version="v0.1",
            status="PASSED",
            checks=[CheckResult(name="expected_columns", category="STRUCTURAL", passed=True)],
        ),
        Artifact(
            id="artifact-1",
            session_id="session-1",
            run_id="run-1",
            type=ArtifactType.REQUIREMENT_STATE,
            contract_version="v0.1",
            payload={"status": "INCOMPLETE"},
            created_at=NOW,
        ),
        Run(
            id="run-1",
            session_id="session-1",
            status=RunStatus.RECEIVED,
            started_at=NOW,
        ),
    ],
)
def test_core_contract_json_round_trip(contract: BaseModel) -> None:
    restored = type(contract).model_validate_json(contract.model_dump_json())
    assert restored == contract


def test_persisted_timestamps_must_be_timezone_aware() -> None:
    with pytest.raises(ValidationError):
        Message(
            id="message-1",
            session_id="session-1",
            role=MessageRole.USER,
            content="hello",
            created_at=datetime(2026, 8, 23, 12, 0),
        )


def test_session_and_run_reject_reversed_timestamps() -> None:
    with pytest.raises(ValidationError, match="updated_at"):
        Session(
            id="session-1",
            status=SessionStatus.ACTIVE,
            requirement=_requirement(),
            created_at=NOW,
            updated_at=NOW - timedelta(seconds=1),
        )

    with pytest.raises(ValidationError, match="completed_at"):
        Run(
            id="run-1",
            session_id="session-1",
            status=RunStatus.FAILED,
            started_at=NOW,
            completed_at=NOW - timedelta(seconds=1),
        )
