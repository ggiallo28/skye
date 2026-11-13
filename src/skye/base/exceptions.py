# decision D105
"""Custom exceptions for Skye.

This module defines the exception hierarchy for the Skye GenAI platform.
All Skye-specific exceptions inherit from SkyeError.

An error never logs itself: creating one emits no log record; the code that
handles an error logs it once, with structured ``extra``.
"""

from typing import Any


class SkyeError(Exception):
    """Base exception for all Skye errors.

    All Skye-specific exceptions should inherit from this class.
    This allows users to catch all Skye errors with a single except clause.

    Args:
        message: Human-readable error message
        details: Optional dictionary containing additional error context

    Attributes:
        message: The error message
        details: Dictionary with additional error information
    """

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        """Initialize SkyeError with message and optional details.

        Args:
            message: Human-readable error message
            details: Optional dictionary containing additional error context
        """
        self.message = message
        self.details = details or {}
        super().__init__(self.message)

    def __str__(self) -> str:
        """Return string representation of the error."""
        if self.details:
            return f"{self.message} | Details: {self.details}"
        return self.message

    def __repr__(self) -> str:
        """Return detailed representation of the error."""
        return f"{self.__class__.__name__}(message={self.message!r}, details={self.details!r})"


# decision D104
class ProviderError(SkyeError):
    """Error from an LLM provider.

    Raised when an error occurs during communication with an LLM provider
    (e.g., OpenAI, Anthropic, AWS Bedrock). The HTTP layer raises the subclass that the response
    calls for: :class:`RateLimitError`, :class:`ServerError`,
    :class:`ProviderTimeoutError`, :class:`AuthenticationError`, :class:`BadRequestError` (and
    its :class:`ContentPolicyError`); a failure that fits none of them is a plain
    ``ProviderError``, so ``except ProviderError`` catches every one.

    Args:
        message: Human-readable error message
        provider: Name of the provider that raised the error
        status_code: Optional HTTP status code from the provider
        retry_after: Seconds the provider asked to wait before retrying (its ``Retry-After``
            header), or ``None`` when it did not say
        **kwargs: Additional context to include in details

    Attributes:
        provider: Name of the provider that raised the error.
        status_code: The HTTP status code, or ``None`` (no response).
        retry_after: Seconds to wait before retrying, or ``None``.
    """

    def __init__(
        self,
        message: str,
        provider: str,
        status_code: int | None = None,
        *,
        retry_after: float | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize ProviderError with provider context."""
        details = {"provider": provider, "status_code": status_code, **kwargs}
        if retry_after is not None:
            details["retry_after"] = retry_after
        super().__init__(message, details)
        self.provider = provider
        self.status_code = status_code
        self.retry_after = retry_after


class RateLimitError(ProviderError):
    """The provider refused the request because of a rate limit or quota (HTTP 429).

    Retryable: wait ``retry_after`` seconds when the provider gave it.
    """


class ServerError(ProviderError):
    """The provider failed on its side (HTTP 5xx). Retryable."""


class ProviderTimeoutError(ProviderError):
    """The request timed out or the connection dropped before a response (no ``status_code``).

    Retryable.
    """


class AuthenticationError(ProviderError):
    """The provider refused the credential (HTTP 401) or the permission (HTTP 403).

    Not retryable.
    """


class BadRequestError(ProviderError):
    """The provider refused the request itself (any other HTTP 4xx). Not retryable."""


class ContentPolicyError(BadRequestError):
    """The provider refused the request under its content policy (a 4xx whose body says so).

    Detected by the HTTP layer when the error body contains ``content_policy``,
    ``content_filter``, ``content policy`` or ``content management policy`` (case-insensitive):
    the markers OpenAI and Azure OpenAI send. Not retryable on the same model.
    """


# Requirement 26.3
class UnsupportedModalityError(ProviderError):
    """The input has a form the provider does not accept.

    Raised by the adapter before anything is sent, so there is no ``status_code``; the input is
    left unchanged. Not retryable: sending it again fails the same way.

    Args:
        message: Human-readable message that names the modality.
        provider: Name of the provider that does not support it.
        modality: The modality or form refused, for example ``"image"``.
        **kwargs: Additional context to include in details.

    Attributes:
        modality: The modality or form refused.
    """

    def __init__(self, message: str, provider: str, modality: str, **kwargs: Any) -> None:
        """Initialize with the provider and the refused modality."""
        super().__init__(message, provider, modality=modality, **kwargs)
        self.modality = modality


# decision D109
class CapabilityChoiceError(ProviderError):
    """The model answered without the capability call the request forced.

    Raised only for a model that refuses a forced ``capability_choice``: Skye asked for the call in
    an instruction, tried twice, and got an answer without it. There is no ``status_code`` (both
    calls succeeded). Not retried by the client; a router may fall back to another model.

    Attributes:
        capability_choice: ``"required"`` or the capability name that was asked for.
    """

    def __init__(self, message: str, provider: str, capability_choice: str, **kwargs: Any) -> None:
        """Initialize with the provider and the choice asked for."""
        super().__init__(message, provider, capability_choice=capability_choice, **kwargs)
        self.capability_choice = capability_choice


class ConfigurationError(SkyeError):
    """Error in configuration.

    Raised when there's an issue with configuration values, missing required
    configuration, or invalid configuration format.

    Args:
        message: Human-readable error message
        details: Optional dictionary containing additional error context
    """

    pass


class ValidationError(SkyeError, ValueError):
    """Error in data validation.

    Raised when data fails validation: a field of a model cannot be read as its type or breaks a
    constraint, or an interface compliance check fails. It is also a ``ValueError``, so code that
    catches ``ValueError`` keeps working.

    Args:
        message: Human-readable error message
        field: Name of the field that failed validation
        value: The invalid value that was provided
        **kwargs: Additional context to include in details
    """

    def __init__(self, message: str, field: str, value: Any, **kwargs: Any) -> None:
        """Initialize ValidationError with field information."""
        details = {"field": field, "value": value, **kwargs}
        super().__init__(message, details)


class CapabilityError(SkyeError):
    """Base exception for capability-related errors.

    All capability-specific exceptions inherit from this class.

    Args:
        message: Human-readable error message
        details: Optional dictionary containing additional error context
    """


class CapabilityExecutionError(CapabilityError):
    """Error during capability execution.

    Raised when a capability fails to execute properly.

    Args:
        message: Human-readable error message
        capability_name: Name of the capability that failed
        **kwargs: Additional context to include in details
    """

    def __init__(self, message: str, capability_name: str, **kwargs: Any) -> None:
        """Initialize CapabilityExecutionError with capability context."""
        details = {"capability_name": capability_name, **kwargs}
        super().__init__(message, details)


class MissingExtraError(SkyeError, ImportError):
    """An optional dependency is absent because its Extra is not installed.

    Wraps the underlying ``ImportError``/``ModuleNotFoundError`` (as
    ``__cause__`` when raised ``from``) and names the missing Extra. It also
    subclasses ``ImportError`` so pre-existing ``except ImportError`` call sites
    keep working.

    Args:
        extra: Name of the Extra that provides the missing module
        missing: Name of the module that could not be imported
        package: Optional pip package name (defaults to ``missing``)
    """

    def __init__(self, extra: str, missing: str, package: str | None = None) -> None:
        """Initialize MissingExtraError with the Extra and module names."""
        pkg = package or missing
        self.extra = extra
        self.missing = missing
        self.package = pkg
        message = (
            f"The '{missing}' package is required but not installed.\n"
            f"Install it with: pip install {pkg}\n"
            f"Or install the skye extra: pip install skyeai[{extra}]"
        )
        SkyeError.__init__(self, message, {"extra": extra, "missing": missing, "package": pkg})
        self.name = missing
