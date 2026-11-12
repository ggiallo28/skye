"""Use the built-in toolkits.

Skye ships toolkits, sets of tools that an agent takes apart from its own `tools=`. Each one is a
plugin, so you build it by name with `skye.toolkit(name, **options)`:

* `"files"`: reads the files under a folder. The folder (`root`) is required and nothing outside it
  can be read.
* `"openapi"`: one tool for each operation of an OpenAPI document (`spec`).
* `"mcp"`: the tools of an MCP server, by its address (`target`).

You do not always ask for one. Giving the agent a `SKILL.md` (`skills=[...]`) makes it add `files`
by itself, limited to the folder of that skill.

A built-in toolkit is a plugin like yours, so you can build on it. `acme-api` below is the `openapi`
toolkit with the document of one API and the key already set: an agent asks for `acme-api` with just
the key, and never sees the address or the header.
"""

import asyncio

import skye
from skye.agents import REACT

plugins = skye.Plugins()

OpenApiToolkit = plugins.get("toolkit", "openapi")  # the class that ships with Skye


@plugins.toolkit("acme-api")
class AcmeApiToolkit(OpenApiToolkit):
    def __init__(self, *, api_key: str) -> None:
        super().__init__(
            spec="https://api.acme.example/openapi.json",
            headers={"Authorization": f"Bearer {api_key}"},
        )


async def main() -> None:
    files = skye.toolkit("files", root="docs")
    print("files:", [schema.name for schema in await files.list_schemas()])

    mcp = skye.toolkit("mcp", target="http://localhost:8000/mcp")
    acme = skye.toolkit("acme-api", api_key="not-a-real-key")  # built on `openapi`, see above

    agent = skye.agent(
        REACT,
        model="gpt-4o-mini",
        toolkits=[files, mcp, acme],
        skills=["examples/plugins/skills/refund-policy/SKILL.md"],  # adds `files` for this folder
    )
    print(await agent.invoke("What is the refund policy?"))


if __name__ == "__main__":
    asyncio.run(main())
