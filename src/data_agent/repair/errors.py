"""Typed M13 orchestration failures."""


class RepairError(RuntimeError):
    """Base M13 error."""


class RepairIntegrityError(RepairError):
    """Raised when failure evidence does not belong to the original planning branch."""
