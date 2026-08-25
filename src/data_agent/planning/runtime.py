"""Composition for the current bound Ollama planner and standalone evaluation."""

from __future__ import annotations

from dataclasses import dataclass

from data_agent.config import Settings
from data_agent.model_runtime.ollama import OllamaChatModel
from data_agent.planning.context import PlannerContextBuilder
from data_agent.planning.evaluation import (
    PlannerEvalReport,
    load_planner_eval_suite,
    run_planner_evaluation,
    write_planner_eval_report,
)
from data_agent.planning.service import QueryPlanner
from data_agent.retrieval.runtime import CurrentRetrievalRuntime, load_current_retrieval_runtime


@dataclass(frozen=True)
class CurrentPlannerRuntime:
    retrieval: CurrentRetrievalRuntime
    planner: QueryPlanner


async def load_current_planner_runtime(settings: Settings) -> CurrentPlannerRuntime:
    retrieval = await load_current_retrieval_runtime(settings)
    planner = QueryPlanner(
        chat_model=OllamaChatModel(settings, fingerprint=retrieval.diagnostics.chat),
        context_builder=PlannerContextBuilder(max_tables=settings.max_retrieved_tables),
        model_fingerprint=retrieval.diagnostics.chat.value,
        runtime_version=retrieval.diagnostics.runtime_version,
    )
    return CurrentPlannerRuntime(retrieval=retrieval, planner=planner)


async def evaluate_current_planner(settings: Settings) -> PlannerEvalReport:
    eval_settings = settings.model_copy(
        update={
            "ollama_request_timeout_seconds": settings.planner_eval_request_timeout_seconds,
        }
    )
    runtime = await load_current_planner_runtime(eval_settings)
    report = await run_planner_evaluation(
        runtime.planner,
        suite=load_planner_eval_suite(),
        catalog=runtime.retrieval.authority.assembled,
        retrieval_index_fingerprint=runtime.retrieval.index.fingerprint,
        chat_fingerprint=runtime.retrieval.diagnostics.chat,
        runtime_version=runtime.retrieval.diagnostics.runtime_version,
    )
    write_planner_eval_report(report)
    return report
