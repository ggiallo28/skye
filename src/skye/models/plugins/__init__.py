# D123: one folder per kind inside ``plugins`` where a component has more than one kind of built-in.
"""The built-ins of ``models``, one folder per kind: ``providers`` and ``clouds``.

A provider is an adapter with its profile (``openai``, ``anthropic``, ``bedrock``, ...); the folder
``providers`` has its own ``IMPLEMENTATIONS``, its ``register`` and the profiles. ``clouds`` holds
placeholders only and registers nothing. ``register(registrar)`` here is the one call the registrar
makes for ``models``; it imports ``providers`` only then.

Raises: ``ConfigurationError`` from the registrar when a built-in name is already registered (a
    plugin that wants to replace one passes ``replace=True``).
Missing: nothing is imported by importing this package.
Concurrency: called once per registrar, from one thread.
"""

from __future__ import annotations

import importlib
from typing import Any

#: The kinds of built-in of ``models`` that register something; each is a folder of this package.
KINDS: tuple[str, ...] = ("providers",)


def register(registrar: Any) -> None:
    """Register the providers of ``models``."""
    for kind in KINDS:
        importlib.import_module(f"{__name__}.{kind}").register(registrar)
