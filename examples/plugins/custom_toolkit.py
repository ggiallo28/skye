"""Add a toolkit.

A toolkit is a named set of tools that Skye builds for you when you ask for it by name. Use it for
tools that you share between agents or that need a setup: a connection, a folder, a key. The
functions of one agent are not a toolkit: write them with `@capability` and pass them in `tools=`.

To add a toolkit you use the decorator `@plugins.toolkit("name")` on top of a class that extends
`skye.Toolkit`:

* An `__init__` that takes the options of the toolkit, as keyword arguments.
* One method for each tool, with the same `@capability` that you use on a function: the name, the
  description and `return_direct` are set in the same way, and `self` is not part of the schema.
* A tool that needs nothing of the toolkit can be written outside the class, as a function with
  `@capability`, and added with `tools=[...]` in the decorator: here it is `jira.slugify`, while
  outside the toolkit it stays `slugify`, for the `tools=[slugify]` of an agent.
* `async close()`, if the toolkit holds something to release (a connection).

`skye.Toolkit` does the rest: it is a `ToolProvider`, so an agent takes it in `toolkits=[...]`,
apart from its own `tools=`. `skye.toolkit("name", **options)` builds it.

The name of a tool is the name of the toolkit and the name of the method: `create_issue` in the
toolkit `"jira"` is the tool `jira.create_issue`. You do not write the prefix, and so the tools of a
toolkit never clash with the tools you write yourself. If you build the same toolkit twice (two
Jira servers), give each its own `alias`: `skye.toolkit("jira", alias="jira-eu", ...)`.

A set of functions with no state needs no class: `plugins.toolkit("text", tools=[slugify])`.

A toolkit with nothing to release can also be a function that returns a `CapabilityRegistry`:

    @plugins.toolkit("jira")
    def jira(*, base_url: str) -> CapabilityRegistry: ...
"""

import asyncio

import skye
from skye.completion import CapabilityCall
from skye.tools import capability

plugins = skye.Plugins()


class JiraClient:
    """Stands for the connection of a real client."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def create(self, title: str) -> str:
        return f"PROJ-1 created at {self.base_url}: {title}"

    async def aclose(self) -> None:
        print("connection closed")


@capability
def slugify(title: str) -> str:
    """Make the part of an address that comes from a title."""
    return "-".join(title.lower().split())


@plugins.toolkit("jira", tools=[slugify])  # a tool written outside the class, added here
class JiraToolkit(skye.Toolkit):
    def __init__(self, *, base_url: str) -> None:
        self.client = JiraClient(base_url)

    @capability
    def create_issue(self, title: str) -> str:
        """Create an issue and return its key."""
        return self.client.create(title)

    @capability(return_direct=True)
    def issue_url(self, key: str) -> str:
        """The address of an issue, ready to be given back as it is."""
        return f"{self.client.base_url}/browse/{key}"

    @capability(
        name="close_issue",
        description="Close an issue that is done or no longer needed.",
    )
    def move_to_done(self, key: str) -> str:
        # A name of its own: the tool is `jira.close_issue`, whatever the method is called.
        return f"{key} closed"

    async def close(self) -> None:
        await self.client.aclose()


async def main() -> None:
    jira = skye.toolkit("jira", base_url="https://acme.example/jira")
    print("tools:", [schema.name for schema in await jira.list_schemas()])

    call = CapabilityCall(id="1", name="jira.create_issue", arguments={"title": "Broken login"})
    message = await jira.run(call)
    print("result:", message.content)

    # An agent takes it apart from its own tools:
    #   skye.agent(REACT, model="gpt-4o-mini", tools=[refund, invoice], toolkits=[jira])
    await jira.close()


if __name__ == "__main__":
    asyncio.run(main())
