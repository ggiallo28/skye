# D110, O80, D16
"""The built-in engines of ``tools``: one folder per implementation of the MCP client, registered by
text (option D).

An engine is an implementation of a Port (today the kind ``mcp_client``), chosen with ``impl=``; a
toolkit is what an agent is given and lives in
``tools/plugins``. ``register(registrar)`` is the same call a third-party plugin makes. It calls the
``register`` of each folder of ``IMPLEMENTATIONS``:
``"skyemcp"`` is the default and needs nothing, ``"fastmcp"`` is the optional one. Each one is a
``"module:attribute"`` text, so ``fastmcp`` is
imported only when a client is built with ``impl="fastmcp"``, never at registration or at ``import
skye``. A folder has an ``__init__.py`` that is
the only door to it and a ``client.py``.

Raises: ``ConfigurationError`` from the registrar when a name is already registered (a plugin that
wants to replace one passes ``replace=True``).
Missing: nothing is read or imported here except the doors, which import no inner file.
Concurrency: called once per registrar, from one thread.
"""

from __future__ import annotations

import importlib
from typing import Any

#: The folders of this package, in registration order.
IMPLEMENTATIONS: tuple[str, ...] = ("skyemcp", "fastmcp")


def register(registrar: Any) -> None:
    """Register the MCP clients of ``tools``."""
    for name in IMPLEMENTATIONS:
        importlib.import_module(f"{__name__}.{name}").register(registrar)
