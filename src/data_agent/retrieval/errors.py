"""Fail-closed error taxonomy for hybrid retrieval."""


class RetrievalError(RuntimeError):
    """Base class for retrieval projection, index, search, or evaluation failures."""


class RetrievalIndexError(RetrievalError):
    """A retrieval index could not be built or validated safely."""


class RetrievalIndexStaleError(RetrievalIndexError):
    """A valid index identity no longer matches current catalog/model authority."""


class RetrievalQueryError(RetrievalError):
    """A retrieval query or query embedding was invalid."""


class RetrievalEvaluationError(RetrievalError):
    """The standalone retrieval evaluation input or report was invalid."""
