"""Agents registry: the single extension point for agent types.

An agent type is a factory (usually a class) that produces a ``Runnable``. Types
are registered by name; user code can register its own through ``register_agent_type``.
The functions below are a view of the ``agent`` table of the default registrar (plugins:7.3,
Requirement 56.7): a plugin registers a type with ``registrar.agent(name, factory)`` and it is
created here by name. ``react``, the placeholder that ships today, is registered by the built-in plugin
of this component (``skye.agents.plugins``) when the registrar is first read.

Standard library plus ``skye.base`` only. This module does not import ``models``
or any other orchestrator; concrete agent types arrive with the future ``agents`` spec.

Raises: ``ConfigurationError`` for an empty name, a name registered twice without ``replace=True``, or an unknown name (the error lists the registered ones).
Missing: not applicable.
Concurrency: register types at start-up; the table is the ``agent`` table of the default registrar of this process.
"""

from collections.abc import Callable
from typing import Any

from skye.agents.plugins.react import ReActAgent
from skye.base.exceptions import ConfigurationError
from skye.base.interfaces.runnable import Runnable
from skye.base.plugins import Registrar, get_registrar

AgentFactory = Callable[..., Runnable[Any, Any]]

REACT = "react"

KIND = "agent"


def _registrar() -> Registrar:
    """The registrar the functions below are a view of; a test replaces this to work on a private one."""
    return get_registrar()


def register_agent_type(name: str, factory: AgentFactory, *, replace: bool = False) -> None:
    """Register an agent type under ``name``.

    This is ``registrar.agent(name, factory)`` of the default registrar. ``factory`` is the class or function, or a
    ``"module:attribute"`` text for it (imported when the type is first created).

    Raises:
        ConfigurationError: if ``name`` is already registered and ``replace`` is False.
    """
    if not name or not isinstance(name, str):
        raise ConfigurationError(
            "Agent type name must be a non-empty string", details={"name": name}
        )
    registrar = _registrar()
    if registrar.has(KIND, name) and not replace:
        raise ConfigurationError(f"Agent type already registered: {name!r}", details={"name": name})
    registrar.agent(name, factory, replace=replace)


def get_agent_type(name: str) -> AgentFactory:
    """Return the factory registered under ``name``.

    Raises:
        ConfigurationError: if ``name`` is not registered.
    """
    registrar = _registrar()
    if not registrar.has(KIND, name):
        raise ConfigurationError(
            f"Unknown agent type: {name!r}", details={"name": name, "available": registrar.names(KIND)}
        )
    factory: AgentFactory = registrar.get(KIND, name)
    return factory


def create_agent(name: str, **options: Any) -> Runnable[Any, Any]:
    """Instantiate the agent type registered under ``name``."""
    return get_agent_type(name)(**options)


def list_agent_types() -> list[str]:
    """Return the registered agent type names, sorted."""
    return _registrar().names(KIND)


__all__ = [
    "REACT",
    "AgentFactory",
    "ReActAgent",
    "create_agent",
    "get_agent_type",
    "list_agent_types",
    "register_agent_type",
]
