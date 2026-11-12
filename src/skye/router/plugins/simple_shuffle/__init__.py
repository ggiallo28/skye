"""simple_shuffle (plugin of ``router``, D110): the ``simple_shuffle`` routing strategy.

This ``__init__.py`` is the only module that code outside the folder imports. Its public names resolve lazily from the files of the folder, so importing
the folder imports no inner file; ``register`` adds what the folder offers to a registrar, by ``"module:attribute"`` text.

Raises: ``ConfigurationError`` from ``register`` when the name is already registered (replacing one is the caller's ``replace=True``, never this folder's).
Missing: a missing inner file breaks only the name that lives in it (an ``ImportError`` on first access, turned into a ``ConfigurationError`` by the registrar).
Concurrency: ``register`` is called once at start-up from one thread; a name resolves once and is the same object afterwards.
"""

from __future__ import annotations

from skye.base.interfaces.plugin import RegistrarInterface
from skye.base.lazy_import import lazy_names

_LAZY = {
    "SimpleShuffleStrategy": "strategy",
}
__all__ = [*_LAZY, "STRATEGIES", "register"]
__getattr__ = lazy_names(__name__, _LAZY)

#: The names this folder registers, each with the text of its class.
STRATEGIES: dict[str, str] = {
    "simple_shuffle": f"{__name__}:SimpleShuffleStrategy",
}


def register(registrar: RegistrarInterface) -> None:
    """Register what this folder offers, each class by text."""
    for name, target in STRATEGIES.items():
        registrar.routing_strategy(name, target)
