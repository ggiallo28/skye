"""The built-in toolkit ``shell`` (plugin of ``tools``, D110): one tool that runs a program from a list of allowed names.

This ``__init__.py`` is the only module that code outside the folder imports; its name resolves lazily, and ``register`` adds the toolkit to a
registrar by ``"module:attribute"`` text.

Raises: ``ConfigurationError`` from ``register`` when the name is already registered (replacing one is the caller's ``replace=True``).
Missing: a missing inner file breaks only the name that lives in it.
Concurrency: ``register`` is called once at start-up from one thread.
"""

from __future__ import annotations

from typing import Any

from skye.base.lazy_import import lazy_names

_LAZY = {"ShellToolkit": "toolkit"}
__all__ = [*_LAZY, "register"]
__getattr__ = lazy_names(__name__, _LAZY)


def register(registrar: Any) -> None:
    """Register the toolkit under its name, by text."""
    registrar.toolkit("shell", f"{__name__}:ShellToolkit")
