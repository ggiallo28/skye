# D123: one folder per kind inside ``plugins`` where a component has more than one kind of built-in.
"""The built-ins of ``tools``, one folder per kind: ``engines`` and ``toolkits``.

An engine is an implementation of the MCP client Port, chosen by name (``skyemcp``, ``fastmcp``).
A toolkit is what an agent is given (``files``, ``human``, ``openapi``, ``shell``). Each of the two
folders has its own ``IMPLEMENTATIONS`` and its own ``register``; ``register(registrar)`` here is
the one call the registrar makes for ``tools``, and it calls the engines first and the toolkits
after, importing each folder only then.

Raises: ``ConfigurationError`` from the registrar when a name is already registered (a plugin that
    wants to replace one passes ``replace=True``).
Missing: nothing is imported by importing this package; the two folders are imported by
    ``register``.
Concurrency: called once per registrar, from one thread.
"""

from __future__ import annotations

import importlib
from typing import Any

#: The kinds of built-in of ``tools``, in registration order; each is a folder of this package.
KINDS: tuple[str, ...] = ("engines", "toolkits")


def register(registrar: Any) -> None:
    """Register the MCP clients and then the toolkits of ``tools``."""
    for kind in KINDS:
        importlib.import_module(f"{__name__}.{kind}").register(registrar)
