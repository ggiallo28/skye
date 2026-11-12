"""The credential-source registry: the one extension point of ``auth`` (Requirement 11.5).

A credential source is a factory: ``factory(**config)`` returns an authenticator (an
``AuthenticationInterface``) or, for a secret manager, an object with ``get(name)``. User code
registers its own source under a name and resolves it by that name; adding a source edits only the
user's code and this registry, never another component. The sources that ship with ``auth`` are
registered here under fixed names and imported only when resolved, so listing the registry loads
nothing.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from skye.auth import plugins as _plugin
from skye.base.exceptions import ConfigurationError
from skye.base.plugins import Registrar, get_registrar

CredentialSourceFactory = Callable[..., Any]

_KIND = "credential_source"
_lock = threading.Lock()


def _registrar() -> Registrar:
    """The default registrar with the built-in sources in it: this module keeps no table of its own (Requirement 56.7)."""
    registrar = get_registrar()
    _plugin.register(
        registrar
    )  # a name already there is skipped, so this is cheap and safe to repeat
    return registrar


def _check_name(name: str) -> None:
    if not isinstance(name, str) or not name.strip():
        raise ConfigurationError(
            "A credential source needs a non-empty name", details={"name": name}
        )


def register_credential_source(
    name: str, factory: CredentialSourceFactory, *, replace: bool = False
) -> None:
    """Register a credential source under ``name``.

    Args:
        name: The name to resolve it by.
        factory: ``factory(**config)`` returns the authenticator (or secret source).
        replace: Allow replacing a source already registered under the name (one of the built-in
            names can only be replaced this way).

    Raises:
        ConfigurationError: The name is empty, or already taken and ``replace`` is false.
    """
    _check_name(name)
    if not callable(factory):
        raise ConfigurationError(
            "A credential source factory must be callable", details={"name": name}
        )
    with _lock:
        registrar = _registrar()
        if registrar.has(_KIND, name) and not replace:
            raise ConfigurationError(
                f"A credential source named {name!r} is already registered", details={"name": name}
            )
        registrar.credential_source(name, factory, replace=True)


def unregister_credential_source(name: str) -> None:
    """Remove a source registered with :func:`register_credential_source` (built-in ones stay).

    A built-in name that was replaced goes back to the built-in source.
    """
    with _lock:
        registrar = _registrar()
        registrar.unregister(_KIND, name)
        _plugin.register(registrar)  # puts a built-in name back


def list_credential_sources() -> list[str]:
    """The names of every source: the built-in ones and those registered by user code or by a plugin."""
    return _registrar().names(_KIND)


def resolve_credential_source(name: str, **config: Any) -> Any:
    """Build the source registered under ``name`` with ``config``.

    Raises:
        ConfigurationError: No source has that name (the message lists the names).
    """
    registrar = _registrar()
    if not registrar.has(_KIND, name):
        raise ConfigurationError(
            f"No credential source named {name!r}; known: {', '.join(registrar.names(_KIND))}",
            details={"name": name},
        )
    factory = registrar.get(_KIND, name)
    return factory(**config)


__all__ = [
    "register_credential_source",
    "unregister_credential_source",
    "list_credential_sources",
    "resolve_credential_source",
]
