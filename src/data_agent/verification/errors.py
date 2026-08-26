"""Typed fail-closed errors for deterministic M12 verification."""


class VerificationError(RuntimeError):
    """Base error for the provider-free verification boundary."""


class VerificationIntegrityError(VerificationError):
    """The supplied objects do not form one trustworthy evidence chain."""
