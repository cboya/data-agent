"""Stable developer command entry points."""

import argparse
from collections.abc import Sequence

from data_agent.config import Settings
from data_agent.infrastructure.mysql_world import bootstrap_mysql, reset_mysql


def _milestone_stub(command: str, milestone: str) -> int:
    print(f"{command} is reserved for {milestone}; implementation has not reached that milestone.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="data-agent")
    parser.add_argument("command", choices=("bootstrap", "eval", "reset"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "bootstrap":
        settings = Settings()  # type: ignore[call-arg]
        summary = bootstrap_mysql(settings)
        print(
            "MySQL test world ready: "
            f"tables={summary.table_count}, orders={summary.order_count}, "
            f"paid_amount={summary.paid_amount_total}, "
            f"successful_refunds={summary.successful_refund_total}"
        )
        return 0
    if args.command == "reset":
        reset_mysql()
        print("MySQL generated state removed; curated catalog files were preserved.")
        return 0
    return _milestone_stub(args.command, "M15")


if __name__ == "__main__":
    raise SystemExit(main())
