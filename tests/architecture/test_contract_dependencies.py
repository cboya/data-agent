import ast
import sys
from pathlib import Path

CONTRACT_ROOT = Path(__file__).resolve().parents[2] / "src" / "data_agent" / "contracts"

ImportReference = tuple[int, str]


def _declared_imports(path: Path) -> set[ImportReference]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[ImportReference] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update((0, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add((node.level, node.module or ""))
    return imports


def _is_allowed(reference: ImportReference) -> bool:
    level, module = reference
    if level == 1:
        return True
    if level >= 2:
        return False

    root = module.partition(".")[0]
    return (
        root in sys.stdlib_module_names
        or module == "pydantic"
        or module.startswith("pydantic.")
        or module == "data_agent.contracts"
        or module.startswith("data_agent.contracts.")
    )


def _display(reference: ImportReference) -> str:
    level, module = reference
    return f"{'.' * level}{module}"


def _dependency_violations(root: Path) -> dict[str, list[str]]:
    violations: dict[str, list[str]] = {}
    for path in sorted(root.rglob("*.py")):
        forbidden = sorted(
            _display(reference)
            for reference in _declared_imports(path)
            if not _is_allowed(reference)
        )
        if forbidden:
            violations[path.relative_to(root).as_posix()] = forbidden
    return violations


def test_contract_layer_depends_only_on_stdlib_pydantic_and_itself() -> None:
    assert any(CONTRACT_ROOT.rglob("*.py")), "contract layer contains no Python modules"
    violations = _dependency_violations(CONTRACT_ROOT)

    assert not violations, f"contract layer contains forbidden dependencies: {violations}"


def test_single_dot_relative_import_is_allowed(tmp_path: Path) -> None:
    contract = tmp_path / "example.py"
    contract.write_text("from .base import ContractModel\n", encoding="utf-8")

    assert _dependency_violations(tmp_path) == {}


def test_parent_relative_import_is_rejected(tmp_path: Path) -> None:
    contract = tmp_path / "example.py"
    contract.write_text("from ..runtime import mysql\n", encoding="utf-8")

    assert _dependency_violations(tmp_path) == {"example.py": ["..runtime"]}


def test_dependency_scan_recurses_into_nested_packages(tmp_path: Path) -> None:
    contract = tmp_path / "nested" / "example.py"
    contract.parent.mkdir()
    contract.write_text("import fastapi\n", encoding="utf-8")

    assert _dependency_violations(tmp_path) == {"nested/example.py": ["fastapi"]}
