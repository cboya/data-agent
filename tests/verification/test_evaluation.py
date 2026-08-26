"""Frozen M12 suite and deterministic report tests."""

from pathlib import Path

import pytest

from data_agent.catalog.semantic import load_assembled_catalog
from data_agent.verification.evaluation import (
    VerificationEvaluationError,
    load_verification_eval_suite,
    run_verification_evaluation,
)


def test_frozen_verification_suite_covers_every_decision_class() -> None:
    suite, fingerprint = load_verification_eval_suite()

    assert len(suite.cases) == 15
    assert {case.expected for case in suite.cases} == {
        "PASS",
        "STRUCTURAL_FAILURE",
        "SEMANTIC_FAILURE",
        "EMPIRICAL_FAILURE",
        "INTEGRITY_ERROR",
    }
    assert len(fingerprint) == 64


def test_verification_evaluation_meets_all_decision_gates() -> None:
    suite, fingerprint = load_verification_eval_suite()

    report = run_verification_evaluation(
        suite=suite,
        suite_fingerprint=fingerprint,
        catalog=load_assembled_catalog(),
    )

    assert report.passed
    assert report.metrics.structural_decision_accuracy == 1.0
    assert report.metrics.semantic_decision_accuracy == 1.0
    assert report.metrics.empirical_decision_accuracy == 1.0
    assert report.metrics.false_accept_rate == 0.0
    assert report.metrics.false_reject_rate == 0.0
    assert report.metrics.identity_mismatch_rejection == 1.0
    assert report.metrics.planner_context_substitution_rejection == 1.0
    assert report.metrics.truncation_rejection == 1.0
    assert 0.0 < report.metrics.verification_coverage < 1.0


def test_verification_suite_duplicate_yaml_key_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "verification.yaml"
    path.write_text("version: v0.1\nversion: v0.1\ncases: []\n", encoding="utf-8")

    with pytest.raises(VerificationEvaluationError, match="missing or invalid"):
        load_verification_eval_suite(path)
