import pytest

import data_agent.cli
from data_agent.cli import main
from data_agent.retrieval.evaluation import RetrievalEvalMetrics, RetrievalEvalReport


def _passing_report() -> RetrievalEvalReport:
    return RetrievalEvalReport(
        index_fingerprint="a" * 64,
        index_identity={"runtime": "test"},
        metrics=RetrievalEvalMetrics(
            case_count=1,
            seed_recall_at_5=1.0,
            seed_recall_at_10=1.0,
            final_recall_at_5=1.0,
            final_recall_at_10=1.0,
            final_precision_at_5=1.0,
            mean_final_table_count=1.0,
            relationship_path_recovery=1.0,
            relationship_path_case_count=0,
        ),
        cases=(),
        passed=True,
    )


def test_eval_runs_standalone_retrieval_gate(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def evaluate(_: object) -> RetrievalEvalReport:
        return _passing_report()

    monkeypatch.setattr(data_agent.cli, "evaluate_current_retrieval", evaluate)

    assert main(["eval"]) == 0

    output = capsys.readouterr().out
    assert "Retrieval eval PASS" in output
    assert "final_recall@5=1.000" in output
