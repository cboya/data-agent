import ast
from pathlib import Path

PORT_PATH = (
    Path(__file__).resolve().parents[2] / "src" / "data_agent" / "model_runtime" / "ports.py"
)


def test_model_ports_are_provider_neutral() -> None:
    tree = ast.parse(PORT_PATH.read_text(encoding="utf-8"), filename=str(PORT_PATH))
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert not any("ollama" in module for module in imports)
