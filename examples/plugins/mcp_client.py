"""Add an MCP client.

To add an MCP client you use the decorator `@plugins.mcp_client("name")` on top of a class.

The class has:

* An `__init__` that receives the `target` (the server) and the keyword arguments `headers` and
  `timeout`.
* The methods of the `MCPClientInterface` Port, all `async`: `list_tools`, `call_tool`,
  `list_prompts`, `get_prompt`, `list_resources` and `read_resource`.

`skye.mcp_client(target, impl="name")` builds it, as it builds `"skyemcp"` and `"fastmcp"`.

Tip: this one answers from memory, which is also the way to test code that uses an MCP client
without a server.
"""

import asyncio
from typing import Any

import skye
from skye.tools import MCPClientInterface, MCPPrompt, Resource, capability

plugins = skye.Plugins()


@capability
def shout(text: str) -> str:
    """Return the text in capital letters."""
    return text.upper()


@plugins.mcp_client("memory")
class MemoryMCPClient(MCPClientInterface):
    def __init__(
        self, target: Any, *, headers: dict[str, str] | None = None, timeout: float = 30.0
    ) -> None:
        self.target = target

    async def list_tools(self):
        return [shout]

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        return await shout.aexecute(**(arguments or {}))

    async def list_prompts(self) -> list[MCPPrompt]:
        return []

    async def get_prompt(self, name: str, arguments: dict[str, str] | None = None):
        return []

    async def list_resources(self) -> list[Resource]:
        return [Resource(uri="memory://readme", name="readme")]

    async def read_resource(self, uri: str) -> Resource:
        return Resource(uri=uri, name="readme", text="Served from memory.")


async def main() -> None:
    client = skye.mcp_client("memory://demo", impl="memory")
    print("tools:", [tool.get_schema().name for tool in await client.list_tools()])
    print("call_tool:", await client.call_tool("shout", {"text": "hello"}))
    print("resource:", (await client.read_resource("memory://readme")).text)


if __name__ == "__main__":
    asyncio.run(main())
