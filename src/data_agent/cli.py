"""Stable developer command entry points."""

import argparse
import asyncio
from collections.abc import Sequence

from data_agent.config import Settings
from data_agent.dialogue.evaluation import format_dialogue_eval_summary
from data_agent.dialogue.runtime import evaluate_current_dialogue
from data_agent.infrastructure.mysql_world import bootstrap_mysql, reset_mysql
from data_agent.planning.evaluation import format_planner_eval_summary
from data_agent.planning.runtime import evaluate_current_planner
from data_agent.query_runtime.evaluation import format_runtime_eval_summary
from data_agent.query_runtime.runtime import evaluate_current_runtime
from data_agent.repair.evaluation import evaluate_current_repair, format_repair_eval_summary
from data_agent.repair.real_evaluation import (
    evaluate_real_repair,
    format_real_repair_summary,
    write_real_repair_report,
)
from data_agent.retrieval.evaluation import format_retrieval_eval_summary
from data_agent.retrieval.runtime import (
    evaluate_current_retrieval,
    rebuild_current_retrieval_index,
)
from data_agent.sql_guard.evaluation import format_sql_guard_eval_summary
from data_agent.sql_guard.runtime import evaluate_current_sql_guard
from data_agent.verification.evaluation import (
    evaluate_current_verification,
    format_verification_eval_summary,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="data-agent")
    parser.add_argument(
        "command",
        choices=(
            "bootstrap",
            "eval",
            "planner-eval",
            "repair-eval",
            "repair-ollama-eval",
            "reset",
            "runtime-eval",
            "sql-guard-eval",
            "verification-eval",
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "bootstrap":
        settings = Settings()  # type: ignore[call-arg]
        summary = bootstrap_mysql(settings)
        index = asyncio.run(rebuild_current_retrieval_index(settings))
        print(
            "MySQL test world ready: "
            f"tables={summary.table_count}, orders={summary.order_count}, "
            f"paid_amount={summary.paid_amount_total}, "
            f"successful_refunds={summary.successful_refund_total}, "
            f"retrieval_index={index.fingerprint}"
        )
        return 0
    if args.command == "eval":
        settings = Settings()  # type: ignore[call-arg]
        retrieval_report = asyncio.run(evaluate_current_retrieval(settings))
        dialogue_report = asyncio.run(evaluate_current_dialogue(settings))
        planner_report = asyncio.run(evaluate_current_planner(settings))
        sql_guard_report = evaluate_current_sql_guard(settings)
        runtime_report = evaluate_current_runtime(settings)
        verification_report = evaluate_current_verification()
        repair_report = evaluate_current_repair(settings.max_sql_repair_attempts)
        print(format_retrieval_eval_summary(retrieval_report))
        print(format_dialogue_eval_summary(dialogue_report))
        print(format_planner_eval_summary(planner_report))
        print(format_sql_guard_eval_summary(sql_guard_report))
        print(format_runtime_eval_summary(runtime_report))
        print(format_verification_eval_summary(verification_report))
        print(format_repair_eval_summary(repair_report))
        return (
            0
            if retrieval_report.passed
            and dialogue_report.passed
            and planner_report.passed
            and sql_guard_report.passed
            and runtime_report.passed
            and verification_report.passed
            and repair_report.passed
            else 1
        )
    if args.command == "planner-eval":
        settings = Settings()  # type: ignore[call-arg]
        planner_report = asyncio.run(evaluate_current_planner(settings))
        print(format_planner_eval_summary(planner_report))
        return 0 if planner_report.passed else 1
    if args.command == "sql-guard-eval":
        settings = Settings()  # type: ignore[call-arg]
        sql_guard_report = evaluate_current_sql_guard(settings)
        print(format_sql_guard_eval_summary(sql_guard_report))
        return 0 if sql_guard_report.passed else 1
    if args.command == "runtime-eval":
        settings = Settings()  # type: ignore[call-arg]
        runtime_report = evaluate_current_runtime(settings)
        print(format_runtime_eval_summary(runtime_report))
        return 0 if runtime_report.passed else 1
    if args.command == "verification-eval":
        verification_report = evaluate_current_verification()
        print(format_verification_eval_summary(verification_report))
        return 0 if verification_report.passed else 1
    if args.command == "repair-eval":
        settings = Settings()  # type: ignore[call-arg]
        repair_report = evaluate_current_repair(settings.max_sql_repair_attempts)
        print(format_repair_eval_summary(repair_report))
        return 0 if repair_report.passed else 1
    if args.command == "repair-ollama-eval":
        settings = Settings()  # type: ignore[call-arg]
        real_repair_report = asyncio.run(evaluate_real_repair(settings))
        write_real_repair_report(real_repair_report)
        print(format_real_repair_summary(real_repair_report))
        return 0 if real_repair_report.passed else 1
    if args.command == "reset":
        reset_mysql()
        print("MySQL generated state removed; curated catalog files were preserved.")
        return 0
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
