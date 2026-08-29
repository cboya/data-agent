import ast
from pathlib import Path

PORT_PATH = (
    Path(__file__).resolve().parents[2] / "src" / "data_agent" / "model_runtime" / "ports.py"
)

ALLOWED_IMPORTS = {
    "dataclasses",
    "enum",
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


def test_openai_compatible_adapter_stays_out_of_business_modules() -> None:
    source_root = PORT_PATH.parents[1]
    violations: list[str] = []
    allowed = {
        source_root / "model_runtime" / "composition.py",
        source_root / "model_runtime" / "openai_compatible.py",
    }
    for path in source_root.rglob("*.py"):
        if path in allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module = None
            if isinstance(node, ast.ImportFrom):
                module = node.module
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if "openai_compatible" in alias.name:
                        violations.append(str(path.relative_to(source_root)))
            if module is not None and "openai_compatible" in module:
                violations.append(str(path.relative_to(source_root)))

    assert violations == []


def test_provider_selection_stays_in_configuration_and_composition() -> None:
    source_root = PORT_PATH.parents[1]
    allowed = {
        source_root / "config.py",
        source_root / "model_runtime" / "composition.py",
        source_root / "model_runtime" / "openai_compatible.py",
    }
    violations: list[str] = []
    for path in source_root.rglob("*.py"):
        if path in allowed:
            continue
        source = path.read_text(encoding="utf-8")
        if "model_runtime_provider" in source or '"openai_compatible"' in source:
            violations.append(str(path.relative_to(source_root)))

    assert violations == []
