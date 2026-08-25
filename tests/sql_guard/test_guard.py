"""AST, scope, namespace, and QueryPlan authority invariants."""

import pytest

from data_agent.contracts.execution import GuardStatus
from data_agent.sql_guard import SQLGuard, SQLViolation
from tests.sql_guard.factories import query_plan


@pytest.fixture
def guard() -> SQLGuard:
    return SQLGuard(analytics_schema="data_agent")


@pytest.mark.parametrize(
    ("sql", "tables", "referenced"),
    [
        ("SELECT id FROM fact_order", ["fact_order"], ["fact_order"]),
        (
            "WITH paid AS (SELECT user_id FROM fact_order) SELECT paid.user_id FROM paid",
            ["fact_order"],
            ["fact_order"],
        ),
        (
            "SELECT nested.user_id FROM "
            "(SELECT user_id FROM fact_order WHERE user_id IN "
            "(SELECT id FROM dim_user)) AS nested",
            ["fact_order", "dim_user"],
            ["dim_user", "fact_order"],
        ),
        (
            "SELECT id FROM fact_order UNION ALL SELECT id FROM fact_refund",
            ["fact_order", "fact_refund"],
            ["fact_order", "fact_refund"],
        ),
        (
            "WITH fact_order AS (SELECT id FROM dim_user) SELECT id FROM fact_order",
            ["dim_user"],
            ["dim_user"],
        ),
        (
            "SELECT id FROM data_agent.fact_order",
            ["fact_order"],
            ["fact_order"],
        ),
        ("SELECT 1", ["fact_order"], []),
    ],
)
def test_scope_aware_physical_tables_pass(
    guard: SQLGuard,
    sql: str,
    tables: list[str],
    referenced: list[str],
) -> None:
    evaluation = guard.evaluate(query_plan(sql, tables=tables))

    assert evaluation.result.status is GuardStatus.PASSED
    assert evaluation.result.referenced_tables == referenced
    assert evaluation.table_scope_compliant is True
    assert evaluation.candidate is not None


def test_subset_authority_reports_unused_declared_tables(guard: SQLGuard) -> None:
    evaluation = guard.evaluate(
        query_plan("SELECT id FROM fact_order", tables=["fact_order", "dim_user"])
    )

    assert evaluation.result.status is GuardStatus.PASSED
    assert evaluation.unused_declared_tables == ("dim_user",)


def test_approved_analytics_function_surface_passes(guard: SQLGuard) -> None:
    evaluation = guard.evaluate(
        query_plan(
            "SELECT DATE(DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)) AS period, "
            "COUNT(id) AS order_count, "
            "CAST(COALESCE(SUM(CASE WHEN status = 'PAID' THEN paid_amount ELSE 0 END), 0) "
            "AS DECIMAL(18, 2)) AS paid_amount FROM fact_order"
        )
    )

    assert evaluation.result.status is GuardStatus.PASSED
    assert evaluation.candidate is not None


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM other.fact_order",
        "SELECT * FROM mysql.user",
        "SELECT * FROM information_schema.tables",
        "SELECT * FROM data_agent_control.agent_session",
        "SELECT * FROM catalog.data_agent.fact_order",
    ],
)
def test_non_analytics_namespaces_fail_closed(guard: SQLGuard, sql: str) -> None:
    evaluation = guard.evaluate(query_plan(sql))

    assert evaluation.result.status is GuardStatus.REJECTED
    assert evaluation.result.violations[0].startswith(SQLViolation.UNAUTHORIZED_SCHEMA)
    assert evaluation.table_scope_compliant is False


def test_sql_tables_must_be_subset_of_query_plan_tables(guard: SQLGuard) -> None:
    evaluation = guard.evaluate(
        query_plan(
            "SELECT * FROM fact_order JOIN dim_user ON dim_user.id = fact_order.user_id",
            tables=["fact_order"],
        )
    )

    assert evaluation.result.status is GuardStatus.REJECTED
    assert evaluation.result.violations == ["UNDECLARED_TABLE:dim_user"]
    assert evaluation.table_scope_compliant is False
    assert evaluation.candidate is None


