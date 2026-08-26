"""Typed fail-closed errors for bounded M11 execution."""

from __future__ import annotations


class RuntimeExecutionError(RuntimeError):
    """Base error exposed by the provider-neutral query runtime."""

    code = "RUNTIME_EXECUTION_ERROR"

    def __init__(self, message: str, *, safe_detail: str | None = None) -> None:
        super().__init__(message)
        self.safe_detail = safe_detail


class CapabilityIntegrityError(RuntimeExecutionError):
    code = "CAPABILITY_INTEGRITY_ERROR"


class QueryTimeoutError(RuntimeExecutionError):
    code = "QUERY_TIMEOUT"


class DatabaseUnavailableError(RuntimeExecutionError):
    code = "DATABASE_UNAVAILABLE"


class DatabaseExecutionError(RuntimeExecutionError):
    code = "DATABASE_EXECUTION_ERROR"


class ResultDecodingError(RuntimeExecutionError):
    code = "RESULT_DECODING_ERROR"


class UnsupportedResultTypeError(ResultDecodingError):
    code = "UNSUPPORTED_RESULT_TYPE"
