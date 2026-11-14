# D110
"""The fastmcp MCP client (plugin of ``tools``): the optional MCP client backed by ``fastmcp``,
chosen with ``impl="fastmcp"``.

This ``__init__.py`` is the only module that code outside the folder imports. Its public name
resolves lazily from the file of the folder, so importing the
folder imports no inner file and never imports ``fastmcp`` (the library is imported when a client is
built); ``register`` adds what the folder offers to a registrar, by ``"module:attribute"`` text.

Raises: ``ConfigurationError`` from ``register`` when the name is already registered (replacing one
is the caller's ``replace=True``, never this folder's).
Missing: a missing inner file breaks only the name that lives in it (an ``ImportError`` on first
access, turned into a ``ConfigurationError`` by the registrar).
Concurrency: ``register`` is called once at start-up from one thread; a name resolves once and is
the same object afterwards.
"""

from __future__ import annotations

from typing import Any

from skye.base.lazy_import import lazy_names

_LAZY = {
    "FastMCPClient": "client",
}
__all__ = [*_LAZY, "register"]
__getattr__ = lazy_names(__name__, _LAZY)


def register(registrar: Any) -> None:
    """Register the client under its ``impl`` name, by text."""
    registrar.mcp_client("fastmcp", f"{__name__}:FastMCPClient")
