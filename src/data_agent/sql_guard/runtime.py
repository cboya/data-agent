"""Composition for the current deterministic M10 admission evaluation."""

from data_agent.config import Settings
from data_agent.sql_guard.evaluation import (
    SQLGuardEvalReport,
    load_m9_proposal_snapshot,
    load_sql_guard_eval_suite,
    run_sql_guard_evaluation,
    write_sql_guard_eval_report,
)
from data_agent.sql_guard.explain import (
    DEFAULT_MAX_EXPLAIN_CHARACTERS,
    DEFAULT_MAX_EXPLAIN_NODES,
    EXPLAIN_POLICY_VERSION,
    ExplainPolicy,
    MySQLExplainProvider,
)
from data_agent.sql_guard.guard import SQL_GUARD_POLICY_VERSION, SQLGuard
from data_agent.sql_guard.service import SQLAdmissionService


def evaluate_current_sql_guard(settings: Settings) -> SQLGuardEvalReport:
    snapshot, snapshot_fingerprint = load_m9_proposal_snapshot()
    admission = SQLAdmissionService(
        guard=SQLGuard(
            analytics_schema=settings.mysql_database,
            max_sql_characters=settings.max_sql_characters,
        ),
        explain_provider=MySQLExplainProvider(settings),
        explain_policy=ExplainPolicy(
            max_estimated_rows_per_access=settings.max_explain_estimated_rows
        ),
    )
    report = run_sql_guard_evaluation(
        admission,
        suite=load_sql_guard_eval_suite(),
        snapshot=snapshot,
        snapshot_fingerprint=snapshot_fingerprint,
        analytics_schema=settings.mysql_database,
        max_sql_characters=settings.max_sql_characters,
        max_explain_estimated_rows=settings.max_explain_estimated_rows,
        max_explain_characters=DEFAULT_MAX_EXPLAIN_CHARACTERS,
        max_explain_nodes=DEFAULT_MAX_EXPLAIN_NODES,
        sql_guard_policy_version=SQL_GUARD_POLICY_VERSION,
        explain_policy_version=EXPLAIN_POLICY_VERSION,
    )
    write_sql_guard_eval_report(report)
    return report
