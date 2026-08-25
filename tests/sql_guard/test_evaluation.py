"""Standalone M10 corpus and accepted M9 snapshot evidence."""

import json
from pathlib import Path

import pytest

from data_agent.sql_guard import ExplainPolicy, SQLAdmissionService, SQLGuard
from data_agent.sql_guard.errors import SQLGuardEvaluationError
from data_agent.sql_guard.evaluation import (
    load_m9_proposal_snapshot,
    load_sql_guard_eval_suite,
    run_sql_guard_evaluation,
)
from data_agent.sql_guard.explain import (
    DEFAULT_MAX_EXPLAIN_CHARACTERS,
    DEFAULT_MAX_EXPLAIN_NODES,
    EXPLAIN_POLICY_VERSION,
)
from data_agent.sql_guard.guard import SQL_GUARD_POLICY_VERSION
from tests.sql_guard.test_admission import RecordingProvider, explain_json


def test_frozen_security_and_m9_proposal_corpora_pass() -> None:
    suite = load_sql_guard_eval_suite()
    snapshot, fingerprint = load_m9_proposal_snapshot()
    admission = SQLAdmissionService(
        guard=SQLGuard(analytics_schema="data_agent"),
        explain_provider=RecordingProvider(explain_json()),
        explain_policy=ExplainPolicy(max_estimated_rows_per_access=100_000),
    )

    report = run_sql_guard_evaluation(
        admission,
        suite=suite,
        snapshot=snapshot,
        snapshot_fingerprint=fingerprint,
        analytics_schema="data_agent",
        max_sql_characters=64_000,
        max_explain_estimated_rows=100_000,
        max_explain_characters=DEFAULT_MAX_EXPLAIN_CHARACTERS,
        max_explain_nodes=DEFAULT_MAX_EXPLAIN_NODES,
        sql_guard_policy_version=SQL_GUARD_POLICY_VERSION,
        explain_policy_version=EXPLAIN_POLICY_VERSION,
    )

    assert report.passed is True
    assert report.metrics.security_case_count == 38
    assert report.metrics.security_guard_accuracy == 1.0
    assert report.metrics.security_explain_accuracy == 1.0
    assert report.metrics.proposal_case_count == 21
    assert report.metrics.proposal_sql_parse_rate == 1.0
    assert report.metrics.proposal_guard_pass_rate == 1.0
    assert report.metrics.proposal_table_scope_compliance == 1.0
    assert report.metrics.proposal_explain_admission_rate == 1.0
    assert report.epistemic_boundary.startswith("guard-and-explain-only")
    assert report.identity.sql_guard_policy_version == SQL_GUARD_POLICY_VERSION
    assert report.identity.explain_policy_version == EXPLAIN_POLICY_VERSION


def test_duplicate_yaml_keys_fail_closed(tmp_path: Path) -> None:
    suite = tmp_path / "duplicate.yaml"
    suite.write_text("version: v0.1\nversion: v0.1\ncases: []\n", encoding="utf-8")

    with pytest.raises(SQLGuardEvaluationError, match="missing or invalid"):
        load_sql_guard_eval_suite(suite)


def test_tampered_snapshot_fails_closed(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "version": "v0.1",
                "source": {},
                "cases": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SQLGuardEvaluationError, match="missing or invalid"):
        load_m9_proposal_snapshot(snapshot_path)
