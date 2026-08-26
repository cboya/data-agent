"""Typed fail-closed M14 answer errors."""


class AnswerError(RuntimeError):
    """Base answer-layer error."""


class AnswerIntegrityError(AnswerError):
    """Raised when synthesis inputs do not form one final verified branch."""


class AnswerGroundingError(AnswerError):
    """Raised when model language escapes exact verified evidence."""
