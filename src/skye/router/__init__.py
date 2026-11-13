"""Routes package for unified model routing and load balancing.

This package provides a comprehensive routing solution with support for:
- Model aliases with multiple targets
- Health tracking and metrics
- Rate limiting (TPM/RPM)
- Multiple routing strategies
- Fallback chains, also when no target of an alias is available
- Retry policies per error class (``RateLimitError``, ``ServerError``, ...), with waits
- Tag-based routing
- Cooldown mechanisms
- Any backend of ``skye.store`` (in memory by default; Redis, DynamoDB, ... passed explicitly)

Example (With Aliases):
    >>> from skye.router import ModelRouter, ModelTarget, RouteConfig
    >>> from skye.base.interfaces.router import RoutingStrategy
    >>>
    >>> # Define routes with aliases and multiple targets
    >>> router = ModelRouter(routes=[
    ...     RouteConfig(
    ...         alias="gpt-3.5-turbo",
    ...         targets=[
    ...             ModelTarget(
    ...                 model="azure/chatgpt-v-2",
    ...                 provider="azure",
    ...                 api_key="...",
    ...                 tpm=100000,
    ...                 rpm=1000
    ...             ),
    ...             ModelTarget(
    ...                 model="gpt-3.5-turbo",
    ...                 provider="openai",
    ...                 api_key="...",
    ...                 tpm=200000,
    ...                 rpm=2000
    ...             )
    ...         ],
    ...         strategy=RoutingStrategy.RATE_LIMIT_AWARE
    ...     )
    ... ])
    >>>
    >>> # Use alias in requests
    >>> response = router.complete(
    ...     messages=[UserMessage("Hello!")],
    ...     model="gpt-3.5-turbo"
    ... )

Example (With External Storage):
    >>> import skye.store
    >>> from skye.router import ModelRouter
    >>>
    >>> # Keep health and limits in a shared store when the process does not survive between invocations
    >>> storage = skye.store.backend("redis", redis_url="redis://localhost:6379")
    >>> router = ModelRouter(routes=[...], storage=storage)
    >>> router = ModelRouter.from_file("router.skye", storage=storage)  # the same for a file

Example (Direct Registration):
    >>> from skye.router import ModelRouter
    >>> from skye.base.interfaces.router import RoutingStrategy
    >>>
    >>> # Create router and register models directly
    >>> router = ModelRouter(strategy=RoutingStrategy.LEAST_BUSY)
    >>> router.register_model("gpt-4", gpt4_model, tpm=100000, rpm=1000)
    >>> router.register_model("gpt-3.5", gpt35_model, tpm=200000, rpm=2000)
    >>>
    >>> # Set fallbacks
    >>> router.set_fallbacks([
    ...     {"primary": "gpt-4", "fallbacks": ["gpt-3.5"]}
    ... ])
    >>>
    >>> # Route requests
    >>> response = router.complete(
    ...     messages=[UserMessage("Hello!")],
    ...     model="gpt-4"
    ... )
    >>>
    >>> # Check health
    >>> health = router.get_model_health("gpt-4")
    >>> print(f"Success rate: {health.success_rate:.1%}")

Codename: jet.
"""

from skye.base.lazy_import import lazy_names as _lazy_names
from skye.base.interfaces.router import RoutingStrategy
from skye.router.config_models import (
    AllowedFailsPolicyConfig,
    CooldownInfo,
    FallbackConfig,
    ModelHealthMetrics,
    ModelTarget,
    RetryPolicyConfig,
    RouteConfig,
    UsageStats,
)
from skye.router.model_router import ModelRouter
from skye.router.routing_strategies import StrategyContext, with_context
from skye.router.skye_file import load_router_config

# The offline check is read at first use, so importing the package does not import it.
_LAZY = {"check_routing_strategy": "conformance"}
__getattr__ = _lazy_names(__name__, _LAZY)

__all__ = [
    *_LAZY,
    "RoutingStrategy",
    # Router
    "ModelRouter",
    "load_router_config",
    # Routing strategies
    "StrategyContext",
    "with_context",
    # Configuration models
    "ModelTarget",
    "RouteConfig",
    "FallbackConfig",
    "RetryPolicyConfig",
    "AllowedFailsPolicyConfig",
    # Metrics and stats models
    "ModelHealthMetrics",
    "UsageStats",
    "CooldownInfo",
]
