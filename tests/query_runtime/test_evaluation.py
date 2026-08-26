"""Frozen M11 suite and report-boundary tests."""

from pathlib import Path

import pytest

from data_agent.query_runtime.evaluation import (
    RuntimeEvaluationError,
    load_runtime_eval_suite,
)


def test_frozen_runtime_suite_covers_all_execution_categories() -> None:
    suite, fingerprint = load_runtime_eval_suite()

    assert len(suite.cases) == 6
    assert {case.category for case in suite.cases} == {
        "success",
        "row_bound",
        "byte_bound",
        "timeout",
    }
    assert len(fingerprint) == 64


def test_runtime_suite_duplicate_yaml_key_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "runtime.yaml"
    path.write_text("version: v0.1\nversion: v0.1\ncases: []\n", encoding="utf-8")

    with pytest.raises(RuntimeEvaluationError, match="missing or invalid"):
        load_runtime_eval_suite(path)
