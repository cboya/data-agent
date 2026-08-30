"""Local artifact paths for the one active analytics catalog workspace."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from data_agent.analytics import AnalyticsSourceProfile, active_analytics_source
from data_agent.config import SYNTHETIC_CATALOG_WORKSPACE, Settings

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CATALOG_ROOT = REPOSITORY_ROOT / "catalog"
SYNTHETIC_GENERATED_ROOT = CATALOG_ROOT / "generated"
SYNTHETIC_SEMANTIC_ROOT = CATALOG_ROOT / "semantic"
EXTERNAL_WORKSPACES_ROOT = CATALOG_ROOT / "workspaces"


@dataclass(frozen=True)
class CatalogWorkspace:
    """Resolved paths for a single source profile; no source selection happens here."""

    identity: str
    generated_root: Path
    semantic_root: Path

    @property
    def generated_schema_path(self) -> Path:
        return self.generated_root / "schema.json"

    @property
    def assembled_catalog_path(self) -> Path:
        return self.generated_root / "catalog.json"

    @property
    def retrieval_index_path(self) -> Path:
        return self.generated_root / "index" / "retrieval.json"

    @property
    def tables_semantics_path(self) -> Path:
        return self.semantic_root / "tables.yaml"

    @property
    def relationships_semantics_path(self) -> Path:
        return self.semantic_root / "relationships.yaml"


def catalog_workspace(profile: AnalyticsSourceProfile) -> CatalogWorkspace:
    """Resolve the synthetic authority or one safely named external workspace."""

    if profile.mode == "SYNTHETIC":
        if profile.catalog_workspace != SYNTHETIC_CATALOG_WORKSPACE:
            raise ValueError("synthetic catalog workspace identity drifted")
        return CatalogWorkspace(
            identity=profile.catalog_workspace,
            generated_root=SYNTHETIC_GENERATED_ROOT,
            semantic_root=SYNTHETIC_SEMANTIC_ROOT,
        )
    workspace_root = EXTERNAL_WORKSPACES_ROOT / profile.catalog_workspace
    return CatalogWorkspace(
        identity=profile.catalog_workspace,
        generated_root=workspace_root / "generated",
        semantic_root=workspace_root / "semantic",
    )


def active_catalog_workspace(settings: Settings) -> CatalogWorkspace:
    """Resolve paths for the one profile selected by validated configuration."""

    return catalog_workspace(active_analytics_source(settings))


def is_safe_generated_root(path: Path) -> bool:
    """Accept only the synthetic root or one direct external workspace generated root."""

    resolved = path.resolve()
    if resolved.name != "generated":
        return False
    if resolved.parent.name == "catalog":
        return True
    return (
        resolved.parent.parent.name == "workspaces"
        and resolved.parent.parent.parent.name == "catalog"
    )


def ensure_generated_output_path(output_path: Path, generated_root: Path) -> None:
    """Keep rebuildable output beneath one recognized generated workspace."""

    resolved_output = output_path.resolve()
    resolved_root = generated_root.resolve()
    if not is_safe_generated_root(generated_root):
        raise ValueError(
            "generated catalog root must be catalog/generated or catalog/workspaces/<id>/generated"
        )
    if not resolved_output.is_relative_to(resolved_root) or resolved_output == resolved_root:
        raise ValueError(
            "generated output must stay beneath catalog/generated or its external workspace"
        )
