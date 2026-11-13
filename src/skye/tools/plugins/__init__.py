# Requirement 56.6, 58.2, 62.7, plugins:7.7, D110
"""The built-in toolkits of ``tools``: one folder per toolkit, registered by text (the MCP clients
are in ``tools/engines``).

``register(registrar)`` is the same call a third-party plugin makes. It calls the ``register`` of
each folder of ``IMPLEMENTATIONS``: ``"files"``, ``"openapi"``, ``"human"`` and ``"shell"`` are
toolkits. Each one is a ``"module:attribute"`` text, so the code of a toolkit is imported only when
it is built,
never at registration or at ``import skye``. A folder has an ``__init__.py`` that is the only door
to it and a ``toolkit.py``.

Raises: ``ConfigurationError`` from the registrar when a name is already registered (a plugin that
wants to replace one passes ``replace=True``).
Missing: nothing is read or imported here except the doors, which import no inner file.
Concurrency: called once per registrar, from one thread.
"""

from __future__ import annotations

import importlib
from typing import Any

#: The folders of this package (the toolkits), in registration order (D110).
IMPLEMENTATIONS: tuple[str, ...] = ("files", "openapi", "human", "shell")


def register(registrar: Any) -> None:
    """Register the toolkits of ``tools``."""
    for name in IMPLEMENTATIONS:
        importlib.import_module(f"{__name__}.{name}").register(registrar)
