"""The registrar Port: how a third party adds an integration to Skye without changing it (Requirement 56 of steering).

``RegistrarInterface`` has one method per kind of integration. A plugin is not an object of its own: it is code that calls these methods,
as decorators or as direct calls, from any part of the program (decision D111). The built-in providers, backends and strategies register
through the same methods. The Port is a ``Protocol``, so a registrar needs no base class and imports nothing from Skye.

Every registrar method takes ``(name, target, *, replace=False)``. ``target`` is the object, a factory, or a ``"module:attribute"``
text that is imported at the first use of the name, never at registration. The provider methods also take ``profile=``, the one
declaration of what is specific to the provider, and ``provider`` takes ``function=`` (``"model"``, ``"embedding"``, ``"decision"``).
``profile(provider, models=..., **fields)`` is the one call that is not a kind: it merges a change into the profile of an existing provider.

Raises: ``ConfigurationError`` for a name already registered for the kind (unless ``replace=True``), for a second different profile of one
    provider, and for a text target that does not import (the error names the kind and the name, and keeps the cause).
Missing: a registration has no lifecycle: there is no ``initialize``, ``shutdown`` or ``get_metadata``; a registration that is not made is simply absent.
Concurrency: a registration is safe from any thread (a duplicate name from two threads gives one success and one error); a read takes no lock and is safe
    from many threads and tasks.
"""

from collections.abc import Mapping, Sequence
from typing import Any, Literal, Protocol, runtime_checkable


@runtime_checkable
class RegistrarInterface(Protocol):
    """What a plugin receives: one method per kind of integration (Requirement 56.2).

    ``profile`` is a ``ProviderProfile`` (plugins:3.1); it is typed ``Any`` here until that class exists in ``base``.
    """

    def provider(
        self,
        name: str,
        target: Any,
        *,
        profile: Any | None = None,
        function: Literal["model", "embedding", "decision"] | None = None,
        replace: bool = False,
    ) -> None:
        """Register a provider under ``name`` for one function (a model, an embedding or a decision), with the optional profile.

        The function is deduced from the methods of the class; a text target must give ``function=``, because it is not imported now.
        """
        ...

    def backend(self, name: str, target: Any, *, replace: bool = False) -> None:
        """Register a storage backend under ``name``."""
        ...

    def credential_source(self, name: str, target: Any, *, replace: bool = False) -> None:
        """Register a credential source under ``name``."""
        ...

    def routing_strategy(self, name: str, target: Any, *, replace: bool = False) -> None:
        """Register a routing strategy under ``name``."""
        ...

    def mcp_client(self, name: str, target: Any, *, replace: bool = False) -> None:
        """Register an MCP client implementation under ``name`` (the ``impl`` of a server)."""
        ...

    def tokenizer(self, name: str, target: Any, *, replace: bool = False) -> None:
        """Register a tokenizer under ``name`` (the name a ``ModelProfile`` refers to)."""
        ...

    def template_filter(self, name: str, target: Any, *, replace: bool = False) -> None:
        """Register a prompt filter in the default set under ``name``."""
        ...

    def agent(self, name: str, target: Any, *, replace: bool = False) -> None:
        """Register an agent type under ``name``."""
        ...

    def profile(
        self, provider: str, models: Mapping[str, Any] | None = None, **fields: Any
    ) -> None:
        """Merge a change into the profile of an existing provider: the model entries given and the scalar fields given, nothing else."""
        ...

    def toolkit(
        self, name: str, target: Any, *, tools: Sequence[Any] | None = None, replace: bool = False
    ) -> None:
        """Register a toolkit under ``name``: a named set of tools that an agent takes apart from its own.

        ``tools`` is a list of capabilities (functions written with ``@capability``) that join the toolkit when it is built.
        """
        ...
