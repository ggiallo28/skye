"""Configuration models for the model router.

This module contains all validated dataclasses used for router configuration, including targets,
routes, fallbacks, and policies.
"""

import dataclasses
from collections.abc import Mapping
from typing import Any

from skye.base.interfaces.router import RoutingStrategy
from skye.base.validated import Validated, field, validated


@validated
class ModelTarget(Validated):
    """A single model target/endpoint configuration.

    Args:
        model: Actual model identifier (e.g., "gpt-4", "azure/chatgpt-v-2")
        provider: Provider name (e.g., "openai", "azure", "bedrock")
        api_key: API key for authentication (optional)
        api_base: Base URL for API calls (optional)
        api_version: API version (optional, for Azure)
        region: Region for the deployment (optional)
        timeout: Request timeout in seconds (optional)
        max_retries: Retries of this target for an error type the retry policy retries; it replaces
            the policy's count for this target (optional; an error type the policy does not retry is
            never retried)
        weight: Weight for weighted routing (optional)
        tpm: Tokens per minute limit (optional)
        rpm: Requests per minute limit (optional)
        cost_per_1k_prompt_tokens: Price of 1000 prompt tokens, read by ``cost_based`` (optional)
        cost_per_1k_completion_tokens: Price of 1000 completion tokens, read by ``cost_based``
            (optional)
        tags: Tags for tag-based routing (optional)
        metadata: Additional metadata, not read by the router (optional)
        options: Keyword arguments passed as they are to the provider client, after the fields
            above, for what a provider needs and the target has no field for: ``project_id`` and
            ``location`` of Google, ``azure_endpoint`` or ``deployment_name`` of Azure (optional).
            ``${NAME}`` in a string value is replaced by the variable.

    Example:
        >>> target = ModelTarget(
        ...     model="azure/chatgpt-v-2",
        ...     provider="azure",
        ...     api_key="${AZURE_API_KEY}",  # Env var substitution
        ...     api_base="https://my-resource.openai.azure.com",
        ...     api_version="2024-02-15-preview",
        ...     region="us-east-1",
        ...     tpm=100000,
        ...     rpm=1000,
        ...     tags=["premium", "paid"]
        ... )
    """

    model: str = field(description="Actual model identifier")
    provider: str = field(description="Provider name")
    api_key: str | None = field(default=None, description="API key for authentication")
    api_base: str | None = field(default=None, description="Base URL for API calls")
    api_version: str | None = field(default=None, description="API version")
    region: str | None = field(default=None, description="Deployment region")
    timeout: float | None = field(default=None, description="Request timeout in seconds")
    max_retries: int | None = field(
        default=None, ge=0, description="Retries of this target, replacing the policy's count"
    )
    weight: float = field(default=1.0, description="Weight for weighted routing")
    tpm: int | None = field(default=None, description="Tokens per minute limit")
    rpm: int | None = field(default=None, description="Requests per minute limit")
    cost_per_1k_prompt_tokens: float | None = field(
        default=None, ge=0, description="Price of 1000 prompt tokens (cost_based)"
    )
    cost_per_1k_completion_tokens: float | None = field(
        default=None, ge=0, description="Price of 1000 completion tokens (cost_based)"
    )
    tags: list[str] = field(default_factory=list, description="Tags for routing")
    metadata: dict[str, Any] = field(default_factory=dict, description="Additional metadata")
    options: dict[str, Any] = field(
        default_factory=dict, description="Keyword arguments passed to the provider client"
    )

    extras: dict[str, Any] = field(default_factory=dict, init=False, repr=False, compare=False)
    #: The fields that were written with ``${NAME}``, as written (the value itself is already
    # substituted); used to export a
    #: router without its secrets (``ModelRouter.to_config``, ``to_skye``).
    env_refs: dict[str, str] = field(default_factory=dict, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Validate the fields, then substitute ${VAR_NAME} patterns in the declared string fields."""
        super().__post_init__()
        self._substitute_env_vars()

    def _substitute_env_vars(self) -> None:
        """Substitute ${VAR_NAME} patterns with environment variables in string fields.

        This method processes all declared string fields and replaces environment variable
        references with their actual values. It uses the substitute_env_vars function from
        skye.base.config. Extra fields are kept as given.

        Raises:
            ConfigurationError: If a referenced environment variable is not found.
        """
        from skye.base.config import substitute_env_vars

        for f in dataclasses.fields(self):
            value = getattr(self, f.name)
            if f.init and isinstance(value, str):
                substituted = substitute_env_vars(value)
                if substituted != value:
                    self.env_refs[f.name] = value
                setattr(self, f.name, substituted)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ModelTarget":
        """Build a target from a mapping; keys that are not declared fields are kept as extra fields."""
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        """The declared fields and the extra fields as plain dicts and lists."""
        dumped = super().to_dict()
        dumped.pop("extras", None)
        dumped.update(self.extras)
        return dumped


_declared_init = ModelTarget.__init__


def _init_with_extras(self: ModelTarget, **kwargs: Any) -> None:
    """Accept keyword arguments the class does not declare and keep them as attributes (``extras``)."""
    names = {f.name for f in dataclasses.fields(ModelTarget) if f.init}
    extras = {key: kwargs.pop(key) for key in list(kwargs) if key not in names}
    _declared_init(self, **kwargs)
    self.extras.update(extras)
    for key, value in extras.items():
        setattr(self, key, value)


_init_with_extras.__doc__ = _declared_init.__doc__
ModelTarget.__init__ = _init_with_extras  # type: ignore[method-assign]


def _ignore_unknown_keywords(cls: type) -> type:
    """Make a configuration class drop keyword arguments it does not declare (unknown keys in a file are ignored)."""
    declared_init = cls.__init__  # type: ignore[misc]

    def init(self: Any, **kwargs: Any) -> None:
        names = {f.name for f in dataclasses.fields(cls) if f.init}
        declared_init(self, **{key: value for key, value in kwargs.items() if key in names})

    init.__doc__ = declared_init.__doc__
    cls.__init__ = init  # type: ignore[misc]
    return cls


@_ignore_unknown_keywords
@validated
class RouteConfig(Validated):
    """Configuration for a route with one or more targets.

    A route defines an alias that maps to one or more model targets. When multiple targets are
    defined, the routing strategy determines which target to use.

    Args:
        alias: Alias name for this route (e.g., "fast", "gpt-3.5-turbo")
        targets: List of model targets for this route
        strategy: Strategy for selecting between targets; ``None`` (the default) uses the router's
            strategy
        fallback_on_error: When the selected target fails (after its retries), try the other
            available targets of this route before the fallback chain (default ``True``); ``False``
            goes straight to the fallback chain

    Example:
        >>> route = RouteConfig(
        ...     alias="gpt-3.5-turbo",
        ...     targets=[
        ...         ModelTarget(model="azure/chatgpt-v-2", provider="azure", api_key="..."),
        ...         ModelTarget(model="gpt-3.5-turbo", provider="openai", api_key="...")
        ...     ],
        ...     strategy=RoutingStrategy.ROUND_ROBIN,
        ...     fallback_on_error=True
        ... )
    """

    alias: str = field(description="Alias name for this route")
    targets: list[ModelTarget] = field(min_length=1, description="Model targets")
    strategy: RoutingStrategy | str | None = field(
        default=None,
        description="Routing strategy: a RoutingStrategy or a registered name (None: the router's)",
    )
    fallback_on_error: bool = field(
        default=True, description="Try the other targets of the route on error"
    )


@_ignore_unknown_keywords
@validated
class FallbackConfig(Validated):
    """Configuration for fallback chains.

    Defines which models to try if the primary model fails.

    Args:
        primary: Primary model ID
        fallbacks: List of fallback model IDs to try in order

    Example:
        >>> fallback = FallbackConfig(
        ...     primary="gpt-4",
        ...     fallbacks=["gpt-3.5-turbo", "claude-3-sonnet"]
        ... )
    """

    primary: str = field(description="Primary model ID")
    fallbacks: list[str] = field(min_length=1, description="Fallback model IDs")


@_ignore_unknown_keywords
@validated
class RetryPolicyConfig(Validated):
    """Configuration for retry policies per error type.

    Defines how many times the router retries the same target for one kind of error, and how long it
    waits first. The error type is the name of an error class; it matches that class and its
    subclasses (``ProviderError`` matches every provider error, the most specific name wins).

    Args:
        error_type: Name of an error class (e.g., "RateLimitError", "ServerError",
            "ProviderTimeoutError")
        max_retries: Maximum number of retry attempts
        retry_after_seconds: Wait before each retry, in seconds (``None``: no wait of its own). The
            error's own ``retry_after`` (the provider's ``Retry-After``) wins when it is longer.
        exponential_backoff: Double the wait after each retry (1x, 2x, 4x, ...)

    Example:
        >>> policy = RetryPolicyConfig(
        ...     error_type="RateLimitError",
        ...     max_retries=3,
        ...     retry_after_seconds=1.0,
        ...     exponential_backoff=True,
        ... )
    """

    error_type: str = field(description="Error type")
    max_retries: int = field(ge=0, description="Maximum retry attempts")
    retry_after_seconds: float | None = field(
        default=None, ge=0, description="Wait before each retry, in seconds"
    )
    exponential_backoff: bool = field(default=False, description="Double the wait each retry")


@_ignore_unknown_keywords
@validated
class AllowedFailsPolicyConfig(Validated):
    """Configuration for allowed fails before cooldown.

    Defines how many failures of each type are allowed per minute before cooling down a deployment.

    Args:
        error_type: Name of an error class; it matches that class and its subclasses, as in
            ``RetryPolicyConfig``
        allowed_fails_per_minute: Number of failures allowed per minute

    Example:
        >>> policy = AllowedFailsPolicyConfig(
        ...     error_type="RateLimitError",
        ...     allowed_fails_per_minute=100
        ... )
    """

    error_type: str = field(description="Error type")
    allowed_fails_per_minute: int = field(ge=0, description="Allowed failures per minute")


@validated
class ModelHealthMetrics(Validated):
    """Health metrics for a model.

    Contains comprehensive health and performance metrics.

    Example:
        >>> metrics = ModelHealthMetrics(
        ...     model_id="gpt-4",
        ...     success_count=100,
        ...     failure_count=5,
        ...     total_requests=105,
        ...     success_rate=0.952,
        ...     average_latency_ms=250.5
        ... )
    """

    model_id: str = field(description="Model identifier")
    success_count: int = field(default=0, ge=0, description="Number of successful requests")
    failure_count: int = field(default=0, ge=0, description="Number of failed requests")
    total_requests: int = field(default=0, ge=0, description="Total requests")
    success_rate: float = field(default=0.0, ge=0.0, le=1.0, description="Success rate (0.0-1.0)")
    average_latency_ms: float = field(default=0.0, ge=0.0, description="Average latency in ms")
    min_latency_ms: float | None = field(default=None, description="Minimum latency in ms")
    max_latency_ms: float | None = field(default=None, description="Maximum latency in ms")
    last_success_time: float | None = field(default=None, description="Last success timestamp")
    last_failure_time: float | None = field(default=None, description="Last failure timestamp")
    is_in_cooldown: bool = field(default=False, description="Whether model is in cooldown")
    cooldown_until: float | None = field(default=None, description="Cooldown end timestamp")
    failure_reasons: dict[str, int] = field(
        default_factory=dict, description="Failure counts by reason"
    )
    active_requests: int = field(default=0, ge=0, description="Currently active requests")
    tags: list[str] = field(default_factory=list, description="Model tags")


@validated
class UsageStats(Validated):
    """Usage statistics for a model.

    Contains rate limit usage and request statistics.

    Example:
        >>> stats = UsageStats(
        ...     model_id="gpt-4",
        ...     tpm_used=50000,
        ...     tpm_limit=100000,
        ...     rpm_used=250,
        ...     rpm_limit=1000
        ... )
    """

    model_id: str = field(description="Model identifier")
    tpm_used: int = field(default=0, ge=0, description="Tokens used this minute")
    tpm_limit: int | None = field(default=None, description="Tokens per minute limit")
    rpm_used: int = field(default=0, ge=0, description="Requests made this minute")
    rpm_limit: int | None = field(default=None, description="Requests per minute limit")
    active_requests: int = field(default=0, ge=0, description="Currently active requests")
    total_requests: int = field(default=0, ge=0, description="Total requests made")
    total_failures: int = field(default=0, ge=0, description="Total failures")


@validated
class CooldownInfo(Validated):
    """Information about a model in cooldown.

    Example:
        >>> info = CooldownInfo(
        ...     model_id="gpt-4",
        ...     cooldown_until=1234567890.0,
        ...     reason="RateLimitError"
        ... )
    """

    model_id: str = field(description="Model identifier")
    cooldown_until: float = field(description="Cooldown end timestamp")
    reason: str = field(description="Reason for cooldown")
