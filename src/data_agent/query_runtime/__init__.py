"""M11 capability-only read-only query runtime."""

from data_agent.query_runtime.errors import (
    CapabilityIntegrityError,
    DatabaseExecutionError,
    DatabaseUnavailableError,
    QueryTimeoutError,
    ResultDecodingError,
    RuntimeExecutionError,
    UnsupportedResultTypeError,
)
from data_agent.query_runtime.evidence import (
    ExecutionMetadata,
    ExecutionMetadataSink,
    ExecutionOutcome,
)
from data_agent.query_runtime.runtime import build_readonly_query_runtime
from data_agent.query_runtime.service import ReadOnlyQueryRuntime, RuntimeLimits

__all__ = [
    "CapabilityIntegrityError",
    "DatabaseExecutionError",
    "DatabaseUnavailableError",
    "ExecutionMetadata",
    "ExecutionMetadataSink",
    "ExecutionOutcome",
    "QueryTimeoutError",
    "ReadOnlyQueryRuntime",
    "ResultDecodingError",
    "RuntimeExecutionError",
    "RuntimeLimits",
    "UnsupportedResultTypeError",
    "build_readonly_query_runtime",
]
