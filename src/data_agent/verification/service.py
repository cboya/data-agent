"""Deterministic structural, semantic, and empirical verification."""

from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, SqlglotError

from data_agent.contracts.catalog import CatalogDocument, Relationship
from data_agent.contracts.requirement import DimensionRequirement, MetricRequirement
from data_agent.contracts.verification import CheckResult, VerificationResult
from data_agent.verification.context import VerificationContext
from data_agent.verification.errors import VerificationIntegrityError
from data_agent.verification.evidence import (
    CoverageDisposition,
    VerificationCategory,
    VerificationCoverageGap,
    VerificationEvidenceIdentity,
    VerificationTrace,
)


def _normalized(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _check(
    name: str,
    category: VerificationCategory,
    passed: bool,
    detail: str | None = None,
) -> CheckResult:
    return CheckResult(name=name, category=category, passed=passed, detail=detail)


def _gap(
    name: str,
    category: VerificationCategory,
    disposition: CoverageDisposition,
    detail: str,
) -> VerificationCoverageGap:
    return VerificationCoverageGap(
        name=name,
        category=category,
        disposition=disposition,
        detail=detail,
    )


@dataclass(frozen=True)
class _SemanticSQL:
    expression: exp.Expr
    final_select: exp.Select | None
    physical_tables: frozenset[str]
    table_aliases: dict[str, str]
    document_columns: dict[str, dict[str, str]]
    complex_sources: bool

    def resolve_column(self, column: exp.Column) -> tuple[str, str] | None:
        column_name = _normalized(column.name)
        qualifier = _normalized(column.table) if column.table else None
        if qualifier is not None:
            table = self.table_aliases.get(qualifier)
            if table is None:
                return None
            actual_name = self.document_columns.get(table, {}).get(column_name)
            return None if actual_name is None else (table, actual_name)
        candidates = [
            (table, columns[column_name])
            for table, columns in self.document_columns.items()
            if table in self.physical_tables and column_name in columns
        ]
        return candidates[0] if len(candidates) == 1 else None


def _parse_semantic_sql(context: VerificationContext) -> _SemanticSQL:
    try:
        statements = sqlglot.parse(
            context.guarded_query.sql,
            read="mysql",
            error_message_context=0,
        )
    except (ParseError, SqlglotError, TypeError, ValueError) as error:
        raise VerificationIntegrityError(
            "admitted SQL cannot be parsed for verification"
        ) from error
    if len(statements) != 1 or statements[0] is None:
        raise VerificationIntegrityError("admitted SQL is not one verification statement")
    expression = statements[0]
    root = expression.unnest()
    final_select = root if isinstance(root, exp.Select) else None
    physical_tables = frozenset(table.name for table in context.guarded_query.physical_tables)

    aliases: dict[str, str] = {}
    ambiguous_aliases: set[str] = set()
    for table_expression in expression.find_all(exp.Table):
        table_name = table_expression.name
        if table_name not in physical_tables:
            continue
        for alias in {_normalized(table_name), _normalized(table_expression.alias_or_name)}:
            existing = aliases.get(alias)
            if existing is not None and existing != table_name:
                ambiguous_aliases.add(alias)
            else:
                aliases[alias] = table_name
    for alias in ambiguous_aliases:
        aliases.pop(alias, None)

    document_columns = {
        str(document.table): {
            _normalized(str(column.name)): str(column.name) for column in document.columns
        }
        for document in context.planning_trace.context.documents
    }
    complex_sources = (
        final_select is None
        or expression.find(exp.CTE) is not None
        or expression.find(exp.Subquery) is not None
        or bool(ambiguous_aliases)
    )
    return _SemanticSQL(
        expression=expression,
        final_select=final_select,
        physical_tables=physical_tables,
        table_aliases=aliases,
        document_columns=document_columns,
        complex_sources=complex_sources,
    )


def _governed_sources(
    documents: tuple[CatalogDocument, ...],
    resolved_name: str,
) -> set[tuple[str, str]]:
    target = _normalized(resolved_name)
    matches: set[tuple[str, str]] = set()
    for document in documents:
        for column in document.columns:
            governed_names = {_normalized(str(column.name))}
            governed_names.update(_normalized(str(alias)) for alias in column.aliases)
            if target in governed_names:
                matches.add((str(document.table), str(column.name)))
    return matches


def _projection_lineage(
    sql: _SemanticSQL,
) -> dict[str, set[tuple[str, str]]] | None:
    if sql.complex_sources or sql.final_select is None:
        return None
    lineage: dict[str, set[tuple[str, str]]] = {}
    for projection in sql.final_select.expressions:
        output_name = projection.alias_or_name
        if not output_name or output_name in lineage:
            return None
        sources: set[tuple[str, str]] = set()
        for column in projection.find_all(exp.Column):
            source = sql.resolve_column(column)
            if source is None:
                return None
            sources.add(source)
        lineage[output_name] = sources
    return lineage


def _relationship_edge(relationship: Relationship) -> frozenset[tuple[str, str]]:
    return frozenset(
        {
            (str(relationship.from_table), str(relationship.from_column)),
            (str(relationship.to_table), str(relationship.to_column)),
        }
    )


def _validate_governed_joins(
    sql: _SemanticSQL,
    relationships: tuple[Relationship, ...],
) -> tuple[bool, str | None]:
    if sql.complex_sources:
        return False, "verifier does not prove joins through CTE/subquery/set-operation shapes"
    allowed_edges = {_relationship_edge(relationship) for relationship in relationships}
    graph: dict[str, set[str]] = {table: set() for table in sql.physical_tables}
    joins = list(sql.expression.find_all(exp.Join))
    if not joins:
        return False, "multi-table SQL has no explicit JOIN evidence"

    for join in joins:
        if join.args.get("kind") == "CROSS" or join.args.get("on") is None:
            return False, "cross, USING, or predicate-free joins are not semantically verified"
        on = join.args["on"]
        if not isinstance(on, exp.Expr) or on.find(exp.Or) is not None:
            return False, "OR or unsupported JOIN predicates cannot be proven"
        join_has_edge = False
        for equality in on.find_all(exp.EQ):
            left_columns = list(equality.this.find_all(exp.Column))
            right_columns = list(equality.expression.find_all(exp.Column))
            if not left_columns or not right_columns:
                continue
            if not isinstance(equality.this, exp.Column) or not isinstance(
                equality.expression, exp.Column
            ):
                return False, "transformed JOIN columns are outside verifier coverage"
            left = sql.resolve_column(equality.this)
            right = sql.resolve_column(equality.expression)
            if left is None or right is None:
                return False, "JOIN columns cannot be resolved to bounded catalog sources"
            if left[0] == right[0]:
                continue
            join_has_edge = True
            if frozenset({left, right}) not in allowed_edges:
                return (
                    False,
                    f"JOIN edge is not governed: {left[0]}.{left[1]}={right[0]}.{right[1]}",
                )
            graph[left[0]].add(right[0])
            graph[right[0]].add(left[0])
        if not join_has_edge:
            return False, "JOIN predicate has no direct inter-table column equality"

    start = min(sql.physical_tables)
    visited: set[str] = set()
    pending = [start]
    while pending:
        table = pending.pop()
        if table in visited:
            continue
        visited.add(table)
        pending.extend(sorted(graph[table] - visited, reverse=True))
    if visited != set(sql.physical_tables):
        return False, "governed JOIN evidence does not connect all physical tables"
    return True, None


def _structural_checks(context: VerificationContext) -> list[CheckResult]:
    plan = context.planning_trace.plan
    metadata = context.execution_metadata
    result = context.execution_result
    expected = [str(column.name) for column in plan.expected_columns]
    checks = [
        _check("execution_succeeded", "STRUCTURAL", metadata.outcome.value == "SUCCEEDED"),
        _check(
            "result_not_truncated",
            "STRUCTURAL",
            not result.truncated,
            None if not result.truncated else "runtime returned partial evidence",
        ),
        _check(
            "expected_columns_present",
            "STRUCTURAL",
            bool(expected),
            None if expected else "QueryPlan expected_columns is empty",
        ),
        _check(
            "expected_columns_unique",
            "STRUCTURAL",
            len(expected) == len(set(expected)),
            None if len(expected) == len(set(expected)) else "expected column names are not unique",
        ),
        _check(
            "actual_columns_match_expected",
            "STRUCTURAL",
            result.columns == expected,
            None if result.columns == expected else "actual columns differ in name or order",
        ),
        _check(
            "result_row_count_consistent",
            "STRUCTURAL",
            result.returned_row_count == len(result.rows),
            None
            if result.returned_row_count == len(result.rows)
            else "ExecutionResult row count does not match rows",
        ),
        _check(
            "result_row_shape_consistent",
            "STRUCTURAL",
            all(len(row) == len(result.columns) for row in result.rows),
            None
            if all(len(row) == len(result.columns) for row in result.rows)
            else "ExecutionResult row width does not match columns",
        ),
        _check(
            "metadata_row_count_consistent",
            "STRUCTURAL",
            metadata.returned_row_count == result.returned_row_count,
            None
            if metadata.returned_row_count == result.returned_row_count
            else "execution metadata row count differs from bounded result",
        ),
        _check(
            "metadata_truncation_consistent",
            "STRUCTURAL",
            metadata.truncated is result.truncated,
            None
            if metadata.truncated is result.truncated
            else "execution metadata truncation differs from bounded result",
        ),
    ]
    return checks


def _semantic_checks(
    context: VerificationContext,
    sql: _SemanticSQL,
) -> tuple[list[CheckResult], list[VerificationCoverageGap]]:
    requirement = context.planning_trace.context.requirement
    documents = context.planning_trace.context.documents
    relationships = context.planning_trace.context.relationships
    expected = {str(column.name) for column in context.planning_trace.plan.expected_columns}
    actual = set(context.execution_result.columns)
    checks: list[CheckResult] = []
    gaps: list[VerificationCoverageGap] = []

    checks.append(
        _check(
            "ready_requirement",
            "SEMANTIC",
            requirement.status.value == "READY",
            None if requirement.status.value == "READY" else "requirement is not READY",
        )
    )
    metric_names = [
        str(metric.resolved_name) for metric in requirement.metrics if metric.resolved_name
    ]
    dimension_names = [
        str(dimension.resolved_name)
        for dimension in requirement.dimensions
        if dimension.resolved_name
    ]
    missing_metrics = sorted(
        name for name in metric_names if name not in expected or name not in actual
    )
    checks.append(
        _check(
            "required_metrics_present",
            "SEMANTIC",
            not missing_metrics,
            None
            if not missing_metrics
            else f"required metric outputs are missing: {missing_metrics}",
        )
    )
    missing_dimensions = sorted(
        name for name in dimension_names if name not in expected or name not in actual
    )
    checks.append(
        _check(
            "required_dimensions_present",
            "SEMANTIC",
            not missing_dimensions,
            None
            if not missing_dimensions
            else f"required dimension outputs are missing: {missing_dimensions}",
        )
    )

    if requirement.grain is not None:
        period_present = "period" in expected and "period" in actual
        checks.append(
            _check(
                "grain_period_present",
                "SEMANTIC",
                period_present,
                None
                if period_present
                else "a time grain requires expected and actual period output",
            )
        )
        if "period" in actual:
            period_index = context.execution_result.columns.index("period")
            period_non_null = all(
                row[period_index] is not None for row in context.execution_result.rows
            )
            checks.append(
                _check(
                    "grain_period_non_null",
                    "SEMANTIC",
                    period_non_null,
                    None if period_non_null else "period output contains null grouping evidence",
                )
            )
        else:
            gaps.append(
                _gap(
                    "grain_period_non_null",
                    "SEMANTIC",
                    CoverageDisposition.NOT_APPLICABLE,
                    "period output is absent",
                )
            )
    else:
        gaps.extend(
            [
                _gap(
                    "grain_period_present",
                    "SEMANTIC",
                    CoverageDisposition.NOT_APPLICABLE,
                    "requirement has no time grain",
                ),
                _gap(
                    "grain_period_non_null",
                    "SEMANTIC",
                    CoverageDisposition.NOT_APPLICABLE,
                    "requirement has no time grain",
                ),
            ]
        )

    projection_lineage = _projection_lineage(sql)
    source_groups: tuple[tuple[str, tuple[MetricRequirement | DimensionRequirement, ...]], ...] = (
        ("metric", tuple(requirement.metrics)),
        ("dimension", tuple(requirement.dimensions)),
    )
    for kind, requirements in source_groups:
        for index, item in enumerate(requirements):
            if item.resolved_name is None:
                gaps.append(
                    _gap(
                        f"{kind}_source:{index}",
                        "SEMANTIC",
                        CoverageDisposition.NOT_APPLICABLE,
                        f"{kind} has no resolved_name",
                    )
                )
                continue
            resolved_name = str(item.resolved_name)
            name = f"{kind}_source:{index}:{resolved_name}"
            candidates = _governed_sources(documents, resolved_name)
            if len(candidates) != 1:
                gaps.append(
                    _gap(
                        name,
                        "SEMANTIC",
                        CoverageDisposition.UNSUPPORTED,
                        f"resolved name maps to {len(candidates)} governed column sources",
                    )
                )
            elif projection_lineage is None:
                gaps.append(
                    _gap(
                        name,
                        "SEMANTIC",
                        CoverageDisposition.UNSUPPORTED,
                        "projection lineage is outside the conservative SQL coverage",
                    )
                )
            else:
                required_source = next(iter(candidates))
                source_present = required_source in projection_lineage.get(resolved_name, set())
                checks.append(
                    _check(
                        name,
                        "SEMANTIC",
                        source_present,
                        None
                        if source_present
                        else (
                            "required governed source is absent: "
                            f"{required_source[0]}.{required_source[1]}"
                        ),
                    )
                )

    if len(sql.physical_tables) > 1:
        joins_passed, detail = _validate_governed_joins(sql, relationships)
        checks.append(
            _check(
                "governed_relationship_joins",
                "SEMANTIC",
                joins_passed,
                detail,
            )
        )
    else:
        gaps.append(
            _gap(
                "governed_relationship_joins",
                "SEMANTIC",
                CoverageDisposition.NOT_APPLICABLE,
                "query has fewer than two physical tables",
            )
        )

    if requirement.time_range is not None:
        gaps.append(
            _gap(
                "time_range_semantics",
                "SEMANTIC",
                CoverageDisposition.UNSUPPORTED,
                "current contracts do not identify one machine-readable governed "
                "time source/formula",
            )
        )
    else:
        gaps.append(
            _gap(
                "time_range_semantics",
                "SEMANTIC",
                CoverageDisposition.NOT_APPLICABLE,
                "requirement has no time range",
            )
        )
    if metric_names:
        gaps.append(
            _gap(
                "metric_formula_semantics",
                "SEMANTIC",
                CoverageDisposition.UNSUPPORTED,
                "catalog metric formulas are not machine-readable in the current semantic contract",
            )
        )
    else:
        gaps.append(
            _gap(
                "metric_formula_semantics",
                "SEMANTIC",
                CoverageDisposition.NOT_APPLICABLE,
                "requirement has no resolved metric",
            )
        )
    return checks, gaps


def _is_integral_nonnegative(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value >= 0
    if isinstance(value, Decimal):
        return value.is_finite() and value >= 0 and value == value.to_integral_value()
    if isinstance(value, float):
        return math.isfinite(value) and value >= 0 and value.is_integer()
    return False


def _is_finite_numeric(value: int | float | Decimal) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, Decimal):
        return value.is_finite()
    return True


def _empirical_checks(
    context: VerificationContext,
    sql: _SemanticSQL,
) -> tuple[list[CheckResult], list[VerificationCoverageGap]]:
    result = context.execution_result
    requirement = context.planning_trace.context.requirement
    checks: list[CheckResult] = []
    gaps: list[VerificationCoverageGap] = []

    numeric_values = [
        value
        for row in result.rows
        for value in row
        if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)
    ]
    if numeric_values:
        finite = all(_is_finite_numeric(value) for value in numeric_values)
        checks.append(
            _check(
                "numeric_values_finite",
                "EMPIRICAL",
                finite,
                None if finite else "bounded result contains a non-finite numeric value",
            )
        )
    else:
        gaps.append(
            _gap(
                "numeric_values_finite",
                "EMPIRICAL",
                CoverageDisposition.NOT_APPLICABLE,
                "bounded result contains no numeric values",
            )
        )

    count_indexes: list[int] = []
    if sql.final_select is not None:
        count_indexes = [
            index
            for index, projection in enumerate(sql.final_select.expressions)
            if projection.find(exp.Count) is not None
        ]
    if count_indexes:
        count_valid = all(
            index < len(row) and _is_integral_nonnegative(row[index])
            for row in result.rows
            for index in count_indexes
        )
        checks.append(
            _check(
                "count_outputs_integral_nonnegative",
                "EMPIRICAL",
                count_valid,
                None if count_valid else "COUNT-derived output is negative or non-integral",
            )
        )
    else:
        gaps.append(
            _gap(
                "count_outputs_integral_nonnegative",
                "EMPIRICAL",
                CoverageDisposition.NOT_APPLICABLE,
                "final SQL projection has no COUNT-derived output",
            )
        )

    key_names: list[str] = []
    if requirement.grain is not None and "period" in result.columns:
        key_names.append("period")
    for dimension in requirement.dimensions:
        if dimension.resolved_name is not None:
            name = str(dimension.resolved_name)
            if name in result.columns and name not in key_names:
                key_names.append(name)
    if key_names:
        indexes = [result.columns.index(name) for name in key_names]
        keys = [tuple(row[index] for index in indexes) for row in result.rows]
        unique = len(keys) == len(set(keys))
        checks.append(
            _check(
                "grouping_keys_unique",
                "EMPIRICAL",
                unique,
                None if unique else f"duplicate grouping-key tuple for columns: {key_names}",
            )
        )
    else:
        gaps.append(
            _gap(
                "grouping_keys_unique",
                "EMPIRICAL",
                CoverageDisposition.NOT_APPLICABLE,
                "result has no returned grain/dimension grouping key",
            )
        )
    return checks, gaps


