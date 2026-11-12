"""Hooks on the memory of an agent (proposed-interface).

The same hooks as in `hooks.py`, on the two operations of the memory: `memory_read`, what the agent
asks to remember, and `memory_write`, what it asks to keep. The payload of a read is the query with
its filters; the payload of a write is the entry. With no hook the agent reads and writes as it
always does.
"""

import asyncio

import skye
from skye.agents import REACT, Modify, Replace, Skip

agent = skye.agent(REACT, model="gpt-4o-mini", memory=...)  # any MemoryInterface


@agent.before("memory_read")
def only_this_user(ctx):
    return Modify({**ctx.payload, "filters": {"user": ctx.state.user}})  # never another user's


@agent.after("memory_read")
def drop_old(ctx):
    return Replace([entry for entry in ctx.payload if entry.age_days < 30])


@agent.before("memory_write")
def keep_secrets_out(ctx):
    if "password" in ctx.payload.content:
        return Skip(None)  # nothing is stored, and the agent goes on


@agent.before("memory_write")
def tag_the_source(ctx):
    return Modify(ctx.payload.with_tags(source="chat"))


@agent.after("memory_write", fail="open")
def count_writes(ctx):
    print("stored:", ctx.payload.id)  # an observer


async def main() -> None:
    print(await agent.invoke("Remember that my favourite colour is green"))


if __name__ == "__main__":
    asyncio.run(main())
