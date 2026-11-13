"""Add and run your own agent type (Live).

This runs real library code end to end.

An agent type is a class that is a ``Runnable`` -- any object with
``async def invoke(self, input) -> output``. You add it by name with
``@plugins.agent("name")``, build instances with ``skye.agent`` and list what is
available with ``plugins.names("agent")``.

The registry is a process-wide singleton that the examples harness does not reset
between scripts, so this example adds it under a script-local name with
``replace=True`` to stay idempotent.
"""

import asyncio

import skye
from skye.interfaces import Runnable

plugins = skye.Plugins()


@plugins.agent("echo-demo", replace=True)
class EchoAgent:
    """A tiny agent type: it echoes the input, optionally with a prefix.

    Satisfies the ``Runnable`` Port structurally, so it needs no base class.
    """

    def __init__(self, *, prefix: str = "echo") -> None:
        self.prefix = prefix

    async def invoke(self, input: str) -> str:
        """Return the input prefixed with the configured label."""
        return f"[{self.prefix}] {input}"


async def main() -> None:
    # Build an instance; the options flow straight to EchoAgent(**options).
    agent = skye.agent("echo-demo", prefix="demo")
    assert isinstance(agent, Runnable)  # the Port is a structural Protocol

    reply = await agent.invoke("hi")
    print(reply)

    print("Registered agent types:", plugins.names("agent"))


if __name__ == "__main__":
    asyncio.run(main())
