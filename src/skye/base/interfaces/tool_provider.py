# Requirement 16.11 of steering
"""ToolProvider Port: how a runtime component (an agent) obtains and runs the capabilities of its operation.

Two things implement it: the local ``CapabilityRegistry`` and, later, the gateway client. An agent takes its toolset through this one
Port, so it works the same with a local list of functions and with a remote gateway.

The Port is a ``Protocol``: any class with these three ``async`` methods is a ``ToolProvider``; nothing needs to be inherited.
The call runs with an explicit ``CapabilityContext`` that carries the scope token and the description of the operation. The context is
a separate argument and is never folded into the arguments the model chose, so a model argument can never clash with it.
A capability is found by name in the provider you pass; there is no implicit global registry.

Example:
    >>> import asyncio
    >>> from skye.completion import CapabilityCall
    >>> from skye.tools import CapabilityRegistry, capability
    >>> @capability
    ... def add(a: int, b: int) -> int:
    ...     "Add two numbers."
    ...     return a + b
    >>> registry = CapabilityRegistry()
    >>> registry.add(add)
    >>> async def demo():
    ...     schemas = await registry.list_schemas()
    ...     message = await registry.run(CapabilityCall(id="1", name="add", arguments={"a": 1, "b": 2}))
    ...     return [s.name for s in schemas], message.content, message.status.value
    >>> asyncio.run(demo())
    (['add'], '3', 'ok')

Raises: ``run`` does not raise for a failing call: it returns a ``CapabilityMessage`` whose status is ``error``; ``list_schemas`` and
    ``close`` raise a ``SkyeError`` subclass when the provider cannot be reached.
Missing: ``list_schemas`` returns an empty list when there is nothing for the operation; ``run`` of an unknown name is an ``error`` message.
Concurrency: all three are coroutines and may run in several tasks at once; ``close`` is called once, when the owner is done.
"""

from typing import Protocol, runtime_checkable

from skye.base.completion import CapabilityCall
from skye.base.interfaces.capability import CapabilitySchema
from skye.base.messages import CapabilityMessage
from skye.base.validated import Validated, field, validated


@validated
class CapabilityContext(Validated):
    """What travels with a call besides the model's arguments.

    Attributes:
        scope_token: The token that limits what the call may do (sent by an agent to a gateway with every call), or ``None``.
        operation: The description of the operation the call belongs to (the toolset selection), or ``None``.
        metadata: Anything else the caller wants the provider to see.
    """

    scope_token: str | None = None
    operation: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class ToolProvider(Protocol):
    """Offers the capabilities of an operation and runs one call of them."""

    async def list_schemas(self, operation: str | None = None) -> list[CapabilitySchema]:
        """Return the schemas the model may be offered for ``operation`` (all of them when ``operation`` is ``None``)."""
        ...

    async def run(self, call: CapabilityCall, context: CapabilityContext | None = None) -> CapabilityMessage:
        """Run one call with its context and say how it ended; never raises for a failing call."""
        ...

    async def close(self) -> None:
        """Release what the provider holds (a connection, a session); a provider that holds nothing does nothing."""
        ...


__all__ = ["CapabilityContext", "ToolProvider"]
