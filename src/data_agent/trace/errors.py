"""Fail-closed M15 trace error taxonomy."""


class TraceError(RuntimeError):
    """Base error for trace construction, persistence, or validation."""


class TracePayloadError(TraceError):
    """A trace payload is unsafe, unbounded, or not canonical."""


class TraceIntegrityError(TraceError):
    """A persisted Run trace is incomplete or internally inconsistent."""
