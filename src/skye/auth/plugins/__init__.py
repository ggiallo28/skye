# Requirements 56.6, 56.7
# plugins:7.2, D110
"""The built-in plugin of ``auth``: one folder per family of credential sources, registered by text
(and 7.6).

``register(registrar)`` calls the ``register`` of each folder of ``IMPLEMENTATIONS``, which adds its
sources under their fixed names as
``"module:attribute"`` texts that name the door of the folder
(``skye.auth.plugins.aws:aws_authenticator``), so registering imports no source; the
factory is imported when the name is first resolved. The built-ins use the same door as a
third-party
plugin, and ``skye.auth.registry`` is a view of the registrar. A folder is a family (``aws``,
``azure``, ``google``, ``oauth2``, ``openai_compatible``,
``secrets``) with its code in ``source.py`` (and the helper files that only that family uses) and
one ``__init__.py`` that is the only door to it.
What more than one family uses (``cache``, ``refresh``, ``errors``, ``rsa_signing``) stays in the
root of ``auth``. ``sources()`` gives every
built-in source as name -> text; ``SOURCES`` is the same, read on first access.

A name that is already registered is left alone, so ``register`` can run more than once and never
overwrites what user code registered
first with ``replace=True``.

Raises: nothing; a name already registered is skipped.
Missing: no source is added to a name the registrar already holds.
Concurrency: called at start-up, or at the first lookup of the kind, from one thread; running it
again is harmless.
"""

from __future__ import annotations

import functools
import importlib
from typing import Any

from skye.base.plugins import Registrar

#: The families of credential sources of this package, in registration order (D110).
IMPLEMENTATIONS: tuple[str, ...] = (
    "openai_compatible",
    "aws",
    "google",
    "azure",
    "oauth2",
    "secrets",
)


def _folder(name: str) -> Any:
    return importlib.import_module(f"{__name__}.{name}")


@functools.cache
def sources() -> dict[str, str]:
    """Every built-in credential source: name -> ``module:attribute`` of its factory, naming the
    door of its folder."""
    found: dict[str, str] = {}
    for name in IMPLEMENTATIONS:
        folder = _folder(name)
        found.update(
            {
                source: f"{folder.__name__}:{attribute}"
                for source, attribute in folder.SOURCES.items()
            }
        )
    return found


def __getattr__(name: str) -> Any:
    if name == "SOURCES":
        return sources()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def register(registrar: Registrar) -> None:
    """Add the built-in credential sources to ``registrar``, skipping a name it already has."""
    for name in IMPLEMENTATIONS:
        _folder(name).register(registrar)
