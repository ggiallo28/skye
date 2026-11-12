"""The built-in plugin of ``agents``: the agent types of Skye, one folder each, registered through the registrar (plugins:7.3, D110).

``register(registrar)`` is the same call a third-party plugin makes: it calls the ``register`` of each folder of ``IMPLEMENTATIONS``. Each type is a
``"module:attribute"`` text, so registering imports no agent; the default registrar calls this at its first lookup, so ``import skye.agents`` loads
nothing.

Raises: ``ConfigurationError`` from the registrar when a built-in name is already registered (a plugin that replaces one passes ``replace=True``).
Missing: not applicable.
Concurrency: ``register`` is called once at start-up, from one thread.
"""

from __future__ import annotations

import importlib
from typing import Any

#: The agent-type folders of this package, in registration order (D110).
IMPLEMENTATIONS: tuple[str, ...] = ("react",)


def register(registrar: Any) -> None:
    """Register every built-in agent type, by text."""
    for name in IMPLEMENTATIONS:
        importlib.import_module(f"{__name__}.{name}").register(registrar)
