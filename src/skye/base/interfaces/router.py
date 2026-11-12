"""Model router interface for load balancing and fallbacks.

This module defines the abstract interface for model routing with support
for multiple routing strategies, health tracking, and fallback mechanisms.

Inspired by LiteLLM's Router, this interface supports:
- Multiple routing strategies (round-robin, least-busy, cost-based, latency-based, usage-based)
- Rate limit tracking (TPM/RPM) with Redis support
- Cooldown mechanisms for failed deployments
- Retry policies per error type
- Allowed fails policies before cooldown
- Fallback chains with context window awareness
- Pre-call checks for rate limits
- Tag-based routing for access control

Raises: ValueError when neither a model nor tags are given or no model matches; ProviderError when every target fails.
Missing: an unknown model id raises; a model with no health data reports a healthy default.
Concurrency: async methods run on the event loop; health, cooldown and rate-limit state is shared across tasks and lives in the storage backend.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from skye.base.completion import CompleteRequest, CompleteResponse



class RoutingStrategy(Enum):
    """Routing strategies for model selection.

    Inspired by LiteLLM's routing strategies. ``ModelRouter`` uses ``ROUND_ROBIN`` unless told otherwise, and a
    route with no strategy of its own uses the router's.

    - ROUND_ROBIN: Each target in turn
    - SIMPLE_SHUFFLE: Random selection
    - LEAST_BUSY: Route to deployment with fewest active requests
    - RATE_LIMIT_AWARE: Route to deployment with lowest TPM/RPM usage (async rate-limit aware)
    - LATENCY_BASED: Route to deployment with lowest latency
    - COST_BASED: Route to deployment with lowest ``cost_per_1k_*_tokens``
    - WEIGHTED: Weighted random selection based on model weights
    - PRIORITY_BASED: Route to the deployment with the highest success rate
    """

    SIMPLE_SHUFFLE = "simple_shuffle"
    ROUND_ROBIN = "round_robin"
    LEAST_BUSY = "least_busy"
    RATE_LIMIT_AWARE = "rate_limit_aware"  # Routes to deployment with lowest TPM/RPM usage
    LATENCY_BASED = "latency_based"
    COST_BASED = "cost_based"
    WEIGHTED = "weighted"
    PRIORITY_BASED = "priority_based"


class ModelSelectionInterface(ABC):
    """Selection role of a model router: register models, choose one for a request and run the request."""

    @abstractmethod
    def register_model(self, model_id: str, model: Any) -> None:
        """Register a model with the router.

        Args:
            model_id: Unique identifier for the model.
            model: The model instance implementing ModelInterface.
        """
        pass

    @abstractmethod
    async def select_model(self, request: CompleteRequest) -> str:
        """Select a model for the request based on routing strategy (async: health and limits may live in a shared store).

        Args:
            request: The completion request.

        Returns:
            The selected model ID.
        """
        pass

    @abstractmethod
    def complete(
        self,
        messages: list[Any],
        model: str | None = None,
        tags: list[str] | None = None,
        **kwargs: Any
    ) -> CompleteResponse:
        """Complete a request using the router.

        This method provides a unified interface for routing with flexible model
        and tag-based selection. At least one of model or tags must be provided.

        Args:
            messages: List of messages for the completion.
            model: Model name or alias to use for completion (optional).
            tags: Tags to filter models by (optional).
            **kwargs: Additional completion parameters.

        Returns:
            The completion response from the selected model.

        Raises:
            ValueError: If neither model nor tags are provided, or if no models
                match the specified criteria.

        Examples:
            >>> # Use specific model/alias
            >>> response = router.complete(
            ...     messages=[UserMessage("Hello!")],
            ...     model="gpt-4"
            ... )
            >>>
            >>> # Use tag-based selection
            >>> response = router.complete(
            ...     messages=[UserMessage("Hello!")],
            ...     tags=["paid", "premium"]
            ... )
            >>>
            >>> # Use both model and tags (model must have all tags)
            >>> response = router.complete(
            ...     messages=[UserMessage("Hello!")],
            ...     model="gpt-4",
            ...     tags=["premium"]
            ... )
        """
        pass

    @abstractmethod
    async def acomplete(
        self,
        messages: list[Any],
        model: str | None = None,
        tags: list[str] | None = None,
        **kwargs: Any
    ) -> CompleteResponse:
        """Complete a request using the router asynchronously.

        Args:
            messages: List of messages for the completion.
            model: Model name or alias to use for completion (optional).
            tags: Tags to filter models by (optional).
            **kwargs: Additional completion parameters.

        Returns:
            The completion response from the selected model.

        Raises:
            ValueError: If neither model nor tags are provided, or if no models
                match the specified criteria.
        """
        pass


class ModelHealthInterface(ABC):
    """Health role of a model router: failures, cooldown and usage of each model."""

    @abstractmethod
    def mark_model_failed(self, model_id: str) -> None:
        """Mark a model as failed for cooldown.

        Args:
            model_id: The model that failed.
        """
        pass

    @abstractmethod
    def get_model_health(self, model_id: str) -> Any:
        """Get health status of a model.

        Args:
            model_id: The model to check.

        Returns:
            ModelHealthMetrics object containing health metrics.

        Example:
            >>> health = router.get_model_health("gpt-4")
            >>> print(f"Success rate: {health.success_rate:.1%}")
        """
        pass

    @abstractmethod
    def get_usage_stats(self, model_id: str) -> Any:
        """Get current usage statistics for a model.

        Returns TPM/RPM usage, active requests, and other metrics.

        Args:
            model_id: The model deployment ID.

        Returns:
            UsageStats object with usage statistics.

        Example:
            >>> stats = router.get_usage_stats("gpt-4-deployment-1")
            >>> print(f"TPM used: {stats.tpm_used}")
        """
        pass

    @abstractmethod
    def get_cooldown_models(self) -> list[Any]:
        """Get list of models currently in cooldown.

        Returns:
            List of CooldownInfo objects with cooldown information.

        Example:
            >>> cooled_down = router.get_cooldown_models()
            >>> for info in cooled_down:
            ...     print(f"{info.model_id} cooled down until {info.cooldown_until}")
        """
        pass


class RouterConfigurationInterface(ABC):
    """Configuration role of a model router: strategy, fallbacks, retry and failure policies, cooldown, rate limits and tags."""

    @abstractmethod
    def set_routing_strategy(self, strategy: RoutingStrategy | str) -> None:
        """Set the routing strategy.

        Args:
            strategy: The routing strategy to use: a ``RoutingStrategy``, or the name of a strategy that a plugin registered.
        """
        pass

    @abstractmethod
    def set_fallbacks(self, fallbacks: list[Any]) -> None:
        """Set fallback model chains.

        Inspired by LiteLLM's fallback system, this allows defining fallback
        chains that are tried when primary models fail.

        Args:
            fallbacks: List of FallbackConfig objects defining fallback chains.

        Example:
            >>> from skye.router import FallbackConfig
            >>> router.set_fallbacks([
            ...     FallbackConfig(
            ...         primary="gpt-4",
            ...         fallbacks=["gpt-3.5-turbo", "claude-3-sonnet"]
            ...     )
            ... ])
        """
        pass

    @abstractmethod
    def set_retry_policy(self, retry_policies: list[Any]) -> None:
        """Set retry policy per error type.

        Inspired by LiteLLM's RetryPolicy, this allows setting custom retry
        counts for different error types.

        Args:
            retry_policies: List of RetryPolicyConfig objects.

        Example:
            >>> from skye.router import RetryPolicyConfig
            >>> router.set_retry_policy([
            ...     RetryPolicyConfig(error_type="RateLimitError", max_retries=3),
            ...     RetryPolicyConfig(error_type="ProviderTimeoutError", max_retries=2)
            ... ])
        """
        pass

    @abstractmethod
    def set_allowed_fails_policy(self, allowed_fails_policies: list[Any]) -> None:
        """Set allowed fails before cooldown per error type.

        Inspired by LiteLLM's AllowedFailsPolicy, this sets how many failures
        of each type are allowed per minute before cooling down a deployment.

        Args:
            allowed_fails_policies: List of AllowedFailsPolicyConfig objects.

        Example:
            >>> from skye.router import AllowedFailsPolicyConfig
            >>> router.set_allowed_fails_policy([
            ...     AllowedFailsPolicyConfig(
            ...         error_type="RateLimitError",
            ...         allowed_fails_per_minute=100
            ...     )
            ... ])
        """
        pass

    @abstractmethod
    def set_cooldown_time(self, cooldown_seconds: float) -> None:
        """Set cooldown duration for failed models.

        Args:
            cooldown_seconds: Duration in seconds to cool down failed models.

        Example:
            >>> router.set_cooldown_time(60.0)  # 60 second cooldown
        """
        pass

    @abstractmethod
    def enable_pre_call_checks(self, enabled: bool = True) -> None:
        """Enable/disable pre-call rate limit checks.

        Inspired by LiteLLM's enable_pre_call_check, this filters out
        deployments that have exceeded their TPM/RPM limits before making calls.

        Args:
            enabled: Whether to enable pre-call checks.

        Example:
            >>> router.enable_pre_call_checks(True)
        """
        pass

    @abstractmethod
    def set_rate_limits(
        self, model_id: str, tpm: int | None = None, rpm: int | None = None
    ) -> None:
        """Set rate limits for a model deployment.

        Inspired by LiteLLM's TPM/RPM tracking, this sets tokens-per-minute
        and requests-per-minute limits for a deployment.

        Args:
            model_id: The model deployment ID.
            tpm: Tokens per minute limit (None for unlimited).
            rpm: Requests per minute limit (None for unlimited).

        Example:
            >>> router.set_rate_limits("gpt-4-deployment-1", tpm=100000, rpm=1000)
        """
        pass

    @abstractmethod
    def set_model_tags(self, model_id: str, tags: list[str]) -> None:
        """Set tags for a model deployment (for tag-based routing).

        Inspired by LiteLLM's tag-based routing, this enables access control
        and routing based on tags (e.g., "free", "paid", "team-a").

        Args:
            model_id: The model deployment ID.
            tags: List of tags to assign.

        Example:
            >>> router.set_model_tags("gpt-4-paid", ["paid", "premium"])
            >>> router.set_model_tags("gpt-3.5-free", ["free", "basic"])
        """
        pass


class ModelRouterInterface(ModelSelectionInterface, ModelHealthInterface, RouterConfigurationInterface):
    """Abstract interface for model routing.

    This interface defines the contract for routing requests to multiple
    models with support for load balancing, fallbacks, and health tracking.
    """

