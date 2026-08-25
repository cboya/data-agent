"""Fail-closed error taxonomy for model runtime adapters."""


class ModelAdapterError(RuntimeError):
    """Base class for provider adapter failures."""


class ModelTransportError(ModelAdapterError):
    """The configured model runtime could not be reached reliably."""


class ModelTimeoutError(ModelTransportError):
    """A model runtime request exceeded its configured timeout."""


class ModelResponseError(ModelAdapterError):
    """The provider returned a malformed or unsuccessful response envelope."""


class ModelUnavailableError(ModelAdapterError):
    """A configured model is absent or lacks its required capability."""


class ModelContractError(ModelAdapterError):
    """Model output failed the requested domain contract."""
