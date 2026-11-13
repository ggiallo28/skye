# decision D104
"""Provider errors to the ``ProviderError`` subclass the failure calls for.

An error that is not already a ``ProviderError`` (one from a vendor SDK, a socket, a custom
adapter) is read for its HTTP status, its class name and its message, and becomes the same
subclass the standard-library HTTP layer raises for that response: ``RateLimitError`` (429),
``ServerError`` (5xx), ``ProviderTimeoutError`` (a timeout or a dropped connection),
``AuthenticationError`` (401, 403), ``BadRequestError`` (other 4xx, ``ContentPolicyError`` when
the body names a content policy). A known status code is decided by the rule of
``skye.base.http``, so there is one mapping; the class name and the message decide only when no
status is known. Every result keeps ``status_code``, ``provider``, ``retry_after`` and, in
``details``, an ``error_type`` classification.

What belongs to one provider is not here. The profile of a provider names its own handler in
``map_error`` (for a built-in one, ``errors.py`` in the folder of the provider, imported when an
error happens) and :meth:`ErrorHandler.wrap_provider_error` calls it first; a provider with no
handler gets the common mapping. A plugin gives ``map_error=`` in its ``ProviderProfile``.

Raises: nothing; a handler text that does not import raises ``ImportError`` at the first error.
Missing: a provider with no profile or no ``map_error`` gets the common mapping.
Concurrency: stateless; the imported handlers are cached.
"""

import functools
import importlib
import logging
from collections.abc import Callable
from typing import Any, TypeVar

from skye.base.exceptions import (
    AuthenticationError,
    ProviderError,
    ProviderTimeoutError,
    RateLimitError,
    ServerError,
)
from skye.base.http import _is_timeout, _status_class
from skye.base.plugins import get_registrar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

#: The subclass for a classification when no HTTP status is known.
_CLASS_OF_KIND: dict[str, type[ProviderError]] = {
    "rate_limit": RateLimitError,
    "timeout": ProviderTimeoutError,
    "connection_error": ProviderTimeoutError,
    "authentication_error": AuthenticationError,
    "permission_error": AuthenticationError,
    "service_unavailable": ServerError,
}


def error_class(status_code: int | None, kind: str, message: str = "") -> type[ProviderError]:
    """The ``ProviderError`` subclass for an HTTP status (the rule of ``skye.base.http``).

    Without a status, the classification (``rate_limit``, ``timeout``, ...) decides.
    """
    if isinstance(status_code, int) and status_code >= 400:
        return _status_class(status_code, message)
    return _CLASS_OF_KIND.get(kind, ProviderError)


def classify(error_type: str, message: str) -> str:
    """The classification that chat-completions clients share (class name and message)."""
    name, text = error_type.lower(), message.lower()
    if "ratelimit" in name or "rate_limit" in name or "rate_limit" in text:
        return "rate_limit"
    if "timeout" in name or "timeout" in text:
        return "timeout"
    if "connection" in name or "connection" in text:
        return "connection_error"
    if "auth" in name or "unauthorized" in text:
        return "authentication_error"
    if "api" in name:
        return "api_error"
    return "unknown_error"


def build_error(
    label: str,
    error: Exception,
    provider: str,
    kind: str,
    status_code: int | None = None,
    retry_after: float | None = None,
    **extra: Any,
) -> ProviderError:
    """Build the ``ProviderError`` subclass for ``error``, with ``label`` in the message."""
    message = str(error)
    cls = error_class(status_code, kind, message)
    if cls is ProviderError and _is_timeout(error):
        cls = ProviderTimeoutError
    return cls(
        f"{label}: {message}",
        provider=provider,
        status_code=status_code,
        retry_after=retry_after,
        error_type=kind,
        original_error_type=type(error).__name__,
        **extra,
    )


@functools.cache
def _resolve(text: str) -> Callable[..., ProviderError]:
    """The function that a ``"module:attribute"`` text names; it is imported at the first error."""
    module, _, attribute = text.partition(":")
    target: Any = importlib.import_module(module)
    for part in attribute.split("."):
        target = getattr(target, part)
    handler: Callable[..., ProviderError] = target
    return handler


def profile_handler(provider: str) -> Callable[..., ProviderError] | None:
    """The ``map_error`` of the profile of ``provider``, or ``None`` when there is none."""
    handler = getattr(get_registrar().get_profile(provider), "map_error", None)
    if isinstance(handler, str):
        return _resolve(handler)
    return handler  # a function, or None


class _HandlerByName(type):
    """Keep ``ErrorHandler.handle_<name>_error(error)``: it is the ``map_error`` of ``name``."""

    def __getattr__(cls, name: str) -> Callable[..., ProviderError]:
        if (
            name.startswith("handle_")
            and name.endswith("_error")
            and len(name) > len("handle__error")
        ):
            handler = profile_handler(name[len("handle_") : -len("_error")])
            if handler is not None:
                return handler
        raise AttributeError(f"type object 'ErrorHandler' has no attribute {name!r}")


# D104
class ErrorHandler(metaclass=_HandlerByName):
    """Turn provider errors into the ``ProviderError`` subclass each provider calls for."""

    @staticmethod
    def wrap_provider_error(
        error: Exception,
        provider: str,
    ) -> ProviderError:
        """Wrap a provider error in the ``ProviderError`` subclass it calls for.

        A ``ProviderError`` is returned as it is. Otherwise the ``map_error`` of the profile of
        ``provider`` is called, and a provider with none gets the common mapping.

        Args:
            error: The error to wrap
            provider: Provider name (the name its profile is registered under)

        Returns:
            The ``ProviderError`` subclass for the failure
        """
        if isinstance(error, ProviderError):
            return error

        handler = profile_handler(provider)
        if handler is not None:
            return handler(error, provider)
        kind = "timeout" if _is_timeout(error) else "unknown_error"
        return build_error(
            "Provider error", error, provider, kind, getattr(error, "status_code", None)
        )


__all__ = ["ErrorHandler", "build_error", "classify", "error_class", "profile_handler"]
