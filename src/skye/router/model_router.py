"""Unified model router with health tracking, rate limiting, and alias support.

This module provides a complete routing solution with support for:
- Model aliases with multiple targets
- Multiple routing strategies (round-robin, least-busy, rate-limit-aware, etc.)
- Health tracking and metrics per model
- Rate limiting (TPM/RPM) with sliding window
- Cooldown mechanisms for failed models
- Retry policies per error type
- Fallback chains
- Tag-based routing
- Pre-call rate limit checks
- Automatic provider instantiation from configuration
- External storage backends for serverless environments
"""

import asyncio
import difflib
import inspect
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, cast

from skye.base.api_keys import api_key_from_environment
from skye.base.completion import CompleteRequest, CompleteResponse
from skye.base.exceptions import ConfigurationError, ProviderError
from skye.base.interfaces import StorageBackend
from skye.base.interfaces.model import ModelInterface
from skye.base.interfaces.router import ModelRouterInterface, RoutingStrategy
from skye.base.plugins import get_registrar
from skye.base.profile import apply_client_settings
from skye.base.sync import run_sync
from skye.store import backend, namespaced

from .config_models import (
    AllowedFailsPolicyConfig,
    CooldownInfo,
    FallbackConfig,
    ModelHealthMetrics,
    ModelTarget,
    RetryPolicyConfig,
    RouteConfig,
    UsageStats,
)
from .health_tracker import ModelHealth, RateLimitTracker, wall_clock
from .routing_strategies import RoutingStrategySelector, normalize_strategy, registered_strategies, strategy_name

logger = logging.getLogger(__name__)


#: The namespace of the router in the store it is given (Requirement 60.10): its keys read ``router:health:<id>``.
ROUTER_NAMESPACE = "router"


@dataclass
class _Outcome:
    """What happened while one request walked the targets: the calls, the targets tried and the last error."""

    attempts: int = 0
    target_attempts: int = 0
    tried: list[str] = field(default_factory=list)
    last_error: BaseException | None = None


#: The retry policy and the cooldown policy a router starts with (a file or ``to_config`` lists only
# what differs).
#: The names are the error classes of ``skye.exceptions`` (decision D104); a name matches its class
# and the subclasses.
DEFAULT_RETRY_POLICY: dict[str, int] = {
    "RateLimitError": 3,
    "ProviderTimeoutError": 2,
    "ServerError": 2,
    "AuthenticationError": 0,
}
DEFAULT_ALLOWED_FAILS_POLICY: dict[str, int] = {
    "RateLimitError": 100,
    "ContentPolicyError": 1000,
}

#: The keyword arguments of ``from_file`` and ``from_config_dict`` that set or extend the router
# (``routes`` comes
#: from the configuration only).
_ROUTER_KEYWORDS = (
    "strategy",
    "cooldown_seconds",
    "enable_pre_call_checks",
    "fallbacks",
    "retry_policies",
    "allowed_fails_policies",
    "storage",
    "sleep",
    "clock",
)


def _matching_policy(error: BaseException, policy: dict[str, Any]) -> str | None:
    """The entry of a policy that applies to an error: its class name or the nearest base class name (MRO order)."""
    for cls in type(error).__mro__:
        if cls.__name__ in policy:
            return cls.__name__
    return None


# decision D104
def _disable_client_retries(model: Any, *, always: bool) -> None:
    """Turn the provider client's own retries off: the router's policy decides retries.

    A client exposes them as ``max_retries``. A client the router built is always given
    ``max_retries = 0``; a model registered by the caller only when it already has the attribute.
    """
    if not always and not hasattr(model, "max_retries"):
        return
    try:
        model.max_retries = 0
    except (AttributeError, TypeError):  # a read-only or slotted client: leave it as it is
        logger.debug(
            "Router could not turn the client retries off", extra={"model": type(model).__name__}
        )


def _target_config(target: ModelTarget, include_secrets: bool) -> dict[str, Any]:
    """The configuration dictionary of one target, with the secrets left out unless asked for."""
    config = {
        key: item
        for key, item in target.to_dict().items()
        if item is not None and item != [] and item != {} and key not in target.extras
    }
    if config.get("weight") == 1.0:
        del config["weight"]
    for key, original in target.env_refs.items():
        if key in config:
            config[key] = original  # as written: ${NAME}, not the value
        elif key.startswith("options.") and key[len("options.") :] in config.get("options", {}):
            config["options"] = {**config["options"], key[len("options.") :]: original}
    if "api_key" in config and "api_key" not in target.env_refs and not include_secrets:
        del config["api_key"]
    return config


def expand_route_shorthand(
    shorthand: dict[str, list[str]],
) -> tuple[list[RouteConfig], list[FallbackConfig]]:
    """Expand ``{"alias": ["provider/model", ...]}`` into the full form.

    The first entry is the primary target of the alias. Every other entry becomes a route named
    ``alias/fallback<N>`` and the chain ``FallbackConfig(primary=alias, fallbacks=[...])`` lists
    them in order.

    Raises:
        ConfigurationError: If an entry is not ``provider/model`` or an alias has no entry.
    """
    routes: list[RouteConfig] = []
    fallbacks: list[FallbackConfig] = []
    for alias, entries in shorthand.items():
        if isinstance(entries, str):
            entries = [entries]
        if not entries:
            raise ConfigurationError(f"Route '{alias}' needs at least one 'provider/model' entry")
        targets = []
        for entry in entries:
            provider, _, model = entry.partition("/")
            if not provider or not model:
                raise ConfigurationError(
                    f"Route '{alias}': '{entry}' is not of the form 'provider/model'"
                )
            targets.append(
                ModelTarget(
                    model=model,
                    provider=provider,
                    api_key=api_key_from_environment(provider),
                )
            )
        routes.append(RouteConfig(alias=alias, targets=[targets[0]]))
        names = []
        for number, target in enumerate(targets[1:], start=1):
            name = f"{alias}/fallback{number}"
            routes.append(RouteConfig(alias=name, targets=[target]))
            names.append(name)
        if names:
            fallbacks.append(FallbackConfig(primary=alias, fallbacks=names))
    return routes, fallbacks


