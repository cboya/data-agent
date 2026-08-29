from data_agent.dialogue.readiness_evaluation import (
    ReadinessExpectedOutcome,
    load_readiness_eval_suite,
    run_readiness_evaluation,
)

FROZEN_FALSE_CLARIFICATION_IDS = {
    "simple-paid-order-count",
    "simple-pending-order-count",
    "simple-failed-attempts",
    "simple-unit-sales",
    "simple-completed-orders",
    "simple-paid-users",
    "agg-paid-order-channel",
    "agg-paid-acquisition-channel",
    "agg-paid-province",
    "agg-orders-status",
    "agg-gmv-status",
    "agg-attempts-status",
    "agg-refund-status",
    "agg-units-product",
    "agg-units-category",
    "agg-events-name",
    "agg-events-channel",
    "agg-paid-date",
    "agg-orders-date",
    "agg-refunds-date",
    "agg-failed-attempts-date",
    "agg-active-users-province",
    "agg-users-register-date",
    "join-attempts-order",
    "join-units-order",
    "join-units-attempts-order",
    "join-paid-orders-category",
    "join-paid-city",
    "join-events-city",
    "join-units-price-product",
    "join-refunds-order",
    "join-paid-users-channel",
    "empty-future-paid",
    "correction-paid-month",
    "repair-users-province",
}


def test_frozen_readiness_suite_contains_exact_diagnosed_cases_and_positive_controls() -> None:
    suite = load_readiness_eval_suite()
    false_cases = {case.id for case in suite.cases if case.category == "KNOWN_FALSE_CLARIFICATION"}
    positive_cases = {case.id for case in suite.cases if case.category == "KNOWN_AMBIGUOUS"}
    complete_ready_cases = {
        case.id for case in suite.cases if case.category == "KNOWN_COMPLETE_READY"
    }
    invalid_evidence_cases = {
        case.id
        for case in suite.cases
        if any(
            turn.expected_outcome is ReadinessExpectedOutcome.INVALID_PROVIDER_EVIDENCE
            for turn in case.turns
        )
    }

    assert false_cases == FROZEN_FALSE_CLARIFICATION_IDS
    assert positive_cases == {
        "ambiguous-metric",
        "ambiguous-dimension",
        "explicit-time-ambiguity",
        "explicit-grain-ambiguity",
    }
    assert complete_ready_cases == {"complete-units-attempts-order"}
    assert invalid_evidence_cases == {
        "simple-paid-users",
        "join-units-order",
        "join-units-attempts-order",
    }
    assert sum(len(case.turns) for case in suite.cases) == 41


def test_provider_free_readiness_eval_enforces_both_clarification_directions() -> None:
    report = run_readiness_evaluation(load_readiness_eval_suite())

    assert report.metrics.frozen_false_clarification_case_count == 35
    assert report.metrics.unnecessary_clarification_count == 0
    assert report.metrics.necessary_clarification_recall == 1.0
    assert report.metrics.false_ready_count == 0
    assert report.metrics.complete_ready_control_count == 1
    assert report.metrics.insufficient_provider_evidence_case_count == 3
    assert report.metrics.insufficient_provider_evidence_false_ready_count == 0
    assert report.metrics.action_accuracy == 1.0
    assert report.metrics.state_accuracy == 1.0
    assert report.metrics.reason_code_accuracy == 1.0
    assert report.metrics.scope_preservation_accuracy == 1.0
    assert report.metrics.confirmed_fact_preservation_accuracy == 1.0
    assert report.passed is True
