# plugins:9.1, D110, Requirement 58.1, D113
"""The built-in plugin of ``router``: one folder per routing strategy, registered by text.

``register(registrar)`` is the same call a third-party plugin makes. It calls the ``register`` of
each folder of ``IMPLEMENTATIONS``. A folder is a
strategy with its code (``strategy.py``) and one ``__init__.py`` that is the only door to it: the
eight strategies named by ``RoutingStrategy``
(``simple_shuffle``, ``round_robin``, ``least_busy``, ``rate_limit_aware``, ``latency_based``,
``cost_based``, ``weighted``, ``priority_based``) and
``lazy_complex``, which is not a member of that enumeration. Each class is a ``"module:attribute"``
text, so registering imports no strategy
module. ``STRATEGIES`` is the name to text map of every folder; the names of the eight are the
values of ``RoutingStrategy``, so every member of that
enumeration still names its strategy.

The call shape of a strategy. A strategy registered with ``registrar.routing_strategy(name,
target)`` is one of three things:

* a function ``(available_models: list[str]) -> str``, which gets the ids of the models that can
  answer and returns the one to use (this is what a
  plugin writes, see ``examples/plugins/routing_strategy.py``);
* a function marked with ``skye.router.with_context`` ``(context: StrategyContext) -> str``, which
  gets the read-only context of the call: the models,
  the alias, the token estimate, the request, the metrics and the targets;
* a subclass of ``skye.router.routing_strategies.RouterStrategy``, as the built-ins are: the router
  builds it with its selector and calls
  ``select(context)``, so it can read the latency, the load and the cost of each model.

The kind is told by the registered object (a class, a marked function or a function) and never by
its parameters.

Raises: ``ConfigurationError`` from the registrar for a name already registered (not for the first
call on a fresh registrar).
Missing: not applicable.
Concurrency: called once per registrar, at its first read or write.
"""

from __future__ import annotations

import importlib

from skye.base.interfaces.plugin import RegistrarInterface

# : The strategy folders of this package, in registration order (D110): the order of
# ``RoutingStrategy``, then the strategies that are not a member
#: of it (``lazy_complex``, D113).
IMPLEMENTATIONS: tuple[str, ...] = (
    "simple_shuffle",
    "round_robin",
    "least_busy",
    "rate_limit_aware",
    "latency_based",
    "cost_based",
    "weighted",
    "priority_based",
    "lazy_complex",
)


def _folder(name: str) -> object:
    return importlib.import_module(f"{__name__}.{name}")


STRATEGIES: dict[str, str] = {}
for _name in IMPLEMENTATIONS:
    STRATEGIES.update(_folder(_name).STRATEGIES)  # type: ignore[attr-defined]


def register(registrar: RegistrarInterface) -> None:
    """Register every built-in strategy by text, folder by folder."""
    for name in IMPLEMENTATIONS:
        _folder(name).register(registrar)  # type: ignore[attr-defined]
