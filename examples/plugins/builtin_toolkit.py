"""Use the built-in toolkits.

Skye ships toolkits, sets of tools that an agent takes apart from its own `tools=`. Each one is a
plugin, so you build it by name with `skye.toolkit(name, **options)`:

* `"files"`: reads the files under a folder. The folder (`root`) is required and nothing outside it
  can be read.
* `"openapi"`: one tool for each operation of an OpenAPI document (`spec`).

You do not always ask for one. Giving the agent a `SKILL.md` (`skills=[...]`) makes it add `files`
by itself, limited to the folder of that skill.

A built-in toolkit is a plugin like yours, so you can build on it. `acme-api` below is the `openapi`
toolkit with the document of one API and the key already set: an agent asks for `acme-api` with just
the key, and never sees the address or the header.
"""

import asyncio
from pathlib import Path

import skye
from skye.agents import REACT

plugins = skye.Plugins()

OpenApiToolkit = plugins.get("toolkit", "openapi")  # the class that ships with Skye


HERE = Path(__file__).parent
ACME = {  # the OpenAPI document of the API; a real one is a path or an address, `spec="https://.../openapi.json"`
    "openapi": "3.0.0",
    "servers": [{"url": "https://api.acme.example"}],
    "paths": {"/orders/{id}": {"get": {"operationId": "get_order", "summary": "Read an order"}}},
}


@plugins.toolkit("acme-api")
class AcmeApiToolkit(OpenApiToolkit):
    def __init__(self, *, api_key: str) -> None:
        super().__init__(spec=ACME, headers={"Authorization": f"Bearer {api_key}"})


async def main() -> None:
    files = skye.toolkit("files", root=HERE)
    print("files:", [schema.name for schema in await files.list_schemas()])

    acme = skye.toolkit("acme-api", api_key="not-a-real-key")  # built on `openapi`, see above
    print("acme-api:", [schema.name for schema in await acme.list_schemas()])

    # `skills=` makes the agent add its own `files`, limited to the folder of the skill, so `files`
    # is not passed here again.
    agent = skye.agent(
        REACT,
        model="gpt-4o-mini",
        toolkits=[acme],
        skills=[str(HERE / "skills" / "refund-policy" / "SKILL.md")],
    )
    print("added for the skill:", [type(toolkit).__name__ for toolkit in agent.skill_toolkits])


if __name__ == "__main__":
    asyncio.run(main())
