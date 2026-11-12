"""Anthropic: a failed call turned into the ``ProviderError`` it calls for (D104); the profile names ``map_error`` by text."""

from skye.base.exceptions import ProviderError
from skye.models.utilities.error_mapping import build_error, classify


def map_error(error: Exception, provider: str = "anthropic") -> ProviderError:
    """The ``ProviderError`` subclass for an error of an Anthropic client."""
    kind = classify(type(error).__name__, str(error))
    return build_error(
        "Anthropic API error",
        error,
        provider,
        kind,
        getattr(error, "status_code", None),
        getattr(error, "retry_after", None),
    )
