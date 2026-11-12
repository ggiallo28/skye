"""The built-in plugin of ``tools``: one folder per MCP client implementation and per toolkit, registered by text (Requirement 56.6, 58.2, 62.7; plugins:7.7, D110).

``register(registrar)`` is the same call a third-party plugin makes. It calls the ``register`` of each folder of ``IMPLEMENTATIONS``: ``"skyemcp"`` is the
default (D16) and needs nothing, ``"fastmcp"`` is the optional one, and ``"files"``, ``"openapi"``, ``"human"`` and ``"shell"`` are toolkits. Each one is a ``"module:attribute"`` text, so ``fastmcp`` is imported only when a client is
built with ``impl="fastmcp"`` and the code of a toolkit (``files``, ``openapi``, ``mcp``) only when it is built, never at registration or at ``import skye``. A folder has an
``__init__.py`` that is the only door to it and a ``client.py`` (an MCP client) or a ``toolkit.py`` (a toolkit).

Raises: ``ConfigurationError`` from the registrar when a name is already registered (a plugin that wants to replace one passes ``replace=True``).
Missing: nothing is read or imported here except the doors, which import no inner file.
Concurrency: called once per registrar, from one thread.
"""

from __future__ import annotations

import importlib
from typing import Any

#: The folders of this package (two MCP clients, then the toolkits), in registration order (D110).
IMPLEMENTATIONS: tuple[str, ...] = ("skyemcp", "fastmcp", "files", "openapi", "human", "shell")


def register(registrar: Any) -> None:
    """Register the MCP clients and the toolkits of ``tools``."""
    for name in IMPLEMENTATIONS:
        importlib.import_module(f"{__name__}.{name}").register(registrar)
