"""A helper for tests that register providers on the default registrar: put it back as it was
(plugins:5.2).

``ProviderRegistry`` is a view of the default registrar, so a test that registers a provider, or
replaces a built-in one, changes what every later test sees.
``restored_default_registrar`` snapshots the tables and the profiles and restores them on exit.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from skye.base.plugins import Registrar, get_registrar


@contextmanager
def restored_default_registrar() -> Iterator[Registrar]:
    """The default registrar, with the built-ins loaded, restored to the state it had on entry."""
    registrar = get_registrar()
    registrar.names("provider")  # loads the built-ins first, so they are part of the snapshot
    tables = {kind: dict(table) for kind, table in registrar._tables.items()}
    profiles = dict(registrar._profiles)
    try:
        yield registrar
    finally:
        registrar._tables = {kind: dict(table) for kind, table in tables.items()}
        registrar._profiles = dict(profiles)
