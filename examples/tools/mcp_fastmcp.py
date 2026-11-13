"""MCP client implementations: built-in vs ``fastmcp`` (Live, ``fastmcp`` branch guarded).

``skye.mcp_client(url, impl="skyemcp")`` returns the standard-library MCP client (no
extra to install); ``impl="fastmcp"`` opts into the ``fastmcp``-backed client, which needs
the optional ``mcp`` extra. Both implementations return identical Skye types
(``CapabilityInterface`` tools, ``MCPPrompt`` prompts, ``Resource`` resources).

This example lists the tools over the built-in client (answered offline by the test fake),
then tries the ``fastmcp`` implementation inside a guard that prints a skip note when the
extra is absent.

Set MCP_SERVER_URL to the address of a server (default: http://localhost:8000/mcp).
"""

import asyncio
import os

import skye
from skye import MissingExtraError, SkyeError


async def main() -> None:
    url = os.getenv("MCP_SERVER_URL", "http://localhost:8000/mcp")

    # Live: the built-in client talks JSON-RPC over HTTP (standard library only).
    client = skye.mcp_client(url, impl="skyemcp")
    try:
        tools = await client.list_tools()
    except (OSError, SkyeError) as error:
        print(f"No MCP server answered at {url} ({type(error).__name__}).")
        print("Start one (see capabilities/mcp_server.py) or set MCP_SERVER_URL to its address.")
        return
    print(f"built-in client: {len(tools)} tool(s) on {url}")
    for tool in tools:
        print("  -", tool.get_schema().name)

    # Opt-in: the fastmcp implementation ships with the `mcp` extra. When the extra is
    # absent, creating the client raises and we print a skip note.
    try:
        skye.mcp_client(url, impl="fastmcp")
    except (ImportError, MissingExtraError):
        print("fastmcp client: `mcp` extra not installed, skipping")
        return

    # The fastmcp client is available and returns the same Skye types as the built-in
    # one; we do not call it here because it needs a live fastmcp-compatible server.
    print("fastmcp client: available (returns the same Skye types as built-in)")


if __name__ == "__main__":
    asyncio.run(main())
