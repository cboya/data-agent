"""Frozen deterministic M13 evaluation gate."""

import json
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from data_agent.repair.evaluation import (
    RepairEvaluationError,
    load_repair_eval_suite,
    run_repair_evaluation,
    write_repair_eval_report,
)


def test_frozen_repair_eval_passes_every_safety_metric(tmp_path: Path) -> None:
    suite, fingerprint = load_repair_eval_suite()

    report = run_repair_evaluation(
        suite=suite,
        suite_fingerprint=fingerprint,
        max_attempts=1,
    )
    output = write_repair_eval_report(report, output_path=tmp_path / "repair.json")
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert report.passed is True
    assert report.metrics.eligibility_classification_accuracy == 1.0
    assert report.metrics.policy_integrity_no_model_call_accuracy == 1.0
    assert report.metrics.repair_bound_enforcement == 1.0
    assert report.metrics.concurrent_claim_bound_enforcement == 1.0
    assert payload["identity"]["suite_fingerprint"] == fingerprint
    assert payload["epistemic_boundary"].startswith("typed-eligibility")
    assert all(len(case.failure_fingerprint) == 64 for case in report.cases)


def test_duplicate_eval_yaml_key_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.yaml"
    path.write_text("version: v0.1\nversion: v0.1\ncases: []\n", encoding="utf-8")

    with pytest.raises(RepairEvaluationError) as captured:
        load_repair_eval_suite(path)

    assert isinstance(captured.value.__cause__, yaml.YAMLError)
