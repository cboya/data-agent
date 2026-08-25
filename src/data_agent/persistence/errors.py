"""Fail-closed persistence error taxonomy."""


class PersistenceError(RuntimeError):
    """Base class for durable control-state failures."""


class RecordNotFoundError(PersistenceError):
    """Raised when a requested durable record does not exist."""


class DuplicateRecordError(PersistenceError):
    """Raised when an immutable identifier has already been persisted."""


class OptimisticConcurrencyError(PersistenceError):
    """Raised when a stale Session revision would overwrite newer state."""


class CorruptRecordError(PersistenceError):
    """Raised when a database row cannot be rebuilt as a valid domain value."""


class PersistenceInvariantError(PersistenceError):
    """Raised when a write would violate a durable-state invariant."""


class MigrationDriftError(PersistenceError):
    """Raised when an applied migration no longer matches repository content."""
