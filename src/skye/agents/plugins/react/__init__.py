# D110
"""The ReAct agent type (plugin of ``agents``): the placeholder agent, registered as ``"react"``.

This ``__init__.py`` is the only module that code outside the folder imports. Its public name
resolves lazily from ``agent.py``; ``register`` adds
the type to a registrar by ``"module:attribute"`` text.

Raises: ``ConfigurationError`` from ``register`` when ``react`` is already registered.
Missing: a missing ``agent.py`` breaks only the name that lives in it.
Concurrency: ``register`` is called once at start-up from one thread.
"""

from __future__ import annotations

from typing import Any

from skye.base.lazy_import import lazy_names

_LAZY = {"ReActAgent": "agent"}
__all__ = [*_LAZY, "register"]
__getattr__ = lazy_names(__name__, _LAZY)


def register(registrar: Any) -> None:
    """Register the ReAct placeholder under the name ``react``, by text."""
    registrar.agent("react", f"{__name__}:ReActAgent")
