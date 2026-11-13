# Requirement 58.4, D98, D111
"""``check_agent``: the conformance function of the kind ``agents`` owns.

It runs offline, returns the names of the checks it passed and raises an ``AssertionError`` that
names the first that fails
(``skye.store.check_backend`` is the model). It is a coroutine function, so one runner awaits every
kind alike.

Example:
    >>> import asyncio
    >>> from skye.agents.conformance import check_agent
    >>> class Echo:
    ...     async def invoke(self, input):
    ...         return input
    >>> asyncio.run(check_agent(Echo, input="hi"))
    ['builds', 'runnable', 'invokes']

Raises: ``AssertionError`` naming the first failed check.
Missing: ``invokes`` runs only when ``input`` is given, with the options of the call (a fake model
keeps it offline); without it the agent is
    built and looked at, and never run.
Concurrency: nothing is shared; each call builds its own agent.
"""

from __future__ import annotations

import inspect
from typing import Any

from skye.base.conformance import Check, require, run_checks


async def check_agent(factory: Any, *, input: Any = None, **options: Any) -> list[str]:
    """Check an agent factory: ``factory(**options)`` builds a ``Runnable`` (a coroutine
    ``invoke``), and with ``input`` it answers it."""
    built: list[Any] = []

    def runnable() -> None:
        require(
            inspect.iscoroutinefunction(getattr(built[0], "invoke", None)),
            "an agent must have the coroutine method invoke(input)",
        )

    async def invokes() -> None:
        await built[0].invoke(input)

    checks: list[Check] = [
        ("builds", lambda: built.append(factory(**options))),
        ("runnable", runnable),
    ]
    if input is not None:
        checks.append(("invokes", invokes))
    return await run_checks("agent", factory, checks)


__all__ = ["check_agent"]
