"""The built-in plugin of ``store``: one folder per backend, registered by text (plugins:7.1 and 7.5, D110, Requirement 56.6).

``register(registrar)`` is the same call a third-party plugin makes. It calls the ``register`` of each folder of ``IMPLEMENTATIONS``. A folder is a
backend (``memory``, ``file``, ``dynamodb``, ``redis``, ``postgres``, ``durable_function``) with its code (``backend.py``) and one ``__init__.py`` that is
the only door to it. Each class is a ``"module:attribute"`` text, so registering imports no backend module: naming a backend imports only its folder
and its driver only on first use. ``valkey`` is a second name for the Redis backend (D102). ``BACKENDS`` is the name to text map of every folder.

Raises: ``ConfigurationError`` from the registrar for a name already registered (not for the first call on a fresh registrar).
Missing: not applicable.
Concurrency: called once per registrar, at its first lookup of a ``backend`` name.
"""

from __future__ import annotations

import importlib

from skye.base.interfaces.plugin import RegistrarInterface

#: The backend folders of this package, in registration order (D110).
IMPLEMENTATIONS: tuple[str, ...] = (
    "memory",
    "file",
    "dynamodb",
    "redis",
    "postgres",
    "durable_function",
)


def _folder(name: str) -> object:
    return importlib.import_module(f"{__name__}.{name}")


BACKENDS: dict[str, str] = {}
for _name in IMPLEMENTATIONS:
    BACKENDS.update(_folder(_name).BACKENDS)  # type: ignore[attr-defined]


def register(registrar: RegistrarInterface) -> None:
    """Register every built-in backend by text, folder by folder."""
    for name in IMPLEMENTATIONS:
        _folder(name).register(registrar)  # type: ignore[attr-defined]
