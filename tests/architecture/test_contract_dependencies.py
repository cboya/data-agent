import ast
import sys
from pathlib import Path

CONTRACT_ROOT = Path(__file__).resolve().parents[2] / "src" / "data_agent" / "contracts"


def _declared_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module is not None:
            imports.add(node.module)
    return imports


def _is_allowed(module: str) -> bool:
    root = module.partition(".")[0]
    return (
        root in sys.stdlib_module_names
        or module == "pydantic"
        or module.startswith("pydantic.")
        or module == "data_agent.contracts"
        or module.startswith("data_agent.contracts.")
    )


def test_contract_layer_depends_only_on_stdlib_pydantic_and_itself() -> None:
    violations = {
        path.name: sorted(module for module in _declared_imports(path) if not _is_allowed(module))
        for path in sorted(CONTRACT_ROOT.glob("*.py"))
    }
    violations = {path: modules for path, modules in violations.items() if modules}

    assert not violations, f"contract layer contains forbidden dependencies: {violations}"
