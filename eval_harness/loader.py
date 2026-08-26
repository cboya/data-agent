"""Fail-closed Golden and Oracle source loading."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import sqlglot
import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError
from sqlglot import exp

from eval_harness.models import GoldenSuite, OracleSuite

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_PATH = REPOSITORY_ROOT / "evals" / "golden.yaml"
ORACLE_PATH = REPOSITORY_ROOT / "evals" / "oracles.yaml"


class AcceptanceSourceError(RuntimeError):
    pass


class _UniqueLoader(yaml.SafeLoader):  # type: ignore[misc]
    def construct_mapping(self, node: Any, deep: bool = False) -> dict[Any, Any]:
        self.flatten_mapping(node)
        result: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in result:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found duplicate key: {key}",
                    key_node.start_mark,
                )
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def _load(path: Path) -> object:
    try:
        return yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueLoader)
    except (OSError, yaml.YAMLError) as error:
        raise AcceptanceSourceError(f"acceptance source is unreadable: {path.name}") from error


def load_golden() -> tuple[GoldenSuite, str]:
    raw = _load(GOLDEN_PATH)
    try:
        suite = GoldenSuite.model_validate(raw)
    except ValidationError as error:
        raise AcceptanceSourceError("Golden Dataset failed strict validation") from error
    canonical = json.dumps(raw, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return suite, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_oracles(golden: GoldenSuite) -> OracleSuite:
    try:
        suite = OracleSuite.model_validate(_load(ORACLE_PATH))
    except ValidationError as error:
        raise AcceptanceSourceError("Oracle suite failed strict validation") from error
    expected = {case.oracle for case in golden.cases if case.oracle is not None}
    if set(suite.queries) != expected:
        raise AcceptanceSourceError("Oracle ids do not exactly cover result Golden cases")
    expected_columns: dict[str, tuple[str, ...]] = {}
    for case in golden.cases:
        if case.oracle is None:
            continue
        previous = expected_columns.setdefault(case.oracle, case.expected_columns)
        if previous != case.expected_columns:
            raise AcceptanceSourceError(
                f"Golden cases disagree on Oracle output columns: {case.oracle}"
            )
    for oracle_id, sql in suite.queries.items():
        try:
            statements = sqlglot.parse(sql, read="mysql")
        except Exception as error:
            raise AcceptanceSourceError(f"Oracle SQL is invalid: {oracle_id}") from error
        if len(statements) != 1 or statements[0] is None:
            raise AcceptanceSourceError(f"Oracle SQL is not one statement: {oracle_id}")
        root = statements[0].unnest()
        if not isinstance(root, (exp.Select, exp.SetOperation)):
            raise AcceptanceSourceError(f"Oracle SQL is not read-only SELECT: {oracle_id}")
        projected = tuple(root.named_selects)
        required = expected_columns[oracle_id]
        if len(projected) != len(required) or set(projected) != set(required):
            raise AcceptanceSourceError(
                f"Oracle output columns do not match Golden cases: {oracle_id}"
            )
    return suite
