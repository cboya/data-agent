import pytest
from pydantic import ValidationError

from data_agent.contracts import (
    CheckResult,
    ExecutionResult,
    ExplainResult,
    GuardStatus,
    SQLGuardResult,
    VerificationResult,
)


def test_execution_result_count_means_bounded_rows_returned() -> None:
    result = ExecutionResult(
        version="v0.1",
        columns=["region", "paid_amount"],
        rows=[["华东", "100.00"], ["华南", "80.00"]],
        returned_row_count=2,
        duration_ms=12,
        truncated=True,
    )

    assert result.returned_row_count == len(result.rows)
    assert "row_count" not in type(result).model_fields


@pytest.mark.parametrize(
    "overrides",
    [
        {"returned_row_count": 2, "rows": [["华东", "100.00"]]},
        {"returned_row_count": 1, "rows": [["华东"]]},
    ],
)
def test_execution_result_rejects_inconsistent_shape(overrides: dict[str, object]) -> None:
    values: dict[str, object] = {
        "version": "v0.1",
        "columns": ["region", "paid_amount"],
        "rows": [["华东", "100.00"]],
        "returned_row_count": 1,
        "duration_ms": 12,
        "truncated": False,
    }
    values.update(overrides)

    with pytest.raises(ValidationError):
        ExecutionResult.model_validate(values)


def test_guard_and_explain_statuses_are_self_consistent() -> None:
    with pytest.raises(ValidationError, match="PASSED"):
        SQLGuardResult(
            status=GuardStatus.PASSED,
            referenced_tables=["fact_order"],
            violations=["unexpected violation"],
        )

    with pytest.raises(ValidationError, match="rejection_reason"):
        ExplainResult(accepted=False, accesses=[])


def test_verification_status_matches_checks() -> None:
    failed_check = CheckResult(
        name="expected_columns",
        category="STRUCTURAL",
        passed=False,
        detail="paid_amount is missing",
    )

    with pytest.raises(ValidationError, match="PASSED"):
        VerificationResult(version="v0.1", status="PASSED", checks=[failed_check])

    result = VerificationResult(version="v0.1", status="FAILED", checks=[failed_check])
    assert result.status == "FAILED"
