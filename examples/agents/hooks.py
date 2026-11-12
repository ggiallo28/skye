"""Change what an agent does at an exact point, with hooks (proposed-interface).

Each operation of the loop (run, step, toolset, model_call, tool_call, memory_read, memory_write)
has a point before it, one after it and one for its error: `agent.before(op)`, `agent.after(op)`,
`agent.on_error(op)`. The hook gets the context (`ctx.payload`, `ctx.state`); what it returns
decides. Nothing: go on. Before: `Modify(payload)`, `Skip(result)`, `Deny(reason)`. After:
`Replace(result)`, `Retry(payload)`, `Stop(reason)`. `tools=[...]` limits a hook to some tools and
`fail="open"` lets a hook that raises be ignored, as an observer should.

`agent.list_hooks()` lists what is hooked, `agent.describe_hook(name)` says what a hook gets and may
return. `hooks_memory.py` hooks the memory.
"""

import asyncio
import re

import skye
from skye.agents import REACT, Deny, Modify, Replace, Retry, Stop
from skye.tools import capability


@capability
def search(query: str) -> str:
    """Search the knowledge base."""
    return f"{query}: write to ada@acme.org"


@capability
def delete_file(path: str) -> str:
    """Delete a file."""
    return f"{path} deleted"


agent = skye.agent(REACT, model="gpt-4o-mini", tools=[search, delete_file])


@agent.before("run", fail="open")
def started(ctx):
    print("run started")  # an observer: it never changes the run


@agent.before("toolset")
def hide_delete(ctx):
    return Modify([tool for tool in ctx.payload if tool.name != "delete_file"])


@agent.before("tool_call", tools=["delete_file"])
def no_deleting(ctx):
    return Deny("deleting is not allowed here")  # the model reads the reason and goes on


@agent.after("tool_call")
def hide_emails(ctx):
    return Replace(re.sub(r"\S+@\S+", "[email]", ctx.payload.content))


@agent.after("model_call")
def answer_something(ctx):
    if not ctx.payload.content:
        return Retry({**ctx.payload.request, "temperature": 0.7})  # up to the retry limit


@agent.on_error("model_call")
def fallback(ctx):
    return Replace("The service is busy. Try again in a minute.")


@agent.after("step")
def budget(ctx):
    return Stop("budget reached") if ctx.state.cost > 0.50 else None


async def main() -> None:
    print(await agent.invoke("Find the contact of the team"))
    print(agent.list_hooks())  # name, operation, point and where each hook comes from
    print(agent.describe_hook("hide_emails"))  # its payload, its outcomes, its limits


if __name__ == "__main__":
    asyncio.run(main())
