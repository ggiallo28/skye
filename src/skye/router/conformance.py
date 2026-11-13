# Requirement 58.4, D98, D111
"""``check_routing_strategy``: the conformance function of the kind ``router`` owns.

It runs offline, returns the names of the checks it passed and raises an ``AssertionError`` that
names the first that fails
(``skye.store.check_backend`` is the model). It is a coroutine function, so one runner awaits every
kind alike. The strategy is registered in a
registrar of its own and run by a real ``RoutingStrategySelector``, so the three forms of a strategy
(a ``RouterStrategy`` subclass, a function of
the ids, a function marked with ``with_context``) are checked the way the router runs them.

Example:
    >>> import asyncio
    >>> from skye.router.conformance import check_routing_strategy
    >>> asyncio.run(check_routing_strategy(lambda ids: ids[-1]))
    ['one_model', 'picks_a_model', 'repeatable_calls', 'alias']

Raises: ``AssertionError`` naming the first failed check.
Missing: the fake models have a tracker with no limit and no metric (the snapshot is empty), so a
strategy that reads metrics must have a default for each.
Concurrency: nothing is shared; the selector and the registrar are built for the call.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from skye.base.conformance import Check, require, run_checks
from skye.base.plugins import Registrar
from skye.router.routing_strategies import RoutingStrategySelector

_MODELS = ["alpha", "beta", "gamma"]


async def check_routing_strategy(strategy: Any, *, models: list[str] | None = None) -> list[str]:
    """Check a routing strategy against fake models: it gives back one of the ids it was given, for
    one model and for several, call after call.

    Args:
        strategy: The target registered as a ``routing_strategy`` (a ``RouterStrategy`` subclass or
            a function).
        models: The ids the strategy chooses among; three fake ids when omitted.
    """
    ids = list(models or _MODELS)
    registrar = Registrar()
    registrar.routing_strategy("under_check", strategy)
    no_limits = {
        model: SimpleNamespace(rpm_limit=None, tpm_limit=None) for model in ids
    }  # a fake tracker per model, with no limit
    selector = RoutingStrategySelector({}, no_limits, {}, {}, registrar=registrar)  # type: ignore[arg-type]

    def pick(available: list[str], alias: str | None = None) -> str:
        return selector.apply_strategy(available, alias, "under_check")

    def one_model() -> None:
        require(pick(ids[:1]) == ids[0], "with one model the strategy must give back that model")

    def picks_a_model() -> None:
        require(pick(ids) in ids, "the strategy must give back one of the ids it was given")

    def repeatable_calls() -> None:
        for _ in range(5):
            require(pick(ids) in ids, "every call must give back one of the ids it was given")

    def alias() -> None:
        require(pick(ids, "a-route") in ids, "a call with an alias must give back one of the ids")

    checks: list[Check] = [
        ("one_model", one_model),
        ("picks_a_model", picks_a_model),
        ("repeatable_calls", repeatable_calls),
        ("alias", alias),
    ]
    return await run_checks("routing strategy", strategy, checks)


__all__ = ["check_routing_strategy"]
