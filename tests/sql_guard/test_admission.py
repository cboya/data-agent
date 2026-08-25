"""Capability issuance and deterministic EXPLAIN admission invariants."""

import json
from typing import cast

import pytest

from data_agent.contracts.execution import ExplainResult, GuardStatus, SQLGuardResult
from data_agent.sql_guard import (
    ExplainPolicy,
    ExplainProviderError,
    GuardedSQL,
    PhysicalTable,
    SQLAdmissionService,
    SQLGuard,
)
from tests.sql_guard.factories import query_plan


def explain_json(*, rows: int = 10, table: str = "fact_order") -> str:
    return json.dumps(
        {
            "query_block": {
                "select_id": 1,
                "table": {
                    "table_name": table,
                    "access_type": "ALL",
                    "rows_examined_per_scan": rows,
                },
            }
        }
    )


class RecordingProvider:
    def __init__(self, result: str) -> None:
        self.result = result
        self.candidates: list[GuardedSQL] = []

    def explain(self, candidate: GuardedSQL) -> str:
        self.candidates.append(candidate)
        return self.result


class FailingProvider:
    def explain(self, candidate: GuardedSQL) -> str:
        raise ExplainProviderError("redacted provider failure")


def service(provider: RecordingProvider | FailingProvider) -> SQLAdmissionService:
    return SQLAdmissionService(
        guard=SQLGuard(analytics_schema="data_agent"),
        explain_provider=provider,
        explain_policy=ExplainPolicy(max_estimated_rows_per_access=100),
    )


def test_guard_rejection_prevents_explain() -> None:
    provider = RecordingProvider(explain_json())

    outcome = service(provider).admit(query_plan("DELETE FROM fact_order"))

    assert outcome.guard.result.status is GuardStatus.REJECTED
    assert outcome.explain_result is None
    assert outcome.guarded_query is None
    assert provider.candidates == []


def test_passed_guard_and_explain_issue_exact_sql_capability() -> None:
    provider = RecordingProvider(explain_json())
    sql = " SELECT id FROM fact_order "

    outcome = service(provider).admit(query_plan(sql))

    assert outcome.guarded_query is not None
    assert outcome.guarded_query.sql == sql
    assert outcome.guarded_query.sql == provider.candidates[0].sql
    assert outcome.guarded_query.sql_digest == provider.candidates[0].sql_digest
    assert outcome.guarded_query.explain_result.accepted is True


def test_capability_cannot_be_constructed_without_issuer_token() -> None:
    with pytest.raises(ValueError, match="only be issued"):
        GuardedSQL(
            sql="SELECT 1",
            sql_digest="invalid",
            query_plan_fingerprint="invalid",
            physical_tables=(),
            guard_result=SQLGuardResult(
                status=GuardStatus.PASSED,
                referenced_tables=[],
                violations=[],
            ),
            _token=object(),
        )


@pytest.mark.parametrize(
    ("raw_explain", "reason"),
    [
        ("not json", "INVALID_EXPLAIN_JSON"),
        ("[]", "INVALID_EXPLAIN_SHAPE"),
        (json.dumps({"query_block": {}}), "MISSING_TABLE_ACCESSES"),
        (
            json.dumps(
                {"query_block": {"table": {"table_name": "fact_order", "access_type": "ALL"}}}
            ),
            "MISSING_ROW_ESTIMATE",
        ),
        (explain_json(rows=101), "ROW_ESTIMATE_LIMIT_EXCEEDED"),
    ],
)
def test_explain_policy_fails_closed(raw_explain: str, reason: str) -> None:
    guard = SQLGuard(analytics_schema="data_agent").evaluate(query_plan("SELECT * FROM fact_order"))
    candidate = cast(GuardedSQL, guard.candidate)

    result = ExplainPolicy(max_estimated_rows_per_access=100).evaluate(candidate, raw_explain)

    assert result.accepted is False
    assert result.rejection_reason == reason


def test_provider_failure_is_fail_closed() -> None:
    outcome = service(FailingProvider()).admit(query_plan("SELECT * FROM fact_order"))

    assert outcome.guard.result.status is GuardStatus.PASSED
    assert outcome.explain_result == ExplainResult(
        accepted=False,
        accesses=[],
        rejection_reason="EXPLAIN_PROVIDER_FAILURE",
    )
    assert outcome.guarded_query is None


def test_constant_select_can_pass_without_table_accesses() -> None:
    provider = RecordingProvider(json.dumps({"query_block": {"select_id": 1}}))

    outcome = service(provider).admit(query_plan("SELECT 1"))

    assert outcome.guarded_query is not None
    assert outcome.guarded_query.physical_tables == ()


def test_explain_access_provenance_is_preserved() -> None:
    provider = RecordingProvider(explain_json(rows=99, table="orders_alias"))

    outcome = service(provider).admit(query_plan("SELECT * FROM fact_order AS orders_alias"))

    assert outcome.guarded_query is not None
    access = outcome.guarded_query.explain_result.accesses[0]
    assert access.table == "orders_alias"
    assert access.access_type == "ALL"
    assert access.estimated_rows == 99
    assert outcome.guarded_query.physical_tables == (PhysicalTable(None, "fact_order"),)


def test_explain_size_and_structure_are_bounded() -> None:
    candidate = cast(
        GuardedSQL,
        SQLGuard(analytics_schema="data_agent")
        .evaluate(query_plan("SELECT * FROM fact_order"))
        .candidate,
    )
    policy = ExplainPolicy(
        max_estimated_rows_per_access=100,
        max_explain_characters=10,
        max_explain_nodes=2,
    )

    oversized = policy.evaluate(candidate, explain_json())
    node_limited = ExplainPolicy(
        max_estimated_rows_per_access=100,
        max_explain_characters=10_000,
        max_explain_nodes=2,
    ).evaluate(candidate, explain_json())

    assert oversized.rejection_reason == "EXPLAIN_SIZE_LIMIT_EXCEEDED"
    assert node_limited.rejection_reason == "EXPLAIN_NODE_LIMIT_EXCEEDED"
