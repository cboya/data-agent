"""Mechanical M13 exact-context and no-M14 architecture checks."""

import ast
import re
from pathlib import Path

from data_agent.catalog.semantic import load_assembled_catalog
from data_agent.repair.prompt import QUERY_REPAIR_SYSTEM_PROMPT

REPAIR_ROOT = Path(__file__).resolve().parents[2] / "src" / "data_agent" / "repair"


def test_repair_cannot_import_retrieval_dialogue_catalog_or_answer_layers() -> None:
    forbidden_prefixes = (
        "data_agent.retrieval",
        "data_agent.catalog",
        "data_agent.dialogue",
        "data_agent.api",
        "data_agent.answer",
    )
    for path in REPAIR_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        assert not any(module.startswith(forbidden_prefixes) for module in modules), path


def test_repair_prompt_contains_no_concrete_catalog_table_identifier() -> None:
    prompt = QUERY_REPAIR_SYSTEM_PROMPT.casefold()

    for document in load_assembled_catalog().documents:
        table = re.escape(str(document.table).casefold())
        assert re.search(rf"\b{table}\b", prompt) is None


def test_repair_trace_models_never_define_raw_rows_field() -> None:
    tree = ast.parse(
        (REPAIR_ROOT / "evidence.py").read_text(encoding="utf-8"),
        filename=str(REPAIR_ROOT / "evidence.py"),
    )
    field_names = {
        node.target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    assert not {"rows", "execution_result", "raw_result"}.intersection(field_names)
