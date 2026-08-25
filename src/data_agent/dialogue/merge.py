"""Pure deterministic RequirementPatch v0.2 merge algebra."""

from __future__ import annotations

from collections.abc import Callable

from data_agent.contracts.requirement import (
    DimensionRequirement,
    MetricRequirement,
    PatchOp,
    RequirementPatch,
    RequirementState,
    RequirementStatus,
    ScalarPatch,
)
from data_agent.dialogue.errors import RequirementMergeError


def _scalar_value[ScalarT](current: ScalarT | None, patch: ScalarPatch[ScalarT]) -> ScalarT | None:
    if patch.op is PatchOp.NO_CHANGE:
        return current
    if patch.op is PatchOp.CLEAR:
        return None
    return patch.value


def _item_identity(value: MetricRequirement | DimensionRequirement) -> str:
    return str(value.resolved_name or value.term)


def _merge_items[RequirementItemT: (MetricRequirement, DimensionRequirement)](
    current: list[RequirementItemT],
    *,
    remove: list[str],
    upsert: list[RequirementItemT],
    identity: Callable[[RequirementItemT], str],
    kind: str,
) -> list[RequirementItemT]:
    positions = {identity(value): index for index, value in enumerate(current)}
    missing = [key for key in remove if key not in positions]
    if missing:
        raise RequirementMergeError(f"cannot remove unknown {kind} identities: {missing}")

    removed = set(remove)
    merged = [value for value in current if identity(value) not in removed]
    current_positions = {identity(value): index for index, value in enumerate(merged)}
    for value in upsert:
        key = identity(value)
        if key in current_positions:
            merged[current_positions[key]] = value
        else:
            current_positions[key] = len(merged)
            merged.append(value)
    return merged


class RequirementMerger:
    """Apply only explicit patch operations; no language or semantic inference occurs here."""

    def merge(self, state: RequirementState, patch: RequirementPatch) -> RequirementState:
        metrics = _merge_items(
            state.metrics,
            remove=[str(value) for value in patch.metrics_remove],
            upsert=patch.metrics_upsert,
            identity=_item_identity,
            kind="metric",
        )
        dimensions = _merge_items(
            state.dimensions,
            remove=[str(value) for value in patch.dimensions_remove],
            upsert=patch.dimensions_upsert,
            identity=_item_identity,
            kind="dimension",
        )
        confirmed_terms = {
            **{str(key): str(value) for key, value in state.confirmed_terms.items()},
            **{str(key): str(value) for key, value in patch.confirmed_terms_upsert.items()},
        }
        assumptions = list(dict.fromkeys([*state.assumptions, *patch.assumptions_add]))
        return RequirementState.model_validate(
            {
                **state.model_dump(mode="python"),
                "goal": _scalar_value(state.goal, patch.goal),
                "time_range": _scalar_value(state.time_range, patch.time_range),
                "grain": _scalar_value(state.grain, patch.grain),
                "comparison": _scalar_value(state.comparison, patch.comparison),
                "sort": _scalar_value(state.sort, patch.sort),
                "limit": _scalar_value(state.limit, patch.limit),
                "metrics": metrics,
                "dimensions": dimensions,
                "filters": (
                    state.filters if patch.filters_replace is None else patch.filters_replace
                ),
                "confirmed_terms": dict(sorted(confirmed_terms.items())),
                "assumptions": assumptions,
                "unresolved": (
                    state.unresolved
                    if patch.unresolved_replace is None
                    else patch.unresolved_replace
                ),
                "status": RequirementStatus.INCOMPLETE,
            }
        )