class ModelRouter(ModelRouterInterface):
    """Unified model router with health tracking, rate limiting, and alias support.

    This router provides comprehensive routing capabilities including:
    - Model aliases with multiple targets
    - Multiple routing strategies
    - Health tracking per model
    - Rate limiting (TPM/RPM)
    - Cooldown for failed models
    - Retry policies
    - Fallback chains
    - Tag-based routing
    - Automatic provider instantiation

    Example (Direct Registration):
        >>> from skye.router import ModelRouter
        >>> from skye.base.interfaces.router import RoutingStrategy
        >>>
        >>> router = ModelRouter(strategy=RoutingStrategy.LEAST_BUSY)
        >>> router.register_model("gpt-4", gpt4_model)
        >>> router.register_model("gpt-3.5", gpt35_model)
        >>> router.set_rate_limits("gpt-4", tpm=100000, rpm=1000)
        >>>
        >>> response = router.complete(
        ...     messages=[UserMessage("Hello!")],
        ...     model="gpt-4"
        ... )

    Example (With Aliases and Targets):
        >>> from skye.router import ModelRouter, ModelTarget, RouteConfig
        >>> from skye.base.interfaces.router import RoutingStrategy
        >>>
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
    """

    def __init__(
        self,
        routes: list[RouteConfig] | dict[str, list[str]] | None = None,
        strategy: RoutingStrategy | str = RoutingStrategy.ROUND_ROBIN,
        cooldown_seconds: float = 60.0,
        enable_pre_call_checks: bool = True,
        fallbacks: list[FallbackConfig] | None = None,
        retry_policies: list[RetryPolicyConfig] | None = None,
        allowed_fails_policies: list[AllowedFailsPolicyConfig] | None = None,
        storage: StorageBackend | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        clock: Callable[[], float] | None = None,
    ):
        """Initialize the router.

        Args:
            routes: Optional list of route configurations with aliases, or the shorthand ``{"alias":
                ["provider/model", ...]}``: the first entry is the primary, the rest are its
                fallbacks. The shorthand builds the same ``RouteConfig``, ``ModelTarget`` and
                ``FallbackConfig`` as the full form; the API key comes from the provider's standard
                environment variable. An explicit ``fallbacks`` argument wins over it.
            strategy: Default routing strategy, used by every route that sets none.
            cooldown_seconds: Default cooldown duration for failed models.
            enable_pre_call_checks: Whether to check rate limits before calls.
            fallbacks: Optional list of fallback configurations.
            retry_policies: Optional list of retry policy configurations (added to the defaults, see
                ``DEFAULT_RETRY_POLICY``).
            allowed_fails_policies: Optional list of allowed fails policy configurations (added to
                the defaults, see ``DEFAULT_ALLOWED_FAILS_POLICY``).
            storage: Optional external storage backend. If None, uses in-memory storage. The router keeps its state in the
                namespace ``router`` of it (the keys read ``router:health:<id>``, ``router:cooldown:<id>``,
                ``router:rate_limit:<id>:...``), so the same store can hold the state of another component; ``router.storage_backend``
                is the store itself.
            sleep: The coroutine that waits between retries, ``asyncio.sleep`` by default; tests
                pass one that only records the waits.
            clock: The source of the current time in seconds, ``time.time`` by default: it chooses the
                window of a rate limit count and stamps the health records (the cooldown and every
                expiry are kept by the store with its own clock). Tests pass the ``FakeClock`` of
                ``skye.store`` here and to ``skye.store.backend("memory", clock=...)``.

        Example:
            >>> router = ModelRouter(
            ...     routes=[...],
            ...     strategy=RoutingStrategy.LEAST_BUSY,
            ...     cooldown_seconds=60.0,
            ...     fallbacks=[
            ...         FallbackConfig(primary="gpt-4", fallbacks=["gpt-3.5-turbo"])
            ...     ],
            ...     retry_policies=[
            ...         RetryPolicyConfig(error_type="RateLimitError", max_retries=3)
            ...     ],
            ...     allowed_fails_policies=[
            ...         AllowedFailsPolicyConfig(
            ...             error_type="RateLimitError",
            ...             allowed_fails_per_minute=100
            ...         )
            ...     ]
            ... )
        """
        self.strategy: RoutingStrategy | str = normalize_strategy(strategy)
        self.cooldown_seconds = cooldown_seconds
        self.pre_call_checks_enabled = enable_pre_call_checks
        self.storage_backend = storage or backend("memory")
        # The state of the router (health, cooldown, rate limits) lives in the namespace ``router`` of that store: the
        # keys read ``router:health:<id>``, so the same store can hold the state of another component.
        self._state = namespaced(self.storage_backend, ROUTER_NAMESPACE)
        self._clock: Callable[[], float] = clock or wall_clock

        self.models: dict[str, ModelInterface] = {}
        self.model_targets: dict[str, ModelTarget] = {}  # Store target configs
        self.aliases: dict[str, RouteConfig] = {}  # Alias -> RouteConfig mapping
        self.health: dict[str, ModelHealth] = {}
        self.rate_limits: dict[str, RateLimitTracker] = {}
        self.fallbacks: dict[str, list[str]] = {}
        self.retry_policy: dict[str, int] = dict(DEFAULT_RETRY_POLICY)
        #: The wait of each retry policy entry: (``retry_after_seconds``, ``exponential_backoff``).
        self.retry_waits: dict[str, tuple[float | None, bool]] = {}
        self.allowed_fails_policy: dict[str, int] = dict(DEFAULT_ALLOWED_FAILS_POLICY)
        self._sleep: Callable[[float], Awaitable[None]] = sleep or asyncio.sleep

        self._round_robin_index: dict[str, int] = {}  # Per-alias round-robin index
        self._last_serving: dict[str, Any] | None = None
        # The storage backend is connected lazily, at the first call that uses it (see
        # _ensure_storage).
        self._storage_connected = False
        self._storage_connecting: tuple[asyncio.AbstractEventLoop, asyncio.Task[None]] | None = None

        # Initialize routing strategy selector
        self._strategy_selector = RoutingStrategySelector(
            health=self.health,
            rate_limits=self.rate_limits,
            model_targets=self.model_targets,
            round_robin_index=self._round_robin_index,
        )

        # The shorthand expands to the full form; explicit fallbacks are applied after it, so they
        # win.
        if isinstance(routes, dict):
            routes, shorthand_fallbacks = expand_route_shorthand(routes)
            fallbacks = [*shorthand_fallbacks, *(fallbacks or [])]

        # Initialize routes if provided
        if routes:
            for route in routes:
                self._register_route(route)

        # Initialize fallbacks if provided
        if fallbacks:
            self.set_fallbacks(fallbacks)

        # Initialize retry policies if provided
        if retry_policies:
            self.set_retry_policy(retry_policies)

        # Initialize allowed fails policies if provided
        if allowed_fails_policies:
            self.set_allowed_fails_policy(allowed_fails_policies)

    async def _ensure_storage(self) -> None:
        """Connect the storage backend once, at the first call that needs it.

        Nothing is started in ``__init__``, so a router can be built inside or outside a running
        loop. Concurrent first calls on one loop share the same connection attempt; a failed attempt
        is retried by the next call.
        """
        if self._storage_connected:
            return
        loop = asyncio.get_running_loop()
        if self._storage_connecting is None or self._storage_connecting[0] is not loop:
            self._storage_connecting = (loop, loop.create_task(self.storage_backend.connect()))
        task = self._storage_connecting[1]
        try:
            await asyncio.shield(task)
        except BaseException:
            if task.done():
                self._storage_connecting = None
            raise
        self._storage_connected = True
        self._storage_connecting = None

    # decisions D59, D62
    @classmethod
    def from_file(cls, path: str | Any, name: str | None = None, **kwargs: Any) -> "ModelRouter":
        """Create a ModelRouter from a ``.skye`` or JSON configuration file.

        A ``.skye`` file holds a ``router`` block; a JSON file holds the
        configuration object. The library reads no YAML: a ``.yaml`` or ``.yml`` file raises a
        ``ConfigurationError`` that names the supported formats. ``env.NAME`` (in ``.skye``) and
        ``${NAME}`` (in JSON) are replaced by the environment variable.

        Args:
            path: Path to the ``.skye`` or ``.json`` file.
            name: The label of the router block when a ``.skye`` file holds several.
            **kwargs: Keyword arguments of ``ModelRouter`` other than ``routes``, as in
                :meth:`from_config_dict` (``storage``, ``strategy``, ``cooldown_seconds``, ...).

        Returns:
            ModelRouter instance configured from the file.

        Raises:
            ConfigurationError: If the file is missing, is YAML, does not parse, names an unset
                variable, or a keyword argument is not one of ``ModelRouter``.

        Example:
            >>> router = ModelRouter.from_file("router.skye")  # doctest: +SKIP
            >>> router = ModelRouter.from_file("router.skye", name="main", cooldown_seconds=120.0)  # doctest: +SKIP
            >>> router = ModelRouter.from_file("router.skye", storage=store)  # doctest: +SKIP
        """
        from .skye_file import load_router_config

        cls._check_keywords("from_file", kwargs)
        return cls.from_config_dict(
            load_router_config(path, name, keep_target_references=True), **kwargs
        )

    @classmethod
    def from_config_dict(cls, config: dict[str, Any], **kwargs: Any) -> "ModelRouter":
        """Create a ModelRouter from a configuration dictionary.

        This class method creates a ModelRouter instance from a configuration dictionary. The
        dictionary should follow the RouterConfig schema.

        Args:
            config: Configuration dictionary with router settings.
            **kwargs: Keyword arguments of ``ModelRouter`` other than ``routes``. ``strategy`` (a
                name or a ``RoutingStrategy``), ``cooldown_seconds`` and ``enable_pre_call_checks``
                replace the values of the configuration; ``fallbacks``, ``retry_policies`` and
                ``allowed_fails_policies`` are added after the configuration's (so they win for the
                same primary or error type); ``storage``, ``sleep`` and ``clock`` are passed on.

        Returns:
            ModelRouter instance configured from the dictionary.

        Raises:
            ConfigurationError: If the configuration is invalid or a keyword argument is not one of
                ``ModelRouter``.

        Example:
            >>> config = {
            ...     "routes": [
            ...         {
            ...             "alias": "gpt-3.5-turbo",
            ...             "targets": [
            ...                 {
            ...                     "model": "gpt-3.5-turbo",
            ...                     "provider": "openai",
            ...                     "api_key": "sk-...",
            ...                     "tpm": 200000,
            ...                     "rpm": 2000
            ...                 }
            ...             ],
            ...             "strategy": "rate_limit_aware"
            ...         }
            ...     ],
            ...     "strategy": "round_robin",
            ...     "cooldown_seconds": 60.0
            ... }
            >>> router = ModelRouter.from_config_dict(config)
        """
        cls._check_keywords("from_config_dict", kwargs)
        # Extract router-level settings
        strategy_value = kwargs.get("strategy", config.get("strategy", "round_robin"))
        strategy_str = (
            strategy_value.value if isinstance(strategy_value, RoutingStrategy) else strategy_value
        )
        cooldown_seconds = kwargs.get("cooldown_seconds", config.get("cooldown_seconds", 60.0))
        enable_pre_call_checks = kwargs.get(
            "enable_pre_call_checks", config.get("enable_pre_call_checks", True)
        )

        # A built-in name becomes its member, a name that a plugin registered stays as it is, another name is an error
        strategy = normalize_strategy(strategy_str)

        # Parse routes
        routes = []
        for route_dict in config.get("routes", []):
            try:
                # Parse targets
                targets = [ModelTarget(**target) for target in route_dict.get("targets", [])]

                # Parse strategy for this route (none: the router's)
                route_strategy_str = route_dict.get("strategy")
                try:
                    route_strategy = (
                        normalize_strategy(route_strategy_str)
                        if route_strategy_str is not None
                        else None
                    )
                except ConfigurationError:
                    raise ConfigurationError(
                        f"Invalid routing strategy for route '{route_dict.get('alias')}': {route_strategy_str}",
                        details={
                            "alias": route_dict.get("alias"),
                            "strategy": route_strategy_str,
                            "valid_strategies": registered_strategies(),
                        },
                    )

                route = RouteConfig(
                    alias=route_dict["alias"],
                    targets=targets,
                    strategy=route_strategy,
                    fallback_on_error=route_dict.get("fallback_on_error", True),
                )
                routes.append(route)
            except KeyError as e:
                raise ConfigurationError(
                    f"Missing required field in route configuration: {e}",
                    details={"route": route_dict, "missing_field": str(e)},
                ) from e
            except Exception as e:
                raise ConfigurationError(
                    f"Failed to parse route configuration: {e}",
                    details={"route": route_dict, "error": str(e)},
                ) from e

        # Parse fallbacks
        fallbacks = []
        for fallback_dict in config.get("fallbacks", []):
            try:
                fallback = FallbackConfig(**fallback_dict)
                fallbacks.append(fallback)
            except Exception as e:
                raise ConfigurationError(
                    f"Failed to parse fallback configuration: {e}",
                    details={"fallback": fallback_dict, "error": str(e)},
                ) from e

        # Parse retry policies
        retry_policies = []
        for policy_dict in config.get("retry_policies", []):
            try:
                policy = RetryPolicyConfig(**policy_dict)
                retry_policies.append(policy)
            except Exception as e:
                raise ConfigurationError(
                    f"Failed to parse retry policy configuration: {e}",
                    details={"policy": policy_dict, "error": str(e)},
                ) from e

        # Parse allowed fails policies
        allowed_fails_policies = []
        for policy_dict in config.get("allowed_fails_policies", []):
            try:
                fails_policy = AllowedFailsPolicyConfig(**policy_dict)
                allowed_fails_policies.append(fails_policy)
            except Exception as e:
                raise ConfigurationError(
                    f"Failed to parse allowed fails policy configuration: {e}",
                    details={"policy": policy_dict, "error": str(e)},
                ) from e

        # Keyword lists come after the configuration's, so they win for the same primary or error
        # type.
        fallbacks.extend(kwargs.get("fallbacks") or [])
        retry_policies.extend(kwargs.get("retry_policies") or [])
        allowed_fails_policies.extend(kwargs.get("allowed_fails_policies") or [])

        # Create router instance
        return cls(
            routes=routes if routes else None,
            strategy=strategy,
            cooldown_seconds=cooldown_seconds,
            enable_pre_call_checks=enable_pre_call_checks,
            fallbacks=fallbacks if fallbacks else None,
            retry_policies=retry_policies if retry_policies else None,
            allowed_fails_policies=allowed_fails_policies if allowed_fails_policies else None,
            storage=kwargs.get("storage"),
            sleep=kwargs.get("sleep"),
            clock=kwargs.get("clock"),
        )

    @staticmethod
    def _check_keywords(method: str, kwargs: dict[str, Any]) -> None:
        """Reject a keyword argument that ``from_file`` / ``from_config_dict`` would otherwise ignore."""
        unknown = sorted(set(kwargs) - set(_ROUTER_KEYWORDS))
        if not unknown:
            return
        hints = {name: difflib.get_close_matches(name, _ROUTER_KEYWORDS, n=1) for name in unknown}
        suggestion = "; ".join(
            f"'{name}': did you mean '{match[0]}'?" for name, match in hints.items() if match
        )
        raise ConfigurationError(
            f"ModelRouter.{method}() got unknown keyword argument(s): {', '.join(repr(n) for n in unknown)}. "
            f"Accepted: {', '.join(_ROUTER_KEYWORDS)}." + (f" {suggestion}" if suggestion else ""),
            details={"unknown": unknown, "accepted": list(_ROUTER_KEYWORDS)},
        )

    def to_config(self, *, include_secrets: bool = False) -> dict[str, Any]:
        """The configuration dictionary of this router: ``ModelRouter.from_config_dict(router.to_config())`` rebuilds it.

        Routes, targets, the fallback chains, the strategy, the cooldown, the pre-call checks, and
        the retry and cooldown policies that differ from the defaults are listed. **Secrets are not
        exported by default:** a value that was written as ``${NAME}`` (an API key, a base URL) is
        exported as ``${NAME}``, and an API key that was written in clear is left out (the target
        then reads its provider's standard environment variable). Pass ``include_secrets=True`` to
        export the keys as they are, for example to a private file. State that is not configuration
        (health, usage, the storage backend, provider instances) and extra fields a target was given
        are not exported.

        Args:
            include_secrets: Export API keys written in clear.

        Returns:
            A dictionary in the shape that :meth:`from_config_dict` and the JSON router files use.
        """
        routes: list[dict[str, Any]] = []
        for alias, route in self.aliases.items():
            entry: dict[str, Any] = {
                "alias": alias,
                "targets": [_target_config(target, include_secrets) for target in route.targets],
            }
            if route.strategy is not None and strategy_name(route.strategy) != strategy_name(
                self.strategy
            ):  # left out: the router's
                entry["strategy"] = strategy_name(route.strategy)
            entry["fallback_on_error"] = route.fallback_on_error
            routes.append(entry)
        return {
            "strategy": strategy_name(self.strategy),
            "cooldown_seconds": self.cooldown_seconds,
            "enable_pre_call_checks": self.pre_call_checks_enabled,
            "routes": routes,
            "fallbacks": [
                {"primary": primary, "fallbacks": list(names)}
                for primary, names in self.fallbacks.items()
            ],
            "retry_policies": [
                self._retry_policy_config(name, count)
                for name, count in self.retry_policy.items()
                if DEFAULT_RETRY_POLICY.get(name) != count or name in self.retry_waits
            ],
            "allowed_fails_policies": [
                {"error_type": name, "allowed_fails_per_minute": count}
                for name, count in self.allowed_fails_policy.items()
                if DEFAULT_ALLOWED_FAILS_POLICY.get(name) != count
            ],
        }

    def _retry_policy_config(self, name: str, count: int) -> dict[str, Any]:
        """One retry policy entry of :meth:`to_config`, with its wait when it has one."""
        entry: dict[str, Any] = {"error_type": name, "max_retries": count}
        retry_after, backoff = self.retry_waits.get(name, (None, False))
        if retry_after is not None:
            entry["retry_after_seconds"] = retry_after
        if backoff:
            entry["exponential_backoff"] = True
        return entry

    def to_skye(self, name: str | None = None, *, include_secrets: bool = False) -> str:
        """The ``router`` block of a ``.skye`` file that rebuilds this router (``ModelRouter.from_file`` reads it back).

        The text is in the full form (one ``route`` block per alias, ``fallback = [...]`` inside the
        route), keys are written as ``env.NAME`` where the router had ``${NAME}`` and are left out
        otherwise (see :meth:`to_config`), and it has no comments. A route's strategy is written
        only when it differs from the router's.

        Args:
            name: The label of the block (``router "name" { ... }``); none by default.
            include_secrets: Write API keys that were given in clear (they are then in the text).

        Returns:
            The ``.skye`` text, which passes ``skye check``.
        """
        from skye.base.dsl import to_text

        from .skye_file import config_to_router_spec

        return str(
            to_text(config_to_router_spec(self.to_config(include_secrets=include_secrets), name))
        )

    def _register_route(self, route: RouteConfig) -> None:
        """Register a route configuration with alias and targets."""
        if route.alias in self.aliases:
            raise ConfigurationError(f"Duplicate route alias: '{route.alias}'")

        self.aliases[route.alias] = route
        self._round_robin_index[route.alias] = 0

        # Register each target as a model
        for target in route.targets:
            # Create unique model ID for this target
            model_id = f"{route.alias}:{target.provider}:{target.model}"

            # Instantiate provider if not already a model instance
            from skye.base.interfaces.registry import get_provider_registry

            ProviderRegistry = get_provider_registry()

            provider_config: dict[str, Any] = {
                "model": target.model,
            }
            if target.api_key:
                provider_config["api_key"] = target.api_key
            if target.api_base:
                provider_config["api_base"] = target.api_base
            if target.api_version:
                provider_config["api_version"] = target.api_version
            if target.region:
                provider_config["region_name"] = target.region
            if target.timeout:
                provider_config["timeout"] = target.timeout

            # A provider may name its settings differently, and may take the model as a deployment name: its profile says so
            # (Requirement 60.4), and the router names no provider.
            provider_config = apply_client_settings(
                get_registrar().get_profile(target.provider), target.model, provider_config
            )
            # What the provider needs and the target has no field for (Google's project_id and
            # location, ...).
            provider_config.update(target.options)

            model = ProviderRegistry.get_model_provider(target.provider, **provider_config)
            _disable_client_retries(model, always=True)

            # Register the model
            self.models[model_id] = model
            self.model_targets[model_id] = target

            # Create health and rate limit trackers with shared storage backend
            self.health[model_id] = ModelHealth(
                model_id=model_id,
                tags=target.tags,
                storage=self._state,
                clock=self._clock,
            )
            self.rate_limits[model_id] = RateLimitTracker(
                tpm_limit=target.tpm,
                rpm_limit=target.rpm,
                model_id=model_id,
                storage=self._state,
                clock=self._clock,
            )

            logger.info(
                "Router target registered", extra={"model_id": model_id, "alias": route.alias}
            )

    # decision D104
    def register_model(
        self,
        model_id: str,
        model: ModelInterface,
        tpm: int | None = None,
        rpm: int | None = None,
        tags: list[str] | None = None,
    ) -> None:
        """Register a model directly with the router.

        A model that has its own retries (a ``max_retries`` attribute, as the provider clients of
        Skye) gets them turned off: the router's retry policy decides.

        Args:
            model_id: Unique identifier for the model.
            model: The model instance implementing ModelInterface.
            tpm: Optional tokens per minute limit.
            rpm: Optional requests per minute limit.
            tags: Optional tags for tag-based routing.
        """
        self.models[model_id] = model
        _disable_client_retries(model, always=False)

        # Create health and rate limit trackers with shared storage backend
        self.health[model_id] = ModelHealth(
            model_id=model_id, tags=tags or [], storage=self._state, clock=self._clock
        )
        self.rate_limits[model_id] = RateLimitTracker(
            tpm_limit=tpm,
            rpm_limit=rpm,
            model_id=model_id,
            storage=self._state,
            clock=self._clock,
        )
        logger.info("Router model registered", extra={"model_id": model_id})

    async def select_model(self, request: CompleteRequest) -> str:
        """Select a model based on routing strategy.

        If the request specifies an alias, selects from targets for that alias. Otherwise, selects
        from all available models.
        """
        await self._ensure_storage()
        # Check if request model is an alias
        if request.model and request.model in self.aliases:
            return await self._select_from_alias(request.model, request)

        # Otherwise select from all available models
        available_models = await self._get_available_models(request)

        if not available_models:
            raise ProviderError(
                "No available models for routing",
                provider="router",
                details={"strategy": strategy_name(self.strategy)},
            )

        await self._strategy_selector.prepare(available_models)
        return self._strategy_selector.apply_strategy(
            available_models,
            None,
            self.strategy,
            token_estimate=self._token_estimate(request),
            request=request,
        )

    async def _select_from_alias(
        self, alias: str, request: CompleteRequest, exclude: set[str] | None = None
    ) -> str:
        """Select a target from an alias based on the route's strategy (the router's when the route sets none).

        Targets in ``exclude`` (those that already failed for this request) are not selected.
        """
        route = self.aliases[alias]

        # Get all model IDs for this alias
        alias_models = [
            model_id
            for model_id in self.models.keys()
            if model_id.startswith(f"{alias}:") and model_id not in (exclude or ())
        ]

        # Filter by availability
        available_models = []
        for model_id in alias_models:
            if await self._is_model_available(model_id, request):
                available_models.append(model_id)

        if not available_models:
            raise ProviderError(
                f"No available targets for alias '{alias}'",
                provider="router",
                details={"alias": alias, "total_targets": len(alias_models)},
            )

        # The route's own strategy, or the router's when the route sets none
        strategy = route.strategy if route.strategy is not None else self.strategy
        await self._strategy_selector.prepare(available_models)
        return self._strategy_selector.apply_strategy(
            available_models,
            alias,
            strategy,
            token_estimate=self._token_estimate(request),
            request=request,
        )

    @staticmethod
    def _token_estimate(request: CompleteRequest) -> tuple[float, float] | None:
        """A rough (prompt, completion) token estimate for ``cost_based``, or ``None`` with nothing to go on.

        The prompt side is about four characters per token over the message texts; the completion
        side is ``max_tokens`` when the request sets it, else the prompt estimate.
        """
        chars = sum(
            len(getattr(message, "content", "") or "") for message in (request.messages or [])
        )
        if not chars and not request.max_tokens:
            return None
        prompt_tokens = chars / 4
        completion_tokens = float(request.max_tokens) if request.max_tokens else prompt_tokens
        return (prompt_tokens, completion_tokens)

    def complete(
        self,
        messages: list[Any],
        model: str | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> CompleteResponse:
        """Complete a request using the router.

        This method provides a unified interface for routing with flexible model and tag-based
        selection. At least one of model or tags must be provided.

        Args:
            messages: List of messages for the completion.
            model: Model name or alias to use for completion (optional).
            tags: Tags to filter models by (optional).
            **kwargs: Additional completion parameters.

        Returns:
            The completion response from the selected model.

        Raises:
            ValueError: If neither model nor tags are provided, or if no models match the specified
                criteria.

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
        # Validate input parameters
        if not model and not tags:
            raise ValueError("At least one of 'model' or 'tags' must be provided")

        # Create internal CompleteRequest
        from skye.base.completion import CompleteRequest

        request = CompleteRequest(
            messages=messages, model=model or "", **kwargs  # Will be selected by router if empty
        )

        # Handle tag-based filtering
        if tags:
            return self._route_with_tags_internal(request, tags)
        else:
            return self._route_request_internal(request)

    async def acomplete(
        self,
        messages: list[Any],
        model: str | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
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
            ValueError: If neither model nor tags are provided, or if no models match the specified
                criteria.
        """
        # Validate input parameters
        if not model and not tags:
            raise ValueError("At least one of 'model' or 'tags' must be provided")

        # Create internal CompleteRequest
        from skye.base.completion import CompleteRequest

        request = CompleteRequest(
            messages=messages, model=model or "", **kwargs  # Will be selected by router if empty
        )

        # Handle tag-based filtering
        if tags:
            return await self._aroute_with_tags_internal(request, tags)
        else:
            return await self._aroute_request_internal(request)

    def _route_request_internal(self, request: CompleteRequest) -> CompleteResponse:
        """Route a request to an appropriate model (internal method)."""
        return run_sync(self._aroute_request_internal(request))

    async def _aroute_request_internal(self, request: CompleteRequest) -> CompleteResponse:
        """Route a request asynchronously (internal method).

        The requested model id, alias (or, with no model, any available model) is tried first, then
        each entry of its fallback chain in order. For an alias the routing strategy selects a
        target among the available ones (not in cooldown, within its limits); when the target fails
        after the retries its error type allows (see :meth:`_retries_for`) and the route has
        ``fallback_on_error``, the other available targets of the route are tried. An alias with no
        available target goes straight to its fallback chain. On success the serving record is put
        in ``response.metadata["router"]`` and kept as :attr:`last_serving`. If every target fails,
        ``ProviderError`` names what was tried and chains the last error; when nothing could be
        selected at all, the selection error itself is raised.
        """
        await self._ensure_storage()
        outcome = _Outcome()
        requested = request.model
        fallback_chain = list(self.fallbacks.get(requested, []))

        # The requested entry: a registered model id, an alias, or no model (any available model).
        served = await self._try_entry(requested, request, outcome, first=True)
        if served is not None:
            return self._record_serving(request, served[0], served[1], outcome, fallbacks_tried=[])
        if not fallback_chain and outcome.tried:
            # No chain for the name asked for: the chain of the model id that was selected, if it
            # has one.
            fallback_chain = list(self.fallbacks.get(outcome.tried[0], []))

        # Try fallbacks (each entry is a registered model id or an alias)
        fallbacks_tried: list[str] = []
        for fallback in fallback_chain:
            logger.warning(
                "Router target failed, trying the next fallback",
                extra={"tried": list(outcome.tried), "fallback": fallback, "requested": requested},
            )
            fallbacks_tried.append(fallback)
            served = await self._try_entry(fallback, request, outcome)
            if served is not None:
                return self._record_serving(
                    request, served[0], served[1], outcome, fallbacks_tried=fallbacks_tried
                )

        if not outcome.tried and isinstance(outcome.last_error, ProviderError):
            raise outcome.last_error  # nothing was available: the selection error says why
        raise ProviderError(
            f"All models failed for request (tried: {outcome.tried}, fallbacks: {fallback_chain})",
            provider="router",
            requested=requested,
            tried=list(outcome.tried),
            attempts=outcome.attempts,
            last_error_type=(
                type(outcome.last_error).__name__ if outcome.last_error is not None else None
            ),
        ) from outcome.last_error

    async def _try_entry(
        self, name: str, request: CompleteRequest, outcome: "_Outcome", *, first: bool = False
    ) -> tuple[str, CompleteResponse] | None:
        """Try one entry of the chain (a model id or an alias); the serving id and the response, or ``None``.

        The requested entry (``first``) that is neither a model id nor an alias (no model, for
        instance) is resolved by the router's strategy over every available model; an unknown
        fallback entry is skipped. A selection that finds nothing available is recorded as the last
        error only when no call failed before it, so the final error chains the provider's failure
        rather than a later "no available targets".
        """
        if name and name in self.models:
            response = await self._try_model(name, request, outcome)
            return (name, response) if response is not None else None

        failed: set[str] = set()
        while True:
            try:
                if name in self.aliases:
                    model_id = await self._select_from_alias(name, request, exclude=failed)
                elif first:
                    model_id = await self.select_model(request)
                else:
                    raise ProviderError(
                        f"Unknown model or alias '{name}'", provider="router", name=name
                    )
            except ProviderError as error:
                if outcome.last_error is None or not outcome.tried:
                    outcome.last_error = error
                return None
            response = await self._try_model(model_id, request, outcome)
            if response is not None:
                return model_id, response
            failed.add(model_id)
            route = self.aliases.get(name)
            if route is None or not route.fallback_on_error:
                return None

    def _retries_for(self, error: BaseException, model_id: str | None = None) -> int:
        """The number of retries of the same target the retry policy allows for this error.

        The error type matches a policy by class name along the MRO, the most specific class first
        (an error derived from ``RateLimitError`` uses the ``RateLimitError`` policy unless its own
        class has one). No match means no retry. When the policy retries the error and the target
        sets ``max_retries``, the target's count is used instead.
        """
        name = _matching_policy(error, self.retry_policy)
        if name is None or self.retry_policy[name] <= 0:
            return 0
        target = self.model_targets.get(model_id) if model_id is not None else None
        if target is not None and target.max_retries is not None:
            return max(0, target.max_retries)
        return max(0, self.retry_policy[name])

    def _retry_wait(self, error: BaseException, retry_number: int) -> float:
        """Seconds to wait before retry number ``retry_number`` (1-based) of this error.

        The policy's ``retry_after_seconds``, doubled after each retry with ``exponential_backoff``;
        the error's own ``retry_after`` (the provider's ``Retry-After``) wins when it is longer.
        """
        name = _matching_policy(error, self.retry_policy)
        base, backoff = (
            self.retry_waits.get(name, (None, False)) if name is not None else (None, False)
        )
        wait = float(base or 0.0)
        if backoff:
            wait *= 2 ** (retry_number - 1)
        server = getattr(error, "retry_after", None)
        if isinstance(server, (int, float)) and server > wait:
            wait = float(server)
        return wait

    async def _call_model(
        self, model: ModelInterface, request: CompleteRequest
    ) -> CompleteResponse:
        """Call the model without blocking the loop: its ``acomplete`` if it has one, else ``complete`` in a worker thread."""
        acomplete = getattr(model, "acomplete", None)
        if acomplete is not None and inspect.iscoroutinefunction(acomplete):
            return cast(CompleteResponse, await acomplete(request))
        return cast(CompleteResponse, await asyncio.to_thread(model.complete, request))

    async def _try_model(
        self, model_id: str, request: CompleteRequest, outcome: "_Outcome | None" = None
    ) -> CompleteResponse | None:
        """Try a request on one target, retrying it as the retry policy allows; ``None`` when the target did not answer.

        Before each retry the router waits :meth:`_retry_wait` seconds (with the injected
        ``sleep``). Retrying stops early when the target is put in cooldown, or when the provider
        asks to wait longer than the cooldown (``retry_after`` above ``cooldown_seconds``): the next
        target is better than waiting. Every attempt and the last error are added to ``outcome``.
        """
        outcome = outcome if outcome is not None else _Outcome()
        if model_id not in self.models:
            logger.error("Router target is not registered", extra={"model_id": model_id})
            return None

        health = self.health[model_id]
        rate_limit = self.rate_limits[model_id]

        # Check cooldown
        if await health.is_in_cooldown():
            logger.warning("Router target is in cooldown", extra={"model_id": model_id})
            return None

        # Check rate limits (pre-call check)
        if self.pre_call_checks_enabled:
            if not await rate_limit.can_accept_request(estimated_tokens=1000):
                logger.warning("Router target is over its rate limit", extra={"model_id": model_id})
                return None

        outcome.tried.append(model_id)
        outcome.target_attempts = 0
        model = self.models[model_id]
        retries_left: int | None = None  # set from the policy at the first failure
        retries_total = 0
        while True:
            wait = 0.0
            outcome.attempts += 1
            outcome.target_attempts += 1
            await rate_limit.increment_active_requests()
            try:
                start_time = time.time()
                response = await self._call_model(model, request)
                latency_ms = (time.time() - start_time) * 1000

                await health.record_success(latency_ms)
                tokens_used = response.usage.total_tokens if response.usage else 0
                await rate_limit.record_request(tokens_used)
                return response

            except Exception as error:
                outcome.last_error = error
                error_type = type(error).__name__
                fails_policy = _matching_policy(error, self.allowed_fails_policy)
                await health.record_failure(error_type, window_reason=fails_policy)

                in_cooldown = await self._should_cooldown(model_id, fails_policy)
                if in_cooldown:
                    await health.set_cooldown(self.cooldown_seconds)
                    logger.warning(
                        "Router target put in cooldown",
                        extra={
                            "model_id": model_id,
                            "error_type": error_type,
                            "cooldown_seconds": self.cooldown_seconds,
                        },
                    )

                if retries_left is None:
                    retries_left = self._retries_for(error, model_id)
                    retries_total = retries_left
                logger.error(
                    "Router target failed",
                    extra={
                        "model_id": model_id,
                        "error_type": error_type,
                        "attempt": outcome.target_attempts,
                        "retries_left": retries_left,
                    },
                )
                if in_cooldown or retries_left <= 0:
                    return None
                server_wait = getattr(error, "retry_after", None)
                if isinstance(server_wait, (int, float)) and server_wait > self.cooldown_seconds:
                    logger.warning(
                        "Router target asked to wait longer than the cooldown, not retried",
                        extra={"model_id": model_id, "retry_after": server_wait},
                    )
                    return None
                retries_left -= 1
                wait = self._retry_wait(error, retries_total - retries_left)

            finally:
                await rate_limit.decrement_active_requests()
            if wait > 0:  # outside the call: a waiting request is not an active one
                await self._sleep(wait)

    def _record_serving(
        self,
        request: CompleteRequest,
        model_id: str,
        response: CompleteResponse,
        outcome: "_Outcome",
        fallbacks_tried: list[str],
    ) -> CompleteResponse:
        """Put the serving record in ``response.metadata["router"]`` and keep it as :attr:`last_serving`.

        The record names the configuration that served the request and never holds a key or another
        secret.
        """
        target = self.model_targets.get(model_id)
        alias: str | None = None
        target_index: int | None = None
        if target is not None:
            alias = model_id.split(":", 1)[0]
            route = self.aliases.get(alias)
            if route is not None:
                target_index = next(
                    (i for i, item in enumerate(route.targets) if item is target), None
                )
        record: dict[str, Any] = {
            "requested": request.model or None,
            "alias": alias,
            "model_id": model_id,
            "provider": target.provider if target is not None else response.provider,
            "model": target.model if target is not None else response.model,
            "target_index": target_index,
            "attempts": outcome.target_attempts,
            "total_attempts": outcome.attempts,
            "tried": outcome.tried[:-1],  # the serving target is the last one tried
            "fallbacks_tried": list(fallbacks_tried),
            "fallback": bool(fallbacks_tried),
        }
        metadata = dict(response.metadata or {})
        metadata["router"] = record
        response.metadata = metadata
        self._last_serving = record
        logger.debug("Router request served", extra={"router": record})
        return response

    @property
    def last_serving(self) -> dict[str, Any] | None:
        """The serving record of the last request this router answered (a copy), or ``None`` before the first one.

        The same record is in ``response.metadata["router"]``: ``requested`` (the model or alias
        asked for), ``alias`` (the route of the serving target, ``None`` for a model registered
        directly), ``model_id``, ``provider``, ``model``, ``target_index`` (the position of the
        target in its route), ``attempts`` (calls to the serving target), ``total_attempts`` (calls
        across the chain), ``tried`` (targets that failed first), ``fallbacks_tried`` and
        ``fallback``. It holds no key or other secret. It is process state, for observability only.
        """
        if self._last_serving is None:
            return None
        record = dict(self._last_serving)
        record["tried"] = list(record["tried"])
        record["fallbacks_tried"] = list(record["fallbacks_tried"])
        return record

    async def _should_cooldown(self, model_id: str, error_type: str | None) -> bool:
        """Whether the failures of the last minute under this allowed-fails entry reached its allowed count.

        ``error_type`` is the entry that matched the error (its class or the nearest base class with
        an entry).
        """
        if error_type is None or error_type not in self.allowed_fails_policy:
            return False

        allowed_fails = self.allowed_fails_policy[error_type]
        recent_fails = await self.health[model_id].recent_failure_count(error_type)
        return recent_fails >= allowed_fails

    async def _is_model_available(self, model_id: str, request: CompleteRequest) -> bool:
        """Check if a model is available for routing."""
        health = self.health.get(model_id)
        rate_limit = self.rate_limits.get(model_id)

        if not health or not rate_limit:
            return False

        # Skip if in cooldown
        if await health.is_in_cooldown():
            return False

        # Skip if rate limit exceeded (if pre-call checks enabled)
        if self.pre_call_checks_enabled:
            if not await rate_limit.can_accept_request():
                return False

        return True

    async def _get_available_models(self, request: CompleteRequest) -> list[str]:
        """Get list of available models (not in cooldown, within rate limits)."""
        available = []
        for model_id in self.models.keys():
            if await self._is_model_available(model_id, request):
                available.append(model_id)
        return available

    def is_alias(self, name: str) -> bool:
        """Check if a name is a registered alias.

        Args:
            name: Name to check.

        Returns:
            True if name is a registered alias.
        """
        return name in self.aliases

    def list_aliases(self) -> list[str]:
        """List all registered aliases.

        Returns:
            List of alias names.
        """
        return list(self.aliases.keys())

    def get_route(self, alias: str) -> RouteConfig | None:
        """Get the route configuration for an alias.

        Args:
            alias: Alias name.

        Returns:
            RouteConfig if alias exists, None otherwise.
        """
        return self.aliases.get(alias)

    async def amark_model_failed(self, model_id: str) -> None:
        """Put a model in cooldown for ``cooldown_seconds`` (async); an unknown model id is ignored."""
        if model_id not in self.health:
            return
        await self._ensure_storage()
        await self.health[model_id].set_cooldown(self.cooldown_seconds)
        logger.warning("Router model marked as failed", extra={"model_id": model_id})

    def mark_model_failed(self, model_id: str) -> None:
        """Put a model in cooldown for ``cooldown_seconds``; the cooldown is stored when the call returns.

        It runs :meth:`amark_model_failed` to the end (in a worker thread when a loop is running),
        as the other synchronous methods do; no background task is left behind. In async code, await
        :meth:`amark_model_failed`.
        """
        if model_id in self.health:
            run_sync(self.amark_model_failed(model_id))

    async def aget_model_health(self, model_id: str) -> ModelHealthMetrics:
        """Get health status of a model asynchronously.

        Args:
            model_id: The model identifier.

        Returns:
            ModelHealthMetrics object with comprehensive health data.
        """
        if model_id not in self.health:
            return ModelHealthMetrics(model_id=model_id)

        await self._ensure_storage()
        health = self.health[model_id]
        rate_limit = self.rate_limits[model_id]

        health_metrics = await health.get_health_metrics()
        usage_stats = await rate_limit.get_current_usage()

        return ModelHealthMetrics(
            model_id=model_id,
            success_count=health_metrics.get("success_count", 0),
            failure_count=health_metrics.get("failure_count", 0),
            total_requests=health_metrics.get("total_requests", 0),
            success_rate=health_metrics.get("success_rate", 1.0),
            average_latency_ms=health_metrics.get("average_latency_ms", 0.0),
            min_latency_ms=health_metrics.get("min_latency_ms"),
            max_latency_ms=health_metrics.get("max_latency_ms"),
            last_success_time=health_metrics.get("last_success_time"),
            last_failure_time=health_metrics.get("last_failure_time"),
            is_in_cooldown=health_metrics.get("is_in_cooldown", False),
            cooldown_until=health_metrics.get("cooldown_until"),
            failure_reasons=health_metrics.get("failure_reasons", {}),
            active_requests=usage_stats.get("active_requests", 0),
            tags=health.tags,
        )

    def get_model_health(self, model_id: str) -> ModelHealthMetrics:
        """Get health status of a model.

        Args:
            model_id: The model identifier.

        Returns:
            ModelHealthMetrics object with comprehensive health data.

        Example:
            >>> health = router.get_model_health("gpt-4")
            >>> print(f"Success rate: {health.success_rate:.1%}")
        """
        if model_id not in self.health:
            return ModelHealthMetrics(model_id=model_id)

        return run_sync(self.aget_model_health(model_id))

    def set_routing_strategy(self, strategy: RoutingStrategy | str) -> None:
        """Set the routing strategy: a ``RoutingStrategy`` or the name of one that a plugin registered.

        Raises:
            ConfigurationError: The name is neither a built-in strategy nor registered.
        """
        self.strategy = normalize_strategy(strategy)
        logger.info("Router strategy set", extra={"strategy": strategy_name(self.strategy)})

    def set_fallbacks(self, fallbacks: list[FallbackConfig]) -> None:
        """Set fallback model chains.

        Args:
            fallbacks: List of FallbackConfig objects defining fallback chains.

        Example:
            >>> router.set_fallbacks([
            ...     FallbackConfig(
            ...         primary="gpt-4",
            ...         fallbacks=["gpt-3.5-turbo", "claude-3-sonnet"]
            ...     )
            ... ])
        """
        for config in fallbacks:
            self.fallbacks[config.primary] = config.fallbacks
            logger.info(
                "Router fallbacks set",
                extra={"primary": config.primary, "fallbacks": list(config.fallbacks)},
            )

    def set_retry_policy(self, retry_policies: list[RetryPolicyConfig]) -> None:
        """Set retry policy per error type.

        Args:
            retry_policies: List of RetryPolicyConfig objects.

        Example:
            >>> router.set_retry_policy([
            ...     RetryPolicyConfig(error_type="RateLimitError", max_retries=3, retry_after_seconds=1.0),
            ...     RetryPolicyConfig(error_type="ProviderTimeoutError", max_retries=2)
            ... ])
        """
        for policy in retry_policies:
            self.retry_policy[policy.error_type] = policy.max_retries
            if policy.retry_after_seconds is not None or policy.exponential_backoff:
                self.retry_waits[policy.error_type] = (
                    policy.retry_after_seconds,
                    policy.exponential_backoff,
                )
            else:
                self.retry_waits.pop(policy.error_type, None)
        logger.info("Router retry policy updated", extra={"retry_policy": dict(self.retry_policy)})

    def set_allowed_fails_policy(
        self, allowed_fails_policies: list[AllowedFailsPolicyConfig]
    ) -> None:
        """Set allowed fails before cooldown per error type.

        Args:
            allowed_fails_policies: List of AllowedFailsPolicyConfig objects.

        Example:
            >>> router.set_allowed_fails_policy([
            ...     AllowedFailsPolicyConfig(
            ...         error_type="RateLimitError",
            ...         allowed_fails_per_minute=100
            ...     )
            ... ])
        """
        for policy in allowed_fails_policies:
            self.allowed_fails_policy[policy.error_type] = policy.allowed_fails_per_minute
        logger.info(
            "Router allowed-fails policy updated",
            extra={"allowed_fails_policy": dict(self.allowed_fails_policy)},
        )

    def set_cooldown_time(self, cooldown_seconds: float) -> None:
        """Set cooldown duration for failed models."""
        self.cooldown_seconds = cooldown_seconds
        logger.info("Router cooldown set", extra={"cooldown_seconds": cooldown_seconds})

    def enable_pre_call_checks(self, enabled: bool = True) -> None:
        """Enable/disable pre-call rate limit checks."""
        self.pre_call_checks_enabled = enabled
        logger.info("Router pre-call checks set", extra={"enabled": enabled})

    def set_rate_limits(
        self, model_id: str, tpm: int | None = None, rpm: int | None = None
    ) -> None:
        """Set rate limits for a model deployment (a model id the router does not know gets a tracker on its store)."""
        if model_id not in self.rate_limits:
            self.rate_limits[model_id] = RateLimitTracker(
                model_id=model_id, storage=self._state
            )

        tracker = self.rate_limits[model_id]
        tracker.tpm_limit = tpm
        tracker.rpm_limit = rpm
        logger.info("Router rate limits set", extra={"model_id": model_id, "tpm": tpm, "rpm": rpm})

    async def aget_usage_stats(self, model_id: str) -> UsageStats:
        """Get current usage statistics for a model (async; state lives in the storage backend)."""
        if model_id not in self.rate_limits:
            return UsageStats(model_id=model_id)

        await self._ensure_storage()
        usage = await self.rate_limits[model_id].get_current_usage()
        health = self.health.get(model_id)
        metrics = await health.get_health_metrics() if health else {}

        return UsageStats(
            model_id=model_id,
            tpm_used=usage.get("tpm_used", 0),
            tpm_limit=usage.get("tpm_limit"),
            rpm_used=usage.get("rpm_used", 0),
            rpm_limit=usage.get("rpm_limit"),
            active_requests=usage.get("active_requests", 0),
            total_requests=metrics.get("total_requests", 0),
            total_failures=metrics.get("failure_count", 0),
        )

    def get_usage_stats(self, model_id: str) -> UsageStats:
        """Get current usage statistics for a model.

        Args:
            model_id: The model identifier.

        Returns:
            UsageStats object with rate limit and request statistics.

        Example:
            >>> stats = router.get_usage_stats("gpt-4")
            >>> print(f"TPM used: {stats.tpm_used}/{stats.tpm_limit}")
        """
        return run_sync(self.aget_usage_stats(model_id))

    async def aget_cooldown_models(self) -> list[CooldownInfo]:
        """Get the models currently in cooldown (async)."""
        await self._ensure_storage()
        cooled_down = []
        for model_id, health in self.health.items():
            metrics = await health.get_health_metrics()
            if not metrics.get("is_in_cooldown"):
                continue
            reasons = metrics.get("failure_reasons") or {}
            reason = max(reasons.items(), key=lambda x: x[1])[0] if reasons else "unknown"
            cooled_down.append(
                CooldownInfo(
                    model_id=model_id,
                    cooldown_until=metrics["cooldown_until"],
                    reason=reason,
                )
            )
        return cooled_down

    def get_cooldown_models(self) -> list[CooldownInfo]:
        """Get list of models currently in cooldown.

        Returns:
            List of CooldownInfo objects for models in cooldown.

        Example:
            >>> cooled_down = router.get_cooldown_models()
            >>> for info in cooled_down:
            ...     print(f"{info.model_id} cooled down until {info.cooldown_until}")
        """
        return run_sync(self.aget_cooldown_models())

    def set_model_tags(self, model_id: str, tags: list[str]) -> None:
        """Set tags for a model deployment."""
        if model_id in self.health:
            self.health[model_id].tags = tags
            logger.info("Router model tags set", extra={"model_id": model_id, "tags": list(tags)})

    def _route_with_tags_internal(
        self, request: CompleteRequest, required_tags: list[str]
    ) -> CompleteResponse:
        """Route request to models matching required tags (internal method)."""
        # Filter models by tags
        matching_models = [
            model_id
            for model_id, health in self.health.items()
            if all(tag in health.tags for tag in required_tags)
        ]

        # If model is specified, also check if it matches the tags
        if request.model:
            # Check if request.model is an alias
            if request.model in self.aliases:
                # Get all model IDs for this alias
                alias_models = [
                    model_id
                    for model_id in self.models.keys()
                    if model_id.startswith(f"{request.model}:")
                ]
                # Filter alias models by tags
                matching_models = [
                    model_id for model_id in alias_models if model_id in matching_models
                ]
            else:
                # Direct model ID - check if it has the required tags
                if request.model not in matching_models:
                    raise ValueError(
                        f"Model '{request.model}' does not have required tags: {required_tags}"
                    )
                matching_models = [request.model]

        if not matching_models:
            if request.model:
                raise ValueError(
                    f"No models found matching model '{request.model}' with required tags: {required_tags}"
                )
            else:
                raise ValueError(f"No models found with required tags: {required_tags}")

        # Temporarily override available models for selection
        original_models = self.models
        self.models = {k: v for k, v in self.models.items() if k in matching_models}

        try:
            return self._route_request_internal(request)
        finally:
            self.models = original_models

    async def _aroute_with_tags_internal(
        self, request: CompleteRequest, required_tags: list[str]
    ) -> CompleteResponse:
        """Route request to models matching required tags asynchronously (internal method)."""
        # Filter models by tags
        matching_models = [
            model_id
            for model_id, health in self.health.items()
            if all(tag in health.tags for tag in required_tags)
        ]

        # If model is specified, also check if it matches the tags
        if request.model:
            # Check if request.model is an alias
            if request.model in self.aliases:
                # Get all model IDs for this alias
                alias_models = [
                    model_id
                    for model_id in self.models.keys()
                    if model_id.startswith(f"{request.model}:")
                ]
                # Filter alias models by tags
                matching_models = [
                    model_id for model_id in alias_models if model_id in matching_models
                ]
            else:
                # Direct model ID - check if it has the required tags
                if request.model not in matching_models:
                    raise ValueError(
                        f"Model '{request.model}' does not have required tags: {required_tags}"
                    )
                matching_models = [request.model]

        if not matching_models:
            if request.model:
                raise ValueError(
                    f"No models found matching model '{request.model}' with required tags: {required_tags}"
                )
            else:
                raise ValueError(f"No models found with required tags: {required_tags}")

        # Temporarily override available models for selection
        original_models = self.models
        self.models = {k: v for k, v in self.models.items() if k in matching_models}

        try:
            return await self._aroute_request_internal(request)
        finally:
            self.models = original_models
