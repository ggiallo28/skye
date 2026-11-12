"""Create a backend by name and add backends from outside Skye (Requirement 12.6, decision D98).

``backend(name, **config)`` builds one of the registered backends, in the style of ``provider(name,
**config)``. Both functions are a view of the ``backend`` table of the default registrar
(plugins:7.1). The ones of Skye are registered by module path (``skye.store.plugins``), so naming
one imports only its module, and its driver only on first use. ``register_backend`` adds any
other backend (a class or a function that returns one) without changing Skye; check it with
``skye.store.conformance``.

Example:
    >>> from skye.store import backend, register_backend, InMemoryBackend
    >>> type(backend("memory")).__name__
    'InMemoryBackend'
    >>> register_backend("scratch", lambda **config: InMemoryBackend())
    >>> type(backend("scratch")).__name__
    'InMemoryBackend'

Raises: ``ConfigurationError`` for an unknown name (listing the known ones) or a name registered
    twice without ``replace=True``.
Missing: not applicable.
Concurrency: register backends at start-up; the table is the ``backend`` table of the default registrar of this process.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from skye.base.exceptions import ConfigurationError
from skye.base.interfaces.storage import StorageBackend
from skye.base.plugins import Registrar, get_registrar

Factory = Callable[..., StorageBackend]

KIND = "backend"


def _registrar() -> Registrar:
    """The registrar the functions below are a view of; a test replaces this to work on a private one."""
    return get_registrar()


def register_backend(name: str, factory: Factory, *, replace: bool = False) -> None:
    """Register ``factory`` under ``name``; ``factory(**config)`` returns the backend.

    This is ``registrar.backend(name, factory)`` of the default registrar (Requirement 56.7).

    Args:
        name: The name passed to ``backend``.
        factory: A backend class, a function taking the configuration as keyword arguments, or a
            ``"module:attribute"`` text for one (imported when the name is first used).
        replace: Allow replacing a name already registered (a built-in one included).
    """
    if not isinstance(name, str) or not name:
        raise ConfigurationError("a backend name must be a non-empty string")
    if not callable(factory) and not isinstance(factory, str):
        raise ConfigurationError(f"the factory of backend {name!r} is not callable")
    _registrar().backend(name, factory, replace=replace)


def available_backends() -> list[str]:
    """The names ``backend`` accepts, sorted."""
    return _registrar().names(KIND)


def _resolve(name: str) -> Factory:
    registrar = _registrar()
    try:
        factory: Factory = registrar.get(KIND, name)
    except ConfigurationError:
        if registrar.has(
            KIND, name
        ):  # registered, but its text does not import: keep that error and its cause
            raise
        raise ConfigurationError(
            f"unknown store backend {name!r}; known: {', '.join(available_backends())}"
        ) from None
    return factory


def backend(name: str, **config: Any) -> StorageBackend:
    """Build the backend registered as ``name`` with ``config`` as keyword arguments.

    Built-in names: ``memory``, ``file``, ``dynamodb``, ``redis``, ``valkey``, ``postgres``,
    ``durable_function``.
    """
    return _resolve(name)(**config)


__all__ = ["available_backends", "backend", "register_backend"]
