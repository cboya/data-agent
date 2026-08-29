"""Canonical task-eval composition and consolidated report writer."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, cast

from fastapi.testclient import TestClient

from data_agent.answer.evaluation import evaluate_current_answer, format_answer_eval_summary
from data_agent.api import create_app
from data_agent.config import Settings
from data_agent.dialogue.evaluation import format_dialogue_eval_summary
from data_agent.dialogue.runtime import evaluate_current_dialogue
from data_agent.model_runtime.ports import ModelRuntimeDiagnostics
from data_agent.planning.evaluation import format_planner_eval_summary
from data_agent.planning.runtime import evaluate_current_planner
from data_agent.query_runtime.evaluation import format_runtime_eval_summary
from data_agent.query_runtime.runtime import evaluate_current_runtime
from data_agent.repair.evaluation import evaluate_current_repair, format_repair_eval_summary
from data_agent.retrieval.evaluation import format_retrieval_eval_summary
from data_agent.retrieval.index import load_retrieval_index
from data_agent.retrieval.runtime import (
    evaluate_current_retrieval,
    load_current_catalog_authority,
)
from data_agent.sql_guard.evaluation import format_sql_guard_eval_summary
from data_agent.sql_guard.runtime import evaluate_current_sql_guard
from data_agent.verification.evaluation import (
    evaluate_current_verification,
    format_verification_eval_summary,
)
from eval_harness.environment import build_environment, require_clean_git_commit
from eval_harness.golden import run_golden
from eval_harness.loader import REPOSITORY_ROOT, load_golden, load_oracles
from eval_harness.models import FinalAcceptanceReport

REPORT_PATH = REPOSITORY_ROOT / "evals" / "reports" / "latest.json"


def _write_report(report: FinalAcceptanceReport, path: Path = REPORT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = (
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    )
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(serialized, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _stage_reports(settings: Settings) -> tuple[dict[str, dict[str, Any]], bool]:
    retrieval = asyncio.run(evaluate_current_retrieval(settings))
    dialogue = asyncio.run(evaluate_current_dialogue(settings))
    planner = asyncio.run(evaluate_current_planner(settings))
    guard = evaluate_current_sql_guard(settings)
    runtime = evaluate_current_runtime(settings)
    verification = evaluate_current_verification()
    repair = evaluate_current_repair(settings.max_sql_repair_attempts)
    answer = evaluate_current_answer()
    reports = {
        "retrieval": retrieval.model_dump(mode="json"),
        "dialogue": dialogue.model_dump(mode="json"),
        "planning": planner.model_dump(mode="json"),
        "sql_guard": guard.model_dump(mode="json"),
        "runtime": runtime.model_dump(mode="json"),
        "verification": verification.model_dump(mode="json"),
        "repair": repair.model_dump(mode="json"),
        "answer": answer.model_dump(mode="json"),
    }
    for summary in (
        format_retrieval_eval_summary(retrieval),
        format_dialogue_eval_summary(dialogue),
        format_planner_eval_summary(planner),
        format_sql_guard_eval_summary(guard),
        format_runtime_eval_summary(runtime),
        format_verification_eval_summary(verification),
        format_repair_eval_summary(repair),
        format_answer_eval_summary(answer),
    ):
        print(summary)
    return reports, all(
        report.passed
        for report in (retrieval, dialogue, planner, guard, runtime, verification, repair, answer)
    )


def run_final_acceptance(settings: Settings) -> FinalAcceptanceReport:
    require_clean_git_commit()
    suite, golden_fingerprint = load_golden()
    oracles = load_oracles(suite)
    stages, stages_passed = _stage_reports(settings)
    app = create_app(settings)
    with TestClient(app) as client:
        diagnostics = cast(ModelRuntimeDiagnostics, app.state.model_runtime_diagnostics)
        authority = load_current_catalog_authority()
        index = load_retrieval_index(
            catalog=authority.assembled,
            current_generated_schema_fingerprint=authority.generated.fingerprint,
            current_semantic_revision=authority.curated.semantic_revision,
            embedding_fingerprint=diagnostics.embedding,
            model_runtime_version=diagnostics.runtime_version,
        )
        environment = build_environment(
            golden_version=suite.version,
            golden_fingerprint=golden_fingerprint,
            authority=authority,
            index=index,
            diagnostics=diagnostics,
            settings=settings,
        )
        golden = run_golden(
            client=client,
            settings=settings,
            suite=suite,
            oracles=oracles,
            environment=environment,
        )
    report = FinalAcceptanceReport(
        environment=environment,
        stages=stages,
        golden=golden,
        passed=stages_passed and golden.passed,
    )
    _write_report(report)
    metrics = golden.metrics
    print(
        f"Golden E2E {'PASS' if golden.passed else 'FAIL'}: cases={metrics.case_count}, "
        f"e2e={metrics.e2e_pass_rate:.3f}, oracle={metrics.result_oracle_pass_rate:.3f}, "
        f"trace={metrics.trace_integrity_rate:.3f}, "
        f"unnecessary_clarification={metrics.unnecessary_clarification_rate:.3f}, "
        f"verified_oracle_mismatch={metrics.verified_oracle_mismatch_count}"
    )
    for case in golden.cases:
        if case.passed:
            continue
        print(
            f"Golden attribution {case.id}: stage={case.failure_stage}, "
            f"session={case.session_id}, runs={list(case.run_ids)}, "
            f"responses={list(case.response_types)}, "
            f"statuses={list(case.run_statuses)}, "
            f"error_codes={list(case.run_error_codes)}, repairs={case.repair_count}, "
            f"trace_event_ids={list(case.trace_event_ids)}, "
            f"failed_trace_events={list(case.failed_trace_events)}, errors={list(case.errors)}"
        )
    print(
        f"MVP acceptance {'PASS' if report.passed else 'FAIL'}: "
        f"environment={environment.fingerprint}, report={REPORT_PATH.relative_to(REPOSITORY_ROOT)}"
    )
    return report


def main() -> int:
    settings = Settings()  # type: ignore[call-arg]
    report = run_final_acceptance(settings)
    return 0 if report.passed else 1
