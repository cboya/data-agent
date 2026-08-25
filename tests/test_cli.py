import pytest

import data_agent.cli
from data_agent.cli import main
from data_agent.dialogue.evaluation import (
    DialogueEvalIdentity,
    DialogueEvalMetrics,
    DialogueEvalReport,
)
from data_agent.planning.evaluation import (
    PlannerEvalIdentity,
    PlannerEvalMetrics,
    PlannerEvalReport,
)
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


def _passing_dialogue_report() -> DialogueEvalReport:
    return DialogueEvalReport(
        identity=DialogueEvalIdentity(
            suite_version="v0.1",
            prompt_version="dialogue-understanding-v0.20",
            provider="test",
            model="chat",
            model_digest="digest",
            model_fingerprint="a" * 64,
            runtime_version="test-runtime",
        ),
        metrics=DialogueEvalMetrics(
            case_count=1,
            turn_count=1,
            action_accuracy=1.0,
            state_accuracy=1.0,
            required_clarification_recall=1.0,
            unnecessary_clarification_rate=0.0,
            explicit_clear_accuracy=1.0,
            correction_accuracy=1.0,
            multi_turn_convergence=1.0,
            mean_turns_to_ready=1.0,
        ),
        cases=(),
        passed=True,
    )


def _passing_planner_report() -> PlannerEvalReport:
    return PlannerEvalReport(
        identity=PlannerEvalIdentity(
            suite_version="v0.1",
            prompt_version="query-planning-v0.3",
            provider="test",
            model="chat",
            model_digest="digest",
            model_fingerprint="a" * 64,
            runtime_version="test-runtime",
            retrieval_index_fingerprint="b" * 64,
            catalog_fingerprint="c" * 64,
            generated_schema_fingerprint="d" * 64,
            semantic_revision="e" * 64,
        ),
        metrics=PlannerEvalMetrics(
            case_count=20,
            structured_plan_parse_rate=1.0,
            allowed_table_compliance=1.0,
            out_of_context_declared_table_rejection=1.0,
            required_table_recall=1.0,
            plan_table_precision=1.0,
            exact_required_table_set_accuracy=1.0,
            expected_column_accuracy=1.0,
            representative_sql_generation_rate=1.0,
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

    async def evaluate_dialogue(_: object) -> DialogueEvalReport:
        return _passing_dialogue_report()

    async def evaluate_planner(_: object) -> PlannerEvalReport:
        return _passing_planner_report()

    monkeypatch.setattr(data_agent.cli, "evaluate_current_retrieval", evaluate)
    monkeypatch.setattr(data_agent.cli, "evaluate_current_dialogue", evaluate_dialogue)
    monkeypatch.setattr(data_agent.cli, "evaluate_current_planner", evaluate_planner)

    assert main(["eval"]) == 0

    output = capsys.readouterr().out
    assert "Retrieval eval PASS" in output
    assert "final_recall@5=1.000" in output
    assert "Dialogue eval PASS" in output
    assert "unnecessary_clarification=0.000" in output
    assert "Planner eval PASS" in output
    assert "table_precision=1.000" in output


def test_planner_eval_command_is_independent(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def evaluate_planner(_: object) -> PlannerEvalReport:
        return _passing_planner_report()

    monkeypatch.setattr(data_agent.cli, "evaluate_current_planner", evaluate_planner)

    assert main(["planner-eval"]) == 0
    output = capsys.readouterr().out
    assert "Planner eval PASS" in output
    assert "cases=20" in output