class DeterministicVerifier:
    """Verify a pre-existing evidence context without execution, inference, or repair."""

    def verify(self, context: VerificationContext) -> VerificationTrace:
        if not isinstance(context, VerificationContext):
            raise VerificationIntegrityError("verifier accepts VerificationContext only")
        context.verify_integrity()
        sql = _parse_semantic_sql(context)
        checks = _structural_checks(context)
        semantic_checks, semantic_gaps = _semantic_checks(context, sql)
        empirical_checks, empirical_gaps = _empirical_checks(context, sql)
        checks.extend(semantic_checks)
        checks.extend(empirical_checks)
        gaps = [*semantic_gaps, *empirical_gaps]
        status: Literal["PASSED", "FAILED"] = (
            "FAILED" if any(not check.passed for check in checks) else "PASSED"
        )
        result = VerificationResult(version="v0.1", status=status, checks=checks)
        metadata = context.execution_metadata
        if metadata.result_fingerprint is None:
            raise VerificationIntegrityError("successful execution has no result fingerprint")
        return VerificationTrace(
            evidence=VerificationEvidenceIdentity(
                query_plan_fingerprint=metadata.query_plan_fingerprint,
                guarded_query_fingerprint=metadata.guarded_query_fingerprint,
                execution_id=metadata.execution_id,
                sql_digest=metadata.sql_digest,
                execution_namespace=metadata.execution_namespace,
                result_fingerprint_version=metadata.result_fingerprint_version,
                result_fingerprint=metadata.result_fingerprint,
            ),
            applied_checks=tuple(str(check.name) for check in checks),
            coverage_gaps=tuple(gaps),
            result=result,
        )
