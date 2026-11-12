"""How the router selects a model: the selector, the base class of a built-in strategy and the lookup of a strategy by name.

A strategy is chosen by name through the registrar (kind ``routing_strategy``, Requirement 58.1). The eight built-ins are registered by the built-in
plugin of the router (``skye.router.plugins``) under the values of ``RoutingStrategy``, so every member of that enumeration still names its strategy.
A plugin adds a name with ``plugins.routing_strategy("name")`` and the name is valid wherever a built-in one is: ``ModelRouter(strategy=...)``,
``RouteConfig.strategy``, ``ModelRouter.from_config_dict`` and the ``strategy`` of a ``.skye`` file.

The call shape of a strategy (D113) is one of three, told apart by what the registered object is and never by its parameters:

* a function ``(available_models) -> model id``: it gets the list of the ids of the models that can answer and returns the one to use;
* a function marked with :func:`with_context`: it gets one read-only :class:`StrategyContext` (the models, the alias, the token estimate, the
  request, the metrics of the models and their targets) and returns the id;
* a ``RouterStrategy`` subclass, as the built-ins are: the selector builds it for each call and calls ``select(context)``.

Raises: ``ConfigurationError`` for a name that is not registered (it lists the registered names) and for a plugin strategy that returns an id that is
    not one of the models it was given; ``ValueError`` when there is no model to choose from.
Missing: no strategy (``None``) picks the first model.
Concurrency: a selector is used by one router on one event loop; a built-in strategy is built for each call and keeps no state.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, TypeVar

from skye.base.completion import CompleteRequest
from skye.base.exceptions import ConfigurationError
from skye.base.interfaces.router import RoutingStrategy
from skye.base.plugins import Registrar, get_registrar

KIND = "routing_strategy"

if TYPE_CHECKING:
    from .config_models import ModelTarget
    from .health_tracker import ModelHealth, RateLimitTracker

_EMPTY: Mapping[str, Any] = MappingProxyType({})

#: The attribute that :func:`with_context` sets on a function to say that it wants the :class:`StrategyContext`.
_WITH_CONTEXT = "__skye_strategy_context__"

_F = TypeVar("_F", bound=Callable[..., Any])


@dataclass(frozen=True)
class StrategyContext:
    """What a strategy is given to choose with: one read-only object for each call (D113, Requirement 58.7).

    Nothing in it can be changed by the strategy: ``models`` is a tuple and the mappings are read-only views.

    Attributes:
        models: The ids of the models that can answer, in the order of the route (never empty).
        alias: The alias (route) the request was made for, or ``None`` when it was not made for one.
        token_estimate: ``(prompt_tokens, completion_tokens)`` expected for the request, or ``None`` with nothing to go on.
        request: The ``CompleteRequest`` of the call (the messages, the capabilities, the ``response_schema``, ``max_tokens``, the tags), or ``None``.
        snapshot: The metrics of each model that the router read before the call (``latency_ms``, ``success_rate``, ``active_requests``, ``rpm_used``,
            ``tpm_used``); a model with no tracker has an empty entry.
        targets: The ``ModelTarget`` of each model that has one.

    Example:
        >>> StrategyContext(models=("a", "b")).models
        ('a', 'b')
    """

    models: tuple[str, ...]
    alias: str | None = None
    token_estimate: tuple[float, float] | None = None
    request: CompleteRequest | None = None
    snapshot: Mapping[str, Mapping[str, float]] = field(default_factory=lambda: _EMPTY)
    targets: Mapping[str, "ModelTarget"] = field(default_factory=lambda: _EMPTY)


def with_context(function: _F) -> _F:
    """Mark a strategy function as one that wants the :class:`StrategyContext` and return it unchanged.

    The selector calls a marked function with the context as its only argument; an unmarked function gets the list of ids.

    Example:
        >>> @with_context
        ... def long_prompt_goes_last(context: StrategyContext) -> str:
        ...     long = (context.token_estimate or (0, 0))[0] > 800
        ...     return context.models[-1 if long else 0]
        >>> long_prompt_goes_last(StrategyContext(models=("cheap", "strong"), token_estimate=(900, 10)))
        'strong'
    """
    setattr(function, _WITH_CONTEXT, True)
    return function


#: The one call shape that the selector uses inside: the context of the call, and the id of the model chosen.
StrategyCall = Callable[[StrategyContext], str]


def strategy_name(strategy: RoutingStrategy | str) -> str:
    """The name of a strategy: the value of a ``RoutingStrategy`` member, or the registered name as it is."""
    return strategy.value if isinstance(strategy, RoutingStrategy) else str(strategy)


def registered_strategies(registrar: Registrar | None = None) -> list[str]:
    """Every strategy name that can be used: the built-in values first, in the order of ``RoutingStrategy``, then the names that a plugin added."""
    names = [member.value for member in RoutingStrategy]
    extra = [name for name in (registrar or get_registrar()).names(KIND) if name not in names]
    return names + extra


def normalize_strategy(
    strategy: RoutingStrategy | str, registrar: Registrar | None = None
) -> RoutingStrategy | str:
    """The member of ``RoutingStrategy`` for a built-in name, the name itself for a registered one.

    Raises:
        ConfigurationError: the name is neither a built-in nor registered (``details["valid_strategies"]`` lists the names that can be used).
    """
    if isinstance(strategy, RoutingStrategy):
        return strategy
    try:
        return RoutingStrategy(strategy)
    except ValueError:
        pass
    source = registrar or get_registrar()
    try:
        source.get(KIND, strategy)
    except ConfigurationError as error:
        raise ConfigurationError(
            f"Invalid routing strategy: {strategy}",
            details={"strategy": strategy, "valid_strategies": registered_strategies(source)},
        ) from error
    return strategy


def estimated_cost(
    target: "ModelTarget", token_estimate: tuple[float, float] | None = None
) -> float | None:
    """The cost of one request to a target, from its ``cost_per_1k_*_tokens`` fields.

    Without an estimate the two prices are summed (the cost of 1k prompt tokens plus 1k completion
    tokens). With ``(prompt_tokens, completion_tokens)`` each price is weighted by its tokens:
    ``prompt_tokens / 1000 * cost_per_1k_prompt_tokens + completion_tokens / 1000 *
    cost_per_1k_completion_tokens``. A price that is not set counts as 0 when the other one is set;
    a target with neither has no cost (``None``).
    """
    prompt = getattr(target, "cost_per_1k_prompt_tokens", None)
    completion = getattr(target, "cost_per_1k_completion_tokens", None)
    if prompt is None and completion is None:
        return None
    if token_estimate is None:
        prompt_weight, completion_weight = 1.0, 1.0
    else:
        prompt_weight, completion_weight = token_estimate[0] / 1000.0, token_estimate[1] / 1000.0
    return (prompt or 0.0) * prompt_weight + (completion or 0.0) * completion_weight


class RouterStrategy:
    """The base of a built-in strategy: it reads the state of the router through the selector it is built with.

    The selector builds one for each call (a strategy keeps no state) and calls :meth:`select` with the :class:`StrategyContext` of the call. A plugin that
    only needs the ids writes a plain function instead (see ``skye.router.plugins``).
    """

    def __init__(self, selector: "RoutingStrategySelector") -> None:
        self.selector = selector

    def select(self, context: StrategyContext) -> str:
        """The id of the model to use among ``context.models`` (never empty)."""
        raise NotImplementedError


class RoutingStrategySelector:
    """Handles model selection by the name of a routing strategy."""

    def __init__(
        self,
        health: dict[str, "ModelHealth"],
        rate_limits: dict[str, "RateLimitTracker"],
        model_targets: dict[str, "ModelTarget"],
        round_robin_index: dict[str, int],
        registrar: Registrar | None = None,
    ):
        """Initialize the strategy selector.

        Args:
            health: Dictionary of model health trackers.
            rate_limits: Dictionary of rate limit trackers.
            model_targets: Dictionary of model target configurations.
            round_robin_index: Dictionary tracking round-robin indices.
            registrar: The registrar that holds the strategies; the default registrar of the process when omitted, read at each call.
        """
        self.health = health
        self.rate_limits = rate_limits
        self.model_targets = model_targets
        self.round_robin_index = round_robin_index
        self._registrar = registrar
        # Metrics read from the (async) trackers by prepare(); the strategies are synchronous.
        self._snapshot: dict[str, dict[str, float]] = {}

    async def prepare(self, model_ids: list[str]) -> None:
        """Read the metrics the strategies need from the storage-backed trackers.

        Call before apply_strategy: the trackers keep their state in a storage backend and can
        only be read asynchronously, while the strategies pick synchronously from this snapshot.
        """
        snapshot: dict[str, dict[str, float]] = {}
        for model_id in model_ids:
            entry: dict[str, float] = {}
            health = self.health.get(model_id)
            if health is not None:
                entry["latency_ms"] = await health.get_avg_latency_ms()
                entry["success_rate"] = await health.get_success_rate()
            tracker = self.rate_limits.get(model_id)
            if tracker is not None:
                usage = await tracker.get_current_usage()
                entry["active_requests"] = usage.get("active_requests", 0)
                entry["rpm_used"] = usage.get("rpm_used", 0)
                entry["tpm_used"] = usage.get("tpm_used", 0)
            snapshot[model_id] = entry
        self._snapshot = snapshot

    def metric(self, model_id: str, name: str, default: float) -> float:
        """A metric of a model from the snapshot that :meth:`prepare` read, or ``default`` when there is none."""
        return self._snapshot.get(model_id, {}).get(name, default)

    def resolve(self, strategy: RoutingStrategy | str) -> StrategyCall:
        """The call that runs the strategy named ``strategy``: one shape (the context in, an id out) for the three kinds of strategy.

        A ``RouterStrategy`` subclass is built with this selector and its ``select`` is called; a function marked with :func:`with_context` is called with
        the context; any other function is called with the list of the ids. The kind is told by the object and never by its parameters.

        Raises:
            ConfigurationError: the name is not registered, or its text does not import.
        """
        target = (self._registrar or get_registrar()).get(KIND, strategy_name(strategy))
        if isinstance(target, type) and issubclass(target, RouterStrategy):
            return target(self).select
        if getattr(target, _WITH_CONTEXT, False):
            return lambda context: str(target(context))

        def call(context: StrategyContext) -> str:
            return str(target(list(context.models)))

        return call

    def context(
        self,
        available_models: list[str],
        alias: str | None = None,
        token_estimate: tuple[float, float] | None = None,
        request: CompleteRequest | None = None,
    ) -> StrategyContext:
        """The read-only context of one call: the models, the alias, the estimate, the request, and the metrics and targets of those models."""
        return StrategyContext(
            models=tuple(available_models),
            alias=alias,
            token_estimate=token_estimate,
            request=request,
            snapshot=MappingProxyType(
                {m: MappingProxyType(dict(self._snapshot.get(m, {}))) for m in available_models}
            ),
            targets=MappingProxyType(
                {m: self.model_targets[m] for m in available_models if m in self.model_targets}
            ),
        )

    def apply_strategy(
        self,
        available_models: list[str],
        alias: str | None = None,
        strategy: RoutingStrategy | str | None = None,
        *,
        token_estimate: tuple[float, float] | None = None,
        request: CompleteRequest | None = None,
    ) -> str:
        """Apply routing strategy to select a model.

        Args:
            available_models: List of available model IDs.
            alias: Optional alias for round-robin tracking.
            strategy: A ``RoutingStrategy`` or the registered name of a strategy; ``None`` picks the first model.
            token_estimate: ``(prompt_tokens, completion_tokens)`` expected for the request; read by
                ``cost_based`` and ``lazy_complex`` (see :func:`estimated_cost`).
            request: The ``CompleteRequest`` of the call, given to the strategy in its :class:`StrategyContext`.

        Returns:
            Selected model ID.

        Raises:
            ValueError: If no models are available.
            ConfigurationError: The name is not registered, or a plugin strategy returned an id that is not one of ``available_models``.
        """
        if not available_models:
            raise ValueError("No available models for routing")
        if strategy is None:
            return available_models[0]
        chosen = self.resolve(strategy)(
            self.context(available_models, alias, token_estimate, request)
        )
        if chosen not in available_models:
            raise ConfigurationError(
                f"The routing strategy {strategy_name(strategy)!r} returned {chosen!r}, which is not one of the available models",
                details={
                    "strategy": strategy_name(strategy),
                    "returned": chosen,
                    "available": list(available_models),
                },
            )
        return chosen