@pytest.mark.parametrize(
    ("sql", "violation"),
    [
        ("SELECT 1; SELECT 2", SQLViolation.MULTIPLE_STATEMENTS),
        ("SELEC FROM", SQLViolation.SQL_PARSE_ERROR),
        ("INSERT INTO fact_order(id) VALUES (1)", SQLViolation.UNSUPPORTED_STATEMENT),
        ("UPDATE fact_order SET id = 1", SQLViolation.UNSUPPORTED_STATEMENT),
        ("DELETE FROM fact_order", SQLViolation.UNSUPPORTED_STATEMENT),
        ("REPLACE INTO fact_order(id) VALUES (1)", SQLViolation.UNSUPPORTED_STATEMENT),
        ("CREATE TABLE unsafe(id INT)", SQLViolation.UNSUPPORTED_STATEMENT),
        ("ALTER TABLE fact_order ADD COLUMN unsafe INT", SQLViolation.UNSUPPORTED_STATEMENT),
        ("DROP TABLE fact_order", SQLViolation.UNSUPPORTED_STATEMENT),
        ("TRUNCATE TABLE fact_order", SQLViolation.UNSUPPORTED_STATEMENT),
        (
            "GRANT SELECT ON data_agent.fact_order TO 'unsafe'@'%'",
            SQLViolation.UNSUPPORTED_STATEMENT,
        ),
        (
            "REVOKE SELECT ON data_agent.fact_order FROM 'unsafe'@'%'",
            SQLViolation.UNSUPPORTED_STATEMENT,
        ),
        (
            "LOAD DATA INFILE '/tmp/unsafe' INTO TABLE fact_order",
            SQLViolation.SQL_PARSE_ERROR,
        ),
        ("CALL unsafe()", SQLViolation.UNSUPPORTED_STATEMENT),
        ("SET @unsafe = 1", SQLViolation.UNSUPPORTED_STATEMENT),
        ("SHOW TABLES", SQLViolation.UNSUPPORTED_STATEMENT),
        ("DESCRIBE fact_order", SQLViolation.UNSUPPORTED_STATEMENT),
        ("EXPLAIN SELECT * FROM fact_order", SQLViolation.UNSUPPORTED_STATEMENT),
        ("TABLE fact_order", SQLViolation.UNSUPPORTED_STATEMENT),
        (
            "WITH RECURSIVE r AS (SELECT 1 UNION ALL SELECT * FROM r) SELECT * FROM r",
            SQLViolation.RECURSIVE_CTE,
        ),
        ("SELECT LOAD_FILE('/etc/passwd')", SQLViolation.DANGEROUS_FUNCTION),
        ("SELECT SLEEP(1)", SQLViolation.DANGEROUS_FUNCTION),
        ("SELECT BENCHMARK(1, MD5('x'))", SQLViolation.DANGEROUS_FUNCTION),
        ("SELECT GET_LOCK('unsafe', 1)", SQLViolation.DANGEROUS_FUNCTION),
        ("SELECT * FROM fact_order FOR UPDATE", SQLViolation.LOCKING_SELECT),
        ("SELECT * FROM fact_order LOCK IN SHARE MODE", SQLViolation.LOCKING_SELECT),
        (
            "SELECT /*+ MAX_EXECUTION_TIME(1000) */ * FROM fact_order",
            SQLViolation.OPTIMIZER_HINT,
        ),
        ("SELECT * FROM fact_order FORCE INDEX (idx)", SQLViolation.OPTIMIZER_HINT),
        ("SELECT HIGH_PRIORITY * FROM fact_order", SQLViolation.OPTIMIZER_HINT),
        ("SELECT /*!50000 SLEEP(1) */ 1", SQLViolation.PROHIBITED_CONSTRUCT),
        ("SELECT @unsafe := 1", SQLViolation.PROHIBITED_CONSTRUCT),
        (
            "SELECT * FROM fact_order WHERE id IN (SELECT unsafe_business_function(1))",
            SQLViolation.UNAPPROVED_FUNCTION,
        ),
        ("SELECT RAND() FROM fact_order", SQLViolation.UNAPPROVED_FUNCTION),
        (
            "SELECT * FROM JSON_TABLE('[]', '$[*]' COLUMNS(value INT PATH '$')) AS jt",
            SQLViolation.PROHIBITED_CONSTRUCT,
        ),
        (
            "SELECT * FROM fact_order INTO OUTFILE '/tmp/unsafe'",
            SQLViolation.SQL_PARSE_ERROR,
        ),
        (
            "SELECT * FROM fact_order INTO DUMPFILE '/tmp/unsafe'",
            SQLViolation.SQL_PARSE_ERROR,
        ),
    ],
)
def test_adversarial_sql_fails_closed(
    guard: SQLGuard,
    sql: str,
    violation: SQLViolation,
) -> None:
    evaluation = guard.evaluate(query_plan(sql))

    assert evaluation.result.status is GuardStatus.REJECTED
    assert evaluation.result.violations[0].startswith(violation.value)
    assert evaluation.candidate is None


def test_size_bound_precedes_parsing() -> None:
    guard = SQLGuard(analytics_schema="data_agent", max_sql_characters=10)

    evaluation = guard.evaluate(query_plan("SELECT * FROM fact_order"))

    assert evaluation.result.violations == ["SQL_TOO_LARGE"]
    assert evaluation.parse_succeeded is False


def test_declared_table_authority_is_defensively_unique(guard: SQLGuard) -> None:
    evaluation = guard.evaluate(
        query_plan("SELECT * FROM fact_order", tables=["fact_order", "FACT_ORDER"])
    )

    assert evaluation.result.violations == ["INVALID_DECLARED_TABLES"]
    assert evaluation.candidate is None


def test_namespace_precedes_dangerous_function_policy(guard: SQLGuard) -> None:
    evaluation = guard.evaluate(
        query_plan("SELECT SLEEP(1) FROM other.fact_order", tables=["fact_order"])
    )

    assert evaluation.result.violations == ["UNAUTHORIZED_SCHEMA:other"]


def test_table_subset_precedes_optimizer_hint_policy(guard: SQLGuard) -> None:
    evaluation = guard.evaluate(query_plan("SELECT /*+ MAX_EXECUTION_TIME(1) */ * FROM dim_user"))

    assert evaluation.result.violations == ["UNDECLARED_TABLE:dim_user"]
