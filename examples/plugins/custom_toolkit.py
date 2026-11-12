"""Add a toolkit.

A toolkit is a named set of tools that Skye builds when you ask for it by name: for tools that
several agents share or that need a setup (a connection, a folder, a key). The functions of one
agent are not a toolkit: write them with `@capability` and pass them in `tools=`.

You use `@plugins.toolkit("name")` on a class that extends `skye.Toolkit`:

* An `__init__` with the options of the toolkit, as keyword arguments.
* One method for each tool, with the `@capability` you use on a function (name, description,
  `return_direct`); `self` is not part of the schema.
* A tool outside the class, a function with `@capability`, goes in `tools=[...]` of the decorator.
* `async close()`, if the toolkit holds something to release.

The name of a tool is the toolkit and the method: `create_issue` of `"jira"` is `jira.create_issue`.
You never write the prefix, so a toolkit never clashes with your tools. Two instances of one toolkit
take an `alias`: `skye.toolkit("jira", alias="jira-eu", ...)`. Functions with no state need no
class: `plugins.toolkit("text", tools=[slugify])`. An agent takes it in `toolkits=[...]`.
"""

import asyncio

import skye
from skye.completion import CapabilityCall
from skye.tools import capability

plugins = skye.Plugins()


@capability
def slugify(title: str) -> str:
    """Make the part of an address that comes from a title."""
    return "-".join(title.lower().split())


@plugins.toolkit("jira", tools=[slugify])  # a tool written outside the class, added here
class JiraToolkit(skye.Toolkit):
    def __init__(self, *, base_url: str) -> None:
        self.base_url = base_url  # stands for the connection of a real client

    @capability
    def create_issue(self, title: str) -> str:
        """Create an issue and return its key."""
        return f"PROJ-1 created at {self.base_url}: {title}"

    @capability(return_direct=True)
    def issue_url(self, key: str) -> str:
        """The address of an issue, ready to be given back as it is."""
        return f"{self.base_url}/browse/{key}"

    @capability(
        name="close_issue",
        description="Close an issue that is done or no longer needed.",
    )
    def move_to_done(self, key: str) -> str:
        # A name of its own: the tool is `jira.close_issue`, whatever the method is called.
        return f"{key} closed"

    async def close(self) -> None:
        print("connection closed")


async def main() -> None:
    jira = skye.toolkit("jira", base_url="https://acme.example/jira")
    print("tools:", [schema.name for schema in await jira.list_schemas()])

    call = CapabilityCall(id="1", name="jira.create_issue", arguments={"title": "Broken login"})
    message = await jira.run(call)
    print("result:", message.content)

    # An agent: skye.agent(REACT, model=..., tools=[refund], toolkits=[jira])
    await jira.close()


if __name__ == "__main__":
    asyncio.run(main())
