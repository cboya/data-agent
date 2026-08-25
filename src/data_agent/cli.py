"""Stable developer command entry points."""

import argparse
import asyncio
from collections.abc import Sequence

from data_agent.config import Settings
from data_agent.infrastructure.mysql_world import bootstrap_mysql, reset_mysql
from data_agent.retrieval.evaluation import format_retrieval_eval_summary
from data_agent.retrieval.runtime import (
    evaluate_current_retrieval,
    rebuild_current_retrieval_index,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="data-agent")
    parser.add_argument("command", choices=("bootstrap", "eval", "reset"))
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
        report = asyncio.run(evaluate_current_retrieval(settings))
        print(format_retrieval_eval_summary(report))
        return 0 if report.passed else 1
    if args.command == "reset":
        reset_mysql()
        print("MySQL generated state removed; curated catalog files were preserved.")
        return 0
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
