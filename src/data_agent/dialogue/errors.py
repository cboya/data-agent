"""Typed fail-closed errors for M8 dialogue behavior."""


class DialogueError(RuntimeError):
    """Base error for requirement-understanding behavior."""


class DialogueContextError(DialogueError):
    """Raised when a bounded model context cannot be built safely."""


class RequirementMergeError(DialogueError):
    """Raised when a validated patch cannot be applied mechanically."""


class DialoguePolicyError(DialogueError):
    """Raised when the proposed action contradicts the merged requirement."""


class InvalidProviderEvidenceError(DialoguePolicyError):
    """Raised when structured provider evidence cannot authorize an M8 outcome."""

    def __init__(self, message: str, *, reason_codes: tuple[str, ...]) -> None:
        super().__init__(message)
        self.reason_codes = reason_codes
