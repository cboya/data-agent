import ast
from pathlib import Path

PORT_PATH = (
    Path(__file__).resolve().parents[2] / "src" / "data_agent" / "model_runtime" / "ports.py"
)

ALLOWED_IMPORTS = {
    "dataclasses",
    "hashlib",
    "json",
    "pydantic",
    "typing",
}


def test_model_ports_are_provider_neutral() -> None:
    tree = ast.parse(PORT_PATH.read_text(encoding="utf-8"), filename=str(PORT_PATH))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)

    assert imports <= ALLOWED_IMPORTS
