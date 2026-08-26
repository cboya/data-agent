"""Fail-closed M10 SQL guard and EXPLAIN failures."""


class SQLAdmissionError(RuntimeError):
    """Base M10 admission failure."""


class ExplainProviderError(SQLAdmissionError):
    """Harness-owned EXPLAIN could not be obtained safely."""

    def __init__(
        self,
        message: str,
        *,
        provider_errno: int | None = None,
        provider_sqlstate: str | None = None,
        safe_detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.provider_errno = provider_errno
        self.provider_sqlstate = provider_sqlstate
        self.safe_detail = safe_detail


class SQLGuardEvaluationError(SQLAdmissionError):
    """The standalone M10 evaluation corpus or run is invalid."""
