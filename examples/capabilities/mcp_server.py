"""Use the tools of an MCP server as capabilities of a model (needs a running server).

``create_mcp_client`` returns the built-in client (standard library, no extra); ``list_tools``
already gives capabilities, so hand them to the model, run the calls it asks for and send the
results back. Set MCP_SERVER_URL (for example http://localhost:8000/mcp). Without a server the
example says so and stops. With OPENAI_API_KEY set the model is real, otherwise a scripted
client answers.
"""

import asyncio
import os
import sys
from pathlib import Path

import skye
from skye import SkyeError, UserMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # the shared offline helper lives in examples/
from _offline import get_client  # noqa: E402

SERVER_URL = os.getenv("MCP_SERVER_URL")


async def main() -> None:
    if not SERVER_URL:
        print("MCP_SERVER_URL not set: start an MCP server and set its address, then run again")
        return

    mcp = skye.mcp_client(SERVER_URL)  # impl="fastmcp" (extra `mcp`) only if you ask for it
    try:
        capabilities = await mcp.list_tools()
    except (OSError, SkyeError) as error:
        print(f"Could not reach the MCP server at {SERVER_URL}: {error}")
        return
    print(f"{len(capabilities)} tool(s):", ", ".join(c.get_schema().name for c in capabilities))

    model = get_client("openai")
    question = [UserMessage(content="Use the available tools to help me")]
    response = model.complete(messages=question, model="gpt-4", capabilities=capabilities)
    if not response.has_capability_calls():
        print(response.content)
        return
    for call in response.capability_calls:
        print(f"the model asks for: {call.name}({call.arguments})")
    results = await response.aexecute_capability_calls()
    final = model.complete(messages=[*question, response.to_message(), *results], model="gpt-4", capabilities=capabilities)
    print(final.content)


if __name__ == "__main__":
    asyncio.run(main())
