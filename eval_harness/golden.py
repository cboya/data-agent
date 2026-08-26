"""Public-API Golden execution with persisted Run and trace assertions."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast

from fastapi.testclient import TestClient

from data_agent.config import Settings
from data_agent.contracts.run import Run
from data_agent.infrastructure.mysql_world import readonly_connection
from data_agent.persistence.mysql.runs import MySQLRunRepository
from data_agent.persistence.mysql.traces import MySQLTraceRepository
from data_agent.trace.model import TraceEvent, TraceEventType
from data_agent.trace.policy import TraceCompletenessPolicy
from eval_harness.models import (
    EvaluationEnvironment,
    GoldenCase,
    GoldenCaseResult,
    GoldenMetrics,
    GoldenReport,
    GoldenSuite,
    OracleSuite,
)


def _json_cell(value: object) -> object:
    if value is None or isinstance(value, str | bool | int | float):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Oracle returned unsupported cell type {type(value).__name__}")


def _oracle_result(
    settings: Settings, sql: str
) -> tuple[tuple[str, ...], tuple[tuple[object, ...], ...]]:
    connection = readonly_connection(settings)
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql)
            if cursor.description is None:
                raise RuntimeError("Oracle SELECT returned no column metadata")
            columns = tuple(str(item[0]) for item in cursor.description)
            rows = tuple(tuple(_json_cell(value) for value in row) for row in cursor.fetchall())
    finally:
        connection.close()
    return columns, rows


def _canonical_rows(
    columns: tuple[str, ...],
    rows: tuple[tuple[object, ...], ...],
    expected_columns: tuple[str, ...],
) -> tuple[str, ...] | None:
    if set(columns) != set(expected_columns) or len(columns) != len(expected_columns):
        return None
    indexes = tuple(columns.index(column) for column in expected_columns)
    projected = [tuple(row[index] for index in indexes) for row in rows]
    return tuple(sorted(json.dumps(row, ensure_ascii=True, default=str) for row in projected))


def _assert_trace(
    settings: Settings,
    run_id: str,
) -> tuple[bool, Run, tuple[TraceEvent, ...], list[str]]:
    errors: list[str] = []
    run = MySQLRunRepository(settings).get(run_id)
    events = tuple(MySQLTraceRepository(settings).list_for_run(run_id))
    try:
        TraceCompletenessPolicy().validate(run, events)
    except Exception as error:
        errors.append(f"trace: {type(error).__name__}: {error}")
    return not errors, run, events, errors


_NUMBER_PATTERN = re.compile(r"(?<![A-Za-z0-9_.])[-+]?\d[\d,]*(?:\.\d+)?%?(?![A-Za-z0-9_.])")


def _normalized_number(token: str) -> tuple[str, Decimal | str]:
    normalized = token.replace(",", "")
    if normalized.endswith("%"):
        return ("percent", normalized)
    return ("number", Decimal(normalized))


def _numeric_grounding_violations(
    payload: dict[str, Any],
    events: tuple[TraceEvent, ...],
) -> int:
    synthesis = next(
        (
            event
            for event in reversed(events)
            if event.event_type is TraceEventType.SYNTHESIS_COMPLETED
            and event.payload.get("outcome") == "SUCCEEDED"
        ),
        None,
    )
    if synthesis is None:
        return 0
    rows = payload.get("data", {}).get("rows", [])
    refs = synthesis.payload.get("evidence_refs", [])
    allowed: set[tuple[str, Decimal | str]] = set()
    for ref in refs:
        if not isinstance(ref, dict):
            return 1
        try:
            cell = rows[int(ref["row_index"])][int(ref["column_index"])]
        except (IndexError, KeyError, TypeError, ValueError):
            return 1
        for token in _NUMBER_PATTERN.findall(str(cell)):
            allowed.add(_normalized_number(token))
    return sum(
        _normalized_number(token) not in allowed
        for token in _NUMBER_PATTERN.findall(str(payload.get("answer", "")))
    )


def _failed_trace_events(run_id: str, events: tuple[TraceEvent, ...]) -> list[str]:
    failed: list[str] = []
    success_outcomes = {"RECEIVED", "SUCCEEDED", "PASSED", "TERMINATED"}
    for event in events:
        outcome = event.payload.get("outcome")
        if isinstance(outcome, str) and outcome not in success_outcomes:
            failed.append(
                f"{run_id}:attempt={event.attempt}:{event.stage.value}:"
                f"{event.event_type.value}:{outcome}"
            )
    return failed


def _trace_gate_counts(events: tuple[TraceEvent, ...]) -> tuple[int, int, int]:
    unauthorized = 0
    failed_verification_synthesis = 0
    repair_bound = int(any(event.attempt > 1 for event in events))
    for index, event in enumerate(events):
        prior = events[:index]
        if event.event_type is TraceEventType.EXECUTION_COMPLETED:
            admitted = any(
                value.event_type is TraceEventType.SQL_ADMISSION_COMPLETED
                and value.attempt == event.attempt
                and value.payload.get("outcome") == "SUCCEEDED"
                for value in prior
            )
            unauthorized += int(not admitted)
        if (
            event.event_type is TraceEventType.SYNTHESIS_COMPLETED
            and event.payload.get("outcome") == "SUCCEEDED"
        ):
            failed = any(
                value.event_type is TraceEventType.VERIFICATION_COMPLETED
                and value.attempt == event.attempt
                and value.payload.get("outcome") != "PASSED"
                for value in prior
            )
            failed_verification_synthesis += int(failed)
    return unauthorized, failed_verification_synthesis, repair_bound


def _run_case(
    *,
    client: TestClient,
    settings: Settings,
    case: GoldenCase,
    oracles: OracleSuite,
) -> tuple[GoldenCaseResult, int, int, int, int, int]:
    errors: list[str] = []
    response_types: list[str] = []
    run_ids: list[str] = []
    run_statuses: list[str] = []
    run_error_codes: list[str | None] = []
    trace_event_ids: list[str] = []
    trace_payload_fingerprints: list[str] = []
    failed_events: list[str] = []
    trace_passed = True
    max_repair_count = 0
    unauthorized = failed_synthesis = repair_bound = 0
    unexpected_clarifications = numeric_violations = 0
    created = client.post("/sessions")
    if created.status_code != 201:
        raise RuntimeError(f"public session creation failed: {created.status_code}")
    session_id = str(created.json()["id"])
    final_payload: dict[str, Any] = {}
    for turn_number, turn in enumerate(case.turns, start=1):
        response = client.post(
            f"/sessions/{session_id}/messages",
            json={"content": turn.content},
        )
        if response.status_code != 200:
            errors.append(f"turn {turn_number}: HTTP {response.status_code}")
            trace_passed = False
            continue
        payload = cast(dict[str, Any], response.json())
        final_payload = payload
        actual_type = str(payload.get("type"))
        response_types.append(actual_type)
        if actual_type != turn.expected_type:
            errors.append(
                f"turn {turn_number}: expected {turn.expected_type}, received {actual_type}"
            )
            if actual_type == "clarification" and turn.expected_type != "clarification":
                unexpected_clarifications += 1
        run_id = str(payload.get("run_id", ""))
        if not run_id:
            errors.append(f"turn {turn_number}: response omitted Run identity")
            trace_passed = False
            continue
        run_ids.append(run_id)
        public_run = client.get(f"/runs/{run_id}")
        if public_run.status_code != 200:
            errors.append(f"turn {turn_number}: persisted Run is not publicly readable")
        try:
            valid, run, events, trace_errors = _assert_trace(settings, run_id)
        except Exception as error:
            trace_passed = False
            errors.append(
                f"turn {turn_number}: trace reload failed: {type(error).__name__}: {error}"
            )
            continue
        trace_passed = trace_passed and valid
        errors.extend(f"turn {turn_number}: {value}" for value in trace_errors)
        run_statuses.append(run.status.value)
        run_error_codes.append(run.error_code)
        trace_event_ids.extend(str(event.id) for event in events)
        trace_payload_fingerprints.extend(str(event.payload_fingerprint) for event in events)
        failed_events.extend(_failed_trace_events(run_id, events))
        max_repair_count = max(max_repair_count, run.repair_count)
        counts = _trace_gate_counts(events)
        unauthorized += counts[0]
        failed_synthesis += counts[1]
        repair_bound += counts[2] + int(run.repair_count > 1)
        if actual_type == "result":
            numeric_violations += _numeric_grounding_violations(payload, events)

    if case.repair_expectation == "FORBIDDEN" and max_repair_count != 0:
        errors.append("repair was forbidden for this case")
    if case.repair_expectation == "REQUIRED" and max_repair_count != 1:
        errors.append("exactly one bounded repair was required for this case")

    oracle_passed: bool | None = None
    observed_tables: tuple[str, ...] = ()
    observed_columns: tuple[str, ...] = ()
    if case.turns[-1].expected_type == "result" and final_payload.get("type") == "result":
        actual_tables = {str(value).split(".")[-1] for value in final_payload["evidence"]["tables"]}
        observed_tables = tuple(sorted(actual_tables))
        missing = sorted(set(case.required_tables) - actual_tables)
        if missing:
            errors.append(f"required tables missing: {missing}")
        data = final_payload["data"]
        actual_columns = tuple(str(value) for value in data["columns"])
        observed_columns = actual_columns
        actual_rows = tuple(tuple(row) for row in data["rows"])
        if case.oracle is None:
            raise AssertionError("validated result case has no Oracle")
        oracle_columns, oracle_rows = _oracle_result(settings, oracles.queries[case.oracle])
        actual_canonical = _canonical_rows(actual_columns, actual_rows, case.expected_columns)
        oracle_canonical = _canonical_rows(oracle_columns, oracle_rows, case.expected_columns)
        oracle_passed = (
            actual_canonical is not None
            and oracle_canonical is not None
            and actual_canonical == oracle_canonical
        )
        if not oracle_passed:
            errors.append("public result did not match the trusted result Oracle")
    elif case.turns[-1].expected_type == "result":
        oracle_passed = False
        errors.append("result Oracle was not reached")

    failure_stage: str | None = None
    if errors:
        if not trace_passed:
            failure_stage = "TRACE"
        elif failed_events:
            failure_stage = failed_events[0].split(":", maxsplit=4)[2]
        elif oracle_passed is False:
            failure_stage = "RESULT_ORACLE"
        else:
            failure_stage = "PUBLIC_ASSERTION"

    return (
        GoldenCaseResult(
            id=case.id,
            category=case.category,
            passed=not errors,
            session_id=session_id,
            response_types=tuple(response_types),
            run_ids=tuple(run_ids),
            run_statuses=tuple(run_statuses),
            run_error_codes=tuple(run_error_codes),
            trace_event_ids=tuple(trace_event_ids),
            trace_payload_fingerprints=tuple(trace_payload_fingerprints),
            failed_trace_events=tuple(failed_events),
            observed_tables=observed_tables,
            observed_columns=observed_columns,
            failure_stage=failure_stage,
            oracle_passed=oracle_passed,
            trace_passed=trace_passed,
            repair_count=max_repair_count,
            errors=tuple(errors),
        ),
        unauthorized,
        failed_synthesis,
        repair_bound,
        unexpected_clarifications,
        numeric_violations,
    )


def run_golden(
    *,
    client: TestClient,
    settings: Settings,
    suite: GoldenSuite,
    oracles: OracleSuite,
    environment: EvaluationEnvironment,
) -> GoldenReport:
    results: list[GoldenCaseResult] = []
    unauthorized = failed_synthesis = repair_bound = unexpected_clarifications = 0
    numeric_violations = 0
    for case in suite.cases:
        (
            result,
            unauthorized_count,
            synthesis_count,
            repair_count,
            clarification_count,
            numeric_count,
        ) = _run_case(
            client=client,
            settings=settings,
            case=case,
            oracles=oracles,
        )
        results.append(result)
        unauthorized += unauthorized_count
        failed_synthesis += synthesis_count
        repair_bound += repair_count
        unexpected_clarifications += clarification_count
        numeric_violations += numeric_count
        print(f"Golden {case.id}: {'PASS' if result.passed else 'FAIL'}")

    result_cases = [result for result in results if result.oracle_passed is not None]
    metrics = GoldenMetrics(
        case_count=len(results),
        result_case_count=len(result_cases),
        e2e_pass_rate=sum(result.passed for result in results) / len(results),
        result_oracle_pass_rate=(
            sum(result.oracle_passed is True for result in result_cases) / len(result_cases)
        ),
        trace_integrity_rate=sum(result.trace_passed for result in results) / len(results),
        unnecessary_clarification_rate=unexpected_clarifications / len(results),
        unauthorized_execution_count=unauthorized,
        failed_verification_synthesis_count=failed_synthesis,
        numeric_grounding_violation_count=numeric_violations,
        repair_bound_violation_count=repair_bound,
    )
    passed = (
        metrics.trace_integrity_rate == 1.0
        and metrics.unauthorized_execution_count == 0
        and metrics.failed_verification_synthesis_count == 0
        and metrics.numeric_grounding_violation_count == 0
        and metrics.repair_bound_violation_count == 0
        and metrics.e2e_pass_rate >= 0.90
        and metrics.result_oracle_pass_rate >= 0.90
        and metrics.unnecessary_clarification_rate <= 0.10
    )
    return GoldenReport(
        environment=environment,
        metrics=metrics,
        cases=tuple(results),
        passed=passed,
    )
