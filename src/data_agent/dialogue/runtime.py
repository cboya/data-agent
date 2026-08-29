"""Composition helpers for the current configured dialogue runtime and eval."""

from data_agent.config import Settings
from data_agent.dialogue.evaluation import (
    DialogueEvalReport,
    load_dialogue_eval_suite,
    run_dialogue_evaluation,
    write_dialogue_eval_report,
)
from data_agent.dialogue.service import DialogueEngine
from data_agent.model_runtime.composition import start_model_runtime


async def evaluate_current_dialogue(settings: Settings) -> DialogueEvalReport:
    runtime = await start_model_runtime(settings)
    diagnostics = runtime.diagnostics
    engine = DialogueEngine(chat_model=runtime.chat_model)
    report = await run_dialogue_evaluation(
        engine,
        suite=load_dialogue_eval_suite(),
        chat_fingerprint=diagnostics.chat,
        runtime_version=diagnostics.runtime_version,
    )
    write_dialogue_eval_report(report)
    return report
