"""Mechanical M11 capability-only and streaming architecture checks."""

import ast
import inspect
import typing
from pathlib import Path

from data_agent.query_runtime.service import ReadOnlyQueryRuntime
from data_agent.sql_guard.capability import GuardedQuery

RUNTIME_ROOT = Path(__file__).resolve().parents[2] / "src" / "data_agent" / "query_runtime"
PLANNING_ROOT = Path(__file__).resolve().parents[2] / "src" / "data_agent" / "planning"


def test_public_execution_boundary_accepts_only_guarded_query() -> None:
    hints = typing.get_type_hints(ReadOnlyQueryRuntime.execute)
    assert hints["query"] is GuardedQuery
    assert len(inspect.signature(ReadOnlyQueryRuntime.execute).parameters) == 2


def test_runtime_has_no_planner_or_pre_explain_capability_dependency() -> None:
    forbidden = {"QueryPlan", "GuardedSQL"}
    execution_boundary_files = (
        RUNTIME_ROOT / "errors.py",
        RUNTIME_ROOT / "evidence.py",
        RUNTIME_ROOT / "mysql.py",
        RUNTIME_ROOT / "service.py",
    )
    for path in execution_boundary_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        assert not imported.intersection(forbidden), path


def test_runtime_never_calls_fetchall() -> None:
    for path in RUNTIME_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assert not any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "fetchall"
            for node in ast.walk(tree)
        ), path


def test_planner_has_no_runtime_or_database_dependency() -> None:
    for path in PLANNING_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        assert "pymysql" not in modules
        assert not any(module.startswith("data_agent.query_runtime") for module in modules)
