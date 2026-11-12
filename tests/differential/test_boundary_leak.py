"""Boundary rule at runtime, both MCP clients (needs fastmcp; Requirement 16, task 7.4).

Built-in and fastmcp clients, against the local fake server, return identical Skye types and
nothing originating from `mcp`/`fastmcp`/`httpx`. The static half is tests/budget/test_boundary_rule.py.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastmcp", reason="fastmcp not installed (dev/test dependency group)")

from skye.tools.plugins.skyemcp import SkyeMCPClient  # noqa: E402
from skye.tools.plugins.fastmcp import FastMCPClient  # noqa: E402
from tests.budget.test_boundary_rule import _foreign_types  # noqa: E402


async def _surface(c):
    tools = await c.list_tools()
    return {
        "tools": tools,
        "schemas": [t.get_schema() for t in tools],
        "call": await c.call_tool("add", {"a": 1, "b": 2}),
        "prompts": await c.list_prompts(),
        "messages": await c.get_prompt("greet", {"who": "Ada"}),
        "resources": await c.list_resources(),
        "resource": await c.read_resource("file:///notes.txt"),
    }


async def test_mcp_clients_expose_only_skye_types_and_same_types(mcp_server):
    out = [await _surface(c) for c in (SkyeMCPClient(mcp_server.url), FastMCPClient(mcp_server.url))]
    for surface in out:
        assert not _foreign_types(surface)
    for key in out[0]:
        a, b = out[0][key], out[1][key]
        ta = [type(x) for x in a] if isinstance(a, list) else type(a)
        tb = [type(x) for x in b] if isinstance(b, list) else type(b)
        assert ta == tb, key
