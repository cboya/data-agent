import asyncio
from pathlib import Path

from data_agent.contracts.dialogue import DialogueAction, DialogueDecision
from data_agent.contracts.requirement import (
    Ambiguity,
    MetricRequirement,
    PatchOp,
    RequirementPatch,
    ResolutionStatus,
    SetScalarPatch,
    TimeRange,
)
from data_agent.dialogue.evaluation import (
    DialogueEvalCase,
    DialogueEvalSuite,
    DialogueEvalTurn,
    DialogueStateExpectation,
    ExpectationOp,
    ScalarExpectation,
    load_dialogue_eval_suite,
    run_dialogue_evaluation,
    write_dialogue_eval_report,
)
from data_agent.dialogue.service import DialogueEngine
from data_agent.model_runtime.ports import ModelFingerprint
from tests.dialogue.factories import FixedDialogueModel


def _fingerprint() -> ModelFingerprint:
    return ModelFingerprint(
        provider="test",
        model="dialogue-double",
        digest="dialogue-digest",
        capabilities=("completion",),
    )


def test_frozen_dialogue_suite_covers_required_categories_and_multi_turns() -> None:
    suite = load_dialogue_eval_suite()

    assert len(suite.cases) == 25
    assert sum(len(case.turns) for case in suite.cases) == 30
    assert {case.category for case in suite.cases} == {
        "complete",
        "correction",
        "explicit_clear",
        "grain_ambiguity",
        "metric_ambiguity",
        "mixed_language",
        "multi_turn",
        "non_blocking",
        "time_ambiguity",
    }


def test_standalone_eval_reports_clarification_clear_and_correction_metrics(
    tmp_path: Path,
) -> None:
    ask = DialogueDecision.model_validate(
        {
            "version": "v0.1",
            "patch": RequirementPatch(
                version="v0.2",
                unresolved_replace=[Ambiguity(field="metric", reason="metric is blocking")],
            ).model_dump(mode="json"),
            "action": DialogueAction.ASK_CLARIFICATION,
            "question": "Which metric?",
            "reason": "metric ambiguity",
        }
    )
    ready = DialogueDecision.model_validate(
        {
            "version": "v0.1",
            "patch": RequirementPatch(
                version="v0.2",
                metrics_upsert=[
                    MetricRequirement(
                        term="订单量",
                        resolved_name="order_count",
                        status=ResolutionStatus.CONFIRMED,
                    )
                ],
                time_range=SetScalarPatch(
                    op=PatchOp.SET,
                    value=TimeRange(kind="RELATIVE", value="last_30_days"),
                ),
                grain=SetScalarPatch(op=PatchOp.SET, value="day"),
                unresolved_replace=[],
            ).model_dump(mode="json"),
            "action": DialogueAction.READY,
            "question": None,
            "reason": "complete requirement",
        }
    )
    suite = DialogueEvalSuite(
        version="v0.1",
        cases=(
            DialogueEvalCase(
                id="ask",
                category="metric_ambiguity",
                turns=(
                    DialogueEvalTurn(
                        user="sales",
                        expected_action=DialogueAction.ASK_CLARIFICATION,
                        expected_state=DialogueStateExpectation(
                            required_blocking_fields=("metric",)
                        ),
                    ),
                ),
            ),
            DialogueEvalCase(
                id="ready",
                category="complete",
                turns=(
                    DialogueEvalTurn(
                        user="last 30 days daily order count",
                        expected_action=DialogueAction.READY,
                        expected_state=DialogueStateExpectation(
                            metrics=("order_count",),
                            time_range_value=ScalarExpectation(
                                op=ExpectationOp.EQUALS,
                                value="last_30_days",
                            ),
                            grain=ScalarExpectation(
                                op=ExpectationOp.EQUALS,
                                value="day",
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )
    model = FixedDialogueModel(ask, ready)
    report = asyncio.run(
        run_dialogue_evaluation(
            DialogueEngine(chat_model=model),
            suite=suite,
            chat_fingerprint=_fingerprint(),
            runtime_version="test-runtime",
        )
    )
    output = tmp_path / "dialogue.json"
    write_dialogue_eval_report(report, output_path=output)

    assert report.metrics.action_accuracy == 1.0
    assert report.metrics.state_accuracy == 1.0
    assert report.metrics.required_clarification_recall == 1.0
    assert report.metrics.unnecessary_clarification_rate == 0.0
    assert report.passed is True
    assert output.is_file()
