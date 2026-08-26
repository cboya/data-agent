"""Mechanical evidence-only architecture checks for M12."""

import ast
import inspect
import typing
from pathlib import Path

from data_agent.verification.context import VerificationContext
from data_agent.verification.service import DeterministicVerifier

VERIFICATION_ROOT = Path(__file__).resolve().parents[2] / "src" / "data_agent" / "verification"


def test_verifier_accepts_only_coherent_context() -> None:
    hints = typing.get_type_hints(DeterministicVerifier.verify)
    assert hints["context"] is VerificationContext
    assert len(inspect.signature(DeterministicVerifier.verify).parameters) == 2


def test_verification_has_no_database_model_or_repair_dependency() -> None:
    forbidden_prefixes = (
        "pymysql",
        "data_agent.model_runtime",
        "data_agent.query_runtime.mysql",
        "data_agent.query_runtime.service",
        "data_agent.repair",
    )
    for path in VERIFICATION_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        direct_modules = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        assert not any(
            module.startswith(forbidden_prefixes) for module in modules | direct_modules
        ), path


def test_verifier_never_connects_or_executes() -> None:
    for path in VERIFICATION_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        called_attributes = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert not {"connect", "execute", "structured", "embed"}.intersection(called_attributes), (
            path
        )
