"""Add an agent type.

To add an agent type you use the decorator `@plugins.agent("name")` on top of a class.

The class has:

* An `__init__` that takes the options of the agent, as keyword arguments.
* `async invoke(input)`, which receives one input and returns one output (the `Runnable` Port).

`skye.agent("name", **options)` builds it, and `plugins.names("agent")` lists it with the built-in
ones. The word is the same to add and to build: `plugins.agent(...)` and `skye.agent(...)`.

The decorator registers at the moment it runs, wherever that code is in your program.

An agent is always built with `skye.agent(...)`, yours and the one that ships with Skye, `REACT` (`from skye.agents import REACT`).
That one runs the loop of model calls and tool calls and takes the model and the tools as options:
`agent.py` shows how to use it. The two classes below need neither: an agent type is any class with
`async invoke`.
"""

import asyncio

import skye

plugins = skye.Plugins()


@plugins.agent("reverse")
class ReverseAgent:
    def __init__(self, *, loud: bool = False) -> None:
        self.loud = loud

    async def invoke(self, input: str) -> str:
        reply = input[::-1]
        return reply.upper() if self.loud else reply


@plugins.agent("shout")
class ShoutAgent:
    async def invoke(self, input: str) -> str:
        return input.upper() + "!"


async def main() -> None:
    print("registered:", plugins.names("agent"))
    print(await skye.agent("reverse", loud=True).invoke("skye"))
    print(await skye.agent("shout").invoke("skye"))


if __name__ == "__main__":
    asyncio.run(main())
