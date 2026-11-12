"""The built-in toolkit ``openapi`` (plugin of ``tools``, D110): one tool for each operation of an OpenAPI document.

This ``__init__.py`` is the only module that code outside the folder imports. Its public name resolves lazily from the file of the folder, so importing the
folder imports no inner file; ``register`` adds what the folder offers to a registrar, by ``"module:attribute"`` text.

Raises: ``ConfigurationError`` from ``register`` when the name is already registered (replacing one is the caller's ``replace=True``, never this folder's).
Missing: a missing inner file breaks only the name that lives in it (an ``ImportError`` on first access, turned into a ``ConfigurationError`` by the registrar).
Concurrency: ``register`` is called once at start-up from one thread; a name resolves once and is the same object afterwards.
"""

from __future__ import annotations

from typing import Any

from skye.base.lazy_import import lazy_names

_LAZY = {
    "OpenApiToolkit": "toolkit",
}
__all__ = [*_LAZY, "register"]
__getattr__ = lazy_names(__name__, _LAZY)


def register(registrar: Any) -> None:
    """Register the toolkit under its name, by text."""
    registrar.toolkit("openapi", f"{__name__}:OpenApiToolkit")
