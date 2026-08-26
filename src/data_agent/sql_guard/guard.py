"""Deterministic MySQL AST guard and scope-aware table authority."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

import sqlglot
from sqlglot import exp
from sqlglot.errors import OptimizeError, ParseError, SqlglotError
from sqlglot.optimizer.scope import Scope, traverse_scope

from data_agent.contracts.execution import GuardStatus, SQLGuardResult
from data_agent.contracts.query import QueryPlan
from data_agent.sql_guard.capability import GuardedSQL, PhysicalTable, issue_guarded_sql

# SQLGlot logs unsupported input together with a raw SQL prefix before returning Command.
# Guard outcomes carry only stable codes, so suppress that library warning to avoid SQL leakage.
logging.getLogger("sqlglot").setLevel(logging.ERROR)

SQL_GUARD_POLICY_VERSION = "sql-guard-v0.2"


class SQLViolation(StrEnum):
    SQL_TOO_LARGE = "SQL_TOO_LARGE"
    SQL_PARSE_ERROR = "SQL_PARSE_ERROR"
    MULTIPLE_STATEMENTS = "MULTIPLE_STATEMENTS"
    UNSUPPORTED_STATEMENT = "UNSUPPORTED_STATEMENT"
    RECURSIVE_CTE = "RECURSIVE_CTE"
    PROHIBITED_CONSTRUCT = "PROHIBITED_CONSTRUCT"
    DANGEROUS_FUNCTION = "DANGEROUS_FUNCTION"
    UNAPPROVED_FUNCTION = "UNAPPROVED_FUNCTION"
    LOCKING_SELECT = "LOCKING_SELECT"
    OPTIMIZER_HINT = "OPTIMIZER_HINT"
    SCOPE_RESOLUTION_FAILED = "SCOPE_RESOLUTION_FAILED"
    UNAUTHORIZED_SCHEMA = "UNAUTHORIZED_SCHEMA"
    UNDECLARED_TABLE = "UNDECLARED_TABLE"
    INVALID_DECLARED_TABLES = "INVALID_DECLARED_TABLES"


@dataclass(frozen=True)
class SQLGuardEvaluation:
    result: SQLGuardResult
    physical_tables: tuple[PhysicalTable, ...] = ()
    unused_declared_tables: tuple[str, ...] = ()
    parse_succeeded: bool = False
    table_scope_compliant: bool | None = None
    candidate: GuardedSQL | None = None


_DANGEROUS_FUNCTIONS = frozenset(
    {
        "BENCHMARK",
        "GET_LOCK",
        "IS_FREE_LOCK",
        "IS_USED_LOCK",
        "LOAD_FILE",
        "RELEASE_ALL_LOCKS",
        "RELEASE_LOCK",
        "SLEEP",
    }
)
_APPROVED_FUNCTION_TYPES: frozenset[type[exp.Func]] = frozenset(
    {
        exp.And,
        exp.Case,
        exp.Cast,
        exp.Coalesce,
        exp.Count,
        exp.CurrentDate,
        exp.DateSub,
        exp.If,
        exp.Or,
        exp.Sum,
        exp.TsOrDsToDate,
    }
)
_QUERY_MODIFIERS = frozenset(
    {
        "HIGH_PRIORITY",
        "SQL_BIG_RESULT",
        "SQL_BUFFER_RESULT",
        "SQL_CALC_FOUND_ROWS",
        "SQL_NO_CACHE",
        "SQL_SMALL_RESULT",
        "STRAIGHT_JOIN",
    }
)
_PROHIBITED_NODE_TYPES = (
    exp.DDL,
    exp.DML,
    exp.Into,
    exp.JSONTable,
    exp.Parameter,
    exp.PropertyEQ,
    exp.QueryOption,
    exp.SessionParameter,
    exp.TableSample,
    exp.UDTF,
)


def _rejected(
    violation: SQLViolation,
    *,
    detail: str | None = None,
    referenced_tables: tuple[str, ...] = (),
    physical_tables: tuple[PhysicalTable, ...] = (),
    parse_succeeded: bool = False,
    table_scope_compliant: bool | None = None,
) -> SQLGuardEvaluation:
    rendered = violation.value if detail is None else f"{violation.value}:{detail}"
    return SQLGuardEvaluation(
        result=SQLGuardResult(
            status=GuardStatus.REJECTED,
            referenced_tables=list(referenced_tables),
            violations=[rendered],
        ),
        physical_tables=physical_tables,
        parse_succeeded=parse_succeeded,
        table_scope_compliant=table_scope_compliant,
    )


def _function_policy_violation(
    expression: exp.Expr,
) -> tuple[SQLViolation, str] | None:
    for function in expression.find_all(exp.Func):
        name = function.name if isinstance(function, exp.Anonymous) else function.sql_name()
        normalized = name.upper()
        if normalized in _DANGEROUS_FUNCTIONS:
            return SQLViolation.DANGEROUS_FUNCTION, normalized
        if isinstance(function, exp.Anonymous) or type(function) not in _APPROVED_FUNCTION_TYPES:
            return SQLViolation.UNAPPROVED_FUNCTION, normalized
    return None


def _has_mysql_executable_comment(expression: exp.Expr) -> bool:
    return any(
        comment.lstrip().startswith("!")
        for node in expression.walk()
        for comment in (node.comments or ())
    )


def _physical_tables(expression: exp.Expr) -> tuple[PhysicalTable, ...]:
    tables: set[PhysicalTable] = set()
    scopes = traverse_scope(expression)
    if not scopes:
        raise OptimizeError("query produced no SQL scopes")
    for scope in scopes:
        for source in scope.sources.values():
            if isinstance(source, Scope):
                continue
            if not isinstance(source, exp.Table):
                raise OptimizeError("unsupported physical table source")
            if not source.name:
                raise OptimizeError("physical table has no name")
            if source.catalog:
                tables.add(
                    PhysicalTable(
                        schema=f"{source.catalog}.{source.db}" if source.db else source.catalog,
                        name=source.name,
                    )
                )
            else:
                tables.add(PhysicalTable(schema=source.db or None, name=source.name))
    return tuple(sorted(tables))


class SQLGuard:
    def __init__(
        self,
        *,
        analytics_schema: str,
        max_sql_characters: int = 64_000,
    ) -> None:
        if not analytics_schema.strip():
            raise ValueError("analytics schema cannot be blank")
        if max_sql_characters < 1:
            raise ValueError("SQL character bound must be positive")
        self._analytics_schema = analytics_schema
        self._max_sql_characters = max_sql_characters

    def evaluate(
        self,
        plan: QueryPlan,
        *,
        planner_context_fingerprint: str,
    ) -> SQLGuardEvaluation:
        sql = str(plan.sql)
        if len(sql) > self._max_sql_characters:
            return _rejected(SQLViolation.SQL_TOO_LARGE)
        try:
            statements = sqlglot.parse(sql, read="mysql", error_message_context=0)
        except (ParseError, SqlglotError, ValueError) as error:
            return _rejected(SQLViolation.SQL_PARSE_ERROR, detail=type(error).__name__)
        if len(statements) != 1 or statements[0] is None:
            return _rejected(
                SQLViolation.MULTIPLE_STATEMENTS,
                parse_succeeded=True,
            )
        expression = statements[0]
        root = expression.unnest()
        if not isinstance(root, (exp.Select, exp.SetOperation)):
            return _rejected(
                SQLViolation.UNSUPPORTED_STATEMENT,
                detail=type(root).__name__,
                parse_succeeded=True,
            )
        if any(with_.args.get("recursive") is True for with_ in expression.find_all(exp.With)):
            return _rejected(SQLViolation.RECURSIVE_CTE, parse_succeeded=True)
        if _has_mysql_executable_comment(expression):
            return _rejected(
                SQLViolation.PROHIBITED_CONSTRUCT,
                detail="EXECUTABLE_COMMENT",
                parse_succeeded=True,
            )
        prohibited = expression.find(*_PROHIBITED_NODE_TYPES)
        if prohibited is not None:
            return _rejected(
                SQLViolation.PROHIBITED_CONSTRUCT,
                detail=type(prohibited).__name__,
                parse_succeeded=True,
            )
        try:
            physical_tables = _physical_tables(expression)
        except (OptimizeError, SqlglotError, ValueError) as error:
            return _rejected(
                SQLViolation.SCOPE_RESOLUTION_FAILED,
                detail=type(error).__name__,
                parse_succeeded=True,
            )
        referenced = tuple(table.qualified_name for table in physical_tables)
        unauthorized_schemas = sorted(
            {
                table.schema
                for table in physical_tables
                if table.schema is not None and table.schema != self._analytics_schema
            }
        )
        if unauthorized_schemas:
            return _rejected(
                SQLViolation.UNAUTHORIZED_SCHEMA,
                detail=",".join(unauthorized_schemas),
                referenced_tables=referenced,
                physical_tables=physical_tables,
                parse_succeeded=True,
                table_scope_compliant=False,
            )

        declared = [str(table) for table in plan.tables]
        declared_by_name = {table: table for table in declared}
        declared_casefold = {table.casefold() for table in declared}
        if not declared or len(declared) != len(declared_casefold):
            return _rejected(
                SQLViolation.INVALID_DECLARED_TABLES,
                referenced_tables=referenced,
                physical_tables=physical_tables,
                parse_succeeded=True,
                table_scope_compliant=False,
            )
        referenced_names = {table.name for table in physical_tables}
        undeclared = sorted(referenced_names - set(declared_by_name))
        if undeclared:
            return _rejected(
                SQLViolation.UNDECLARED_TABLE,
                detail=",".join(undeclared),
                referenced_tables=referenced,
                physical_tables=physical_tables,
                parse_succeeded=True,
                table_scope_compliant=False,
            )

        if expression.find(exp.Hint) is not None:
            return _rejected(
                SQLViolation.OPTIMIZER_HINT,
                referenced_tables=referenced,
                physical_tables=physical_tables,
                parse_succeeded=True,
                table_scope_compliant=True,
            )
        if expression.find(exp.IndexTableHint) is not None:
            return _rejected(
                SQLViolation.OPTIMIZER_HINT,
                detail="INDEX",
                referenced_tables=referenced,
                physical_tables=physical_tables,
                parse_succeeded=True,
                table_scope_compliant=True,
            )
        query_modifier = next(
            (
                variable.name.upper()
                for variable in expression.find_all(exp.Var)
                if variable.name.upper() in _QUERY_MODIFIERS
            ),
            None,
        )
        if query_modifier is not None:
            return _rejected(
                SQLViolation.OPTIMIZER_HINT,
                detail=query_modifier,
                referenced_tables=referenced,
                physical_tables=physical_tables,
                parse_succeeded=True,
                table_scope_compliant=True,
            )
        if expression.find(exp.Lock) is not None:
            return _rejected(
                SQLViolation.LOCKING_SELECT,
                referenced_tables=referenced,
                physical_tables=physical_tables,
                parse_succeeded=True,
                table_scope_compliant=True,
            )
        function_violation = _function_policy_violation(expression)
        if function_violation is not None:
            violation, function_name = function_violation
            return _rejected(
                violation,
                detail=function_name,
                referenced_tables=referenced,
                physical_tables=physical_tables,
                parse_succeeded=True,
                table_scope_compliant=True,
            )

        normalized_referenced = tuple(sorted(declared_by_name[table] for table in referenced_names))
        result = SQLGuardResult(
            status=GuardStatus.PASSED,
            referenced_tables=list(normalized_referenced),
            violations=[],
        )
        candidate = issue_guarded_sql(
            plan,
            planner_context_fingerprint=planner_context_fingerprint,
            physical_tables=physical_tables,
            guard_result=result,
            execution_namespace=self._analytics_schema,
            guard_policy_version=SQL_GUARD_POLICY_VERSION,
        )
        unused = tuple(
            sorted(declared_by_name[table] for table in set(declared_by_name) - referenced_names)
        )
        return SQLGuardEvaluation(
            result=result,
            physical_tables=physical_tables,
            unused_declared_tables=unused,
            parse_succeeded=True,
            table_scope_compliant=True,
            candidate=candidate,
        )
