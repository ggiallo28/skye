"""MCP prompts and resources through the built-in client (Live, guarded where empty).

Besides tools, an MCP server can expose prompts and resources. The built-in client reads
them through the same Port: ``list_prompts()``/``get_prompt(name)`` return base
``SkyeMessage`` objects, and ``list_resources()``/``read_resource(uri)`` return
``skye.tools.Resource``. A server that advertises none is handled cleanly with a note.

The ``MCPPrompt``, ``MCPPromptArgument`` and ``Resource`` types are imported below to show
the shapes the client returns.

Set MCP_SERVER_URL to the address of a server (default: http://localhost:8000/mcp).
"""

import asyncio
import os

from skye import SkyeError
from skye.tools import MCPPrompt, MCPPromptArgument, Resource, create_mcp_client


def show_types() -> None:
    """Construct the prompt/resource types to show their shape, without a server."""
    prompt = MCPPrompt(
        name="summarize",
        description="Summarize a document",
        arguments=(MCPPromptArgument(name="text", description="Text to summarize", required=True),),
    )
    resource = Resource(uri="file:///notes.txt", name="notes", mime_type="text/plain")
    print(f"prompt descriptor: {prompt.name} args={[a.name for a in prompt.arguments]}")
    print(f"resource descriptor: {resource.name} ({resource.uri})")


async def main() -> None:
    url = os.getenv("MCP_SERVER_URL", "http://localhost:8000/mcp")
    client = create_mcp_client(url, impl="skyemcp")

    show_types()

    # Prompts: guard cleanly when the server advertises none.
    try:
        prompts = await client.list_prompts()
    except SkyeError:
        print("no prompts advertised by this server, skipping prompts")
    else:
        print(f"{len(prompts)} prompt(s):")
        for prompt in prompts:
            print("  -", prompt.name)
            messages = await client.get_prompt(prompt.name)
            print(f"    rendered into {len(messages)} message(s)")

    # Resources: same guard.
    try:
        resources = await client.list_resources()
    except SkyeError:
        print("no resources advertised by this server, skipping resources")
    else:
        print(f"{len(resources)} resource(s):")
        for res in resources:
            print("  -", res.name, res.uri)
            content = await client.read_resource(res.uri)
            print(f"    read: has_content={content.has_content}")


if __name__ == "__main__":
    asyncio.run(main())
