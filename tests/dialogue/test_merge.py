from data_agent.contracts.requirement import (
    ClearScalarPatch,
    DimensionRequirement,
    MetricRequirement,
    PatchOp,
    RequirementPatch,
    RequirementState,
    RequirementStatus,
    ResolutionStatus,
    SetScalarPatch,
    TimeRange,
)
from data_agent.dialogue.errors import RequirementMergeError
from data_agent.dialogue.merge import RequirementMerger


def _state() -> RequirementState:
    return RequirementState(
        version="v0.1",
        goal="Revenue trend",
        metrics=[
            MetricRequirement(
                term="实际支付金额",
                resolved_name="paid_amount",
                status=ResolutionStatus.CONFIRMED,
            )
        ],
        dimensions=[
            DimensionRequirement(
                term="地区",
                resolved_name="region",
                status=ResolutionStatus.CONFIRMED,
            )
        ],
        time_range=TimeRange(kind="RELATIVE", value="last_30_days"),
        grain="day",
        comparison="previous_period",
        sort="date_asc",
        limit=100,
        assumptions=["paid orders only"],
        status=RequirementStatus.READY,
    )


def test_scalar_merge_algebra_preserves_sets_and_clears_explicitly() -> None:
    merged = RequirementMerger().merge(
        _state(),
        RequirementPatch(
            version="v0.2",
            grain=ClearScalarPatch(op=PatchOp.CLEAR),
            comparison=SetScalarPatch(op=PatchOp.SET, value="year_over_year"),
            limit=SetScalarPatch(op=PatchOp.SET, value=25),
        ),
    )

    assert merged.goal == "Revenue trend"
    assert merged.time_range == TimeRange(kind="RELATIVE", value="last_30_days")
    assert merged.grain is None
    assert merged.comparison == "year_over_year"
    assert merged.sort == "date_asc"
    assert merged.limit == 25
    assert merged.status is RequirementStatus.INCOMPLETE


def test_metric_and_dimension_corrections_require_explicit_remove_and_upsert() -> None:
    order_count = MetricRequirement(
        term="订单量",
        resolved_name="order_count",
        status=ResolutionStatus.CONFIRMED,
    )
    channel = DimensionRequirement(
        term="渠道",
        resolved_name="channel",
        status=ResolutionStatus.CONFIRMED,
    )
    merged = RequirementMerger().merge(
        _state(),
        RequirementPatch(
            version="v0.2",
            metrics_remove=["paid_amount"],
            metrics_upsert=[order_count],
            dimensions_remove=["region"],
            dimensions_upsert=[channel],
        ),
    )

    assert merged.metrics == [order_count]
    assert merged.dimensions == [channel]


def test_unknown_collection_removal_fails_closed() -> None:
    try:
        RequirementMerger().merge(
            _state(),
            RequirementPatch(version="v0.2", metrics_remove=["not_in_state"]),
        )
    except RequirementMergeError as error:
        assert "unknown metric" in str(error)
    else:
        raise AssertionError("unknown removal did not fail closed")


def test_collection_replace_and_add_operations_are_deterministic() -> None:
    merged = RequirementMerger().merge(
        _state(),
        RequirementPatch(
            version="v0.2",
            filters_replace=[],
            assumptions_add=["paid orders only", "UTC time"],
            unresolved_replace=[],
        ),
    )

    assert merged.filters == []
    assert merged.assumptions == ["paid orders only", "UTC time"]
    assert merged.unresolved == []
