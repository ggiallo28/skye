# Requirement 58.4, D98, D111
"""``check_mcp_client`` and ``check_toolkit``: the conformance functions of the kinds that ``tools``
owns.

Both run offline (no call reaches a server and no tool is run), return the names of the checks they
passed and raise an ``AssertionError`` that
names the first that fails (``skye.store.check_backend`` is the model). Both are coroutine
functions, so one runner awaits every kind alike.

Example:
    >>> import asyncio
    >>> from skye.tools import Toolkit, capability
    >>> from skye.tools.conformance import check_toolkit
    >>> class ClockToolkit(Toolkit):
    ...     @capability
    ...     def now(self) -> str:
    ...         '''The time.'''
    ...         return "12:00"
    >>> asyncio.run(check_toolkit(ClockToolkit))
    ['builds', 'provider', 'schemas', 'closes']

Raises: ``AssertionError`` naming the first failed check.
Missing: an MCP client is built and looked at, never connected; a toolkit lists its schemas, and
none of its tools runs (a tool may have effects).
Concurrency: nothing is shared; each call builds its own object.
"""

from __future__ import annotations

import inspect
from typing import Any

from skye.base.conformance import Check, require, run_checks
from skye.tools.mcp_client import MCPClientInterface


def _coroutines(obj: Any, names: Any) -> None:
    for name in names:
        method = getattr(obj, name, None)
        require(callable(method), f"the object has no method {name!r}")
        require(inspect.iscoroutinefunction(method), f"{name!r} must be a coroutine function")


async def check_mcp_client(
    factory: Any, target: str = "http://127.0.0.1:9/mcp", **config: Any
) -> list[str]:
    """Check an MCP client factory: ``factory(target, headers=None, timeout=...)`` builds an object
    with the coroutine methods of the Port.

    The client is built and never connected. ``config`` goes to the factory next to the three
    arguments the builder gives it.
    """
    built: list[Any] = []
    methods = sorted(MCPClientInterface.__abstractmethods__)

    def builds() -> None:
        built.append(factory(target, headers=None, timeout=1.0, **config))

    async def closes() -> None:
        close = getattr(built[0], "close", None)
        if callable(close):
            result = close()
            if inspect.isawaitable(result):
                await result

    checks: list[Check] = [
        ("builds", builds),
        ("interface", lambda: _coroutines(built[0], methods)),
        ("closes", closes),
    ]
    return await run_checks("mcp client", factory, checks)


async def check_toolkit(toolkit: Any, **config: Any) -> list[str]:
    """Check a toolkit: ``toolkit(**config)`` builds a ``ToolProvider`` whose schemas are named,
    described and unique, and that closes.

    For a ``Toolkit`` the names of the tools must carry its prefix (``<toolkit>.<name>``). No tool
    is run.
    """
    built: list[Any] = []

    def provider() -> None:
        _coroutines(built[0], ("list_schemas", "run", "close"))

    async def schemas() -> None:
        listed = await built[0].list_schemas()
        require(isinstance(listed, list), "list_schemas must return a list")
        names = [schema.name for schema in listed]
        require(all(isinstance(name, str) and name for name in names), "a tool has no name")
        require(len(names) == len(set(names)), f"two tools have one name: {sorted(names)}")
        require(
            all(str(schema.description).strip() for schema in listed), "a tool has no description"
        )
        prefix = built[0]._prefix() if hasattr(built[0], "_prefix") else None
        require(
            prefix is None or all(name.startswith(f"{prefix}_") for name in names),
            f"the names of the tools must start with '{prefix}_'",
        )

    async def closes() -> None:
        await built[0].close()

    checks: list[Check] = [
        ("builds", lambda: built.append(toolkit(**config))),
        ("provider", provider),
        ("schemas", schemas),
        ("closes", closes),
    ]
    return await run_checks("toolkit", toolkit, checks)


__all__ = ["check_mcp_client", "check_toolkit"]
