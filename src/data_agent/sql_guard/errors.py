"""Fail-closed M10 SQL guard and EXPLAIN failures."""


class SQLAdmissionError(RuntimeError):
    """Base M10 admission failure."""


class ExplainProviderError(SQLAdmissionError):
    """Harness-owned EXPLAIN could not be obtained safely."""


class SQLGuardEvaluationError(SQLAdmissionError):
    """The standalone M10 evaluation corpus or run is invalid."""
