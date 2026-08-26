"""Golden truth and Oracles must never become runtime model context or authority."""

from pathlib import Path

from eval_harness.loader import load_golden, load_oracles

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_FINGERPRINT = "53d969d1196877829cc89ee3070d75a1fea6ba88bfd5986fbe66beb21fcf93f7"


def test_golden_dataset_has_frozen_scale_coverage_and_oracle_identity() -> None:
    golden, fingerprint = load_golden()
    oracles = load_oracles(golden)

    assert len(golden.cases) == 59
    assert fingerprint == GOLDEN_FINGERPRINT
    assert len(oracles.queries) == 54


def test_runtime_and_model_prompts_cannot_import_acceptance_truth() -> None:
    forbidden = ("eval_harness", "evals/golden", "evals/oracles", "golden.yaml", "oracles.yaml")
    runtime_files = tuple((REPOSITORY_ROOT / "src" / "data_agent").rglob("*.py"))
    prompt_files = tuple((REPOSITORY_ROOT / "src" / "data_agent").rglob("prompt.py"))

    for path in (*runtime_files, *prompt_files):
        source = path.read_text(encoding="utf-8").lower()
        assert all(value not in source for value in forbidden), path
