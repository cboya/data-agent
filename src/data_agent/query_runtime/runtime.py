"""M11 runtime composition over the analytics read-only principal."""

from data_agent.config import Settings
from data_agent.query_runtime.evaluation import (
    RuntimeEvalReport,
    load_runtime_eval_suite,
    run_runtime_evaluation,
    write_runtime_eval_report,
)
from data_agent.query_runtime.mysql import MySQLQueryConnectionFactory
from data_agent.query_runtime.service import ReadOnlyQueryRuntime, RuntimeLimits


def build_readonly_query_runtime(settings: Settings) -> ReadOnlyQueryRuntime:
    return ReadOnlyQueryRuntime(
        connection_factory=MySQLQueryConnectionFactory(settings),
        limits=RuntimeLimits(
            max_execution_time_ms=settings.max_query_time_ms,
            max_result_rows=settings.max_result_rows,
            max_result_bytes=settings.max_result_bytes,
        ),
    )


def evaluate_current_runtime(settings: Settings) -> RuntimeEvalReport:
    suite, suite_fingerprint = load_runtime_eval_suite()
    report = run_runtime_evaluation(
        settings,
        suite=suite,
        suite_fingerprint=suite_fingerprint,
    )
    write_runtime_eval_report(report)
    return report
