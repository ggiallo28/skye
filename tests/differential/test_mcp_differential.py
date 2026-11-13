"""MCP client: SkyeMCPClient vs FastMCPClient (real fastmcp) against a local fake server (Requirement 14).

Only the subset Skye consumes is compared: exact field-subset equality for structured values,
epsilon for numeric/timing values, category-level equivalence for errors.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastmcp", reason="fastmcp not installed (dev/test dependency group)")

from skye.base.exceptions import ProviderError  # noqa: E402
from skye.tools.exceptions import CapabilityExecutionError  # noqa: E402
from skye.tools.engines.skyemcp import SkyeMCPClient  # noqa: E402
from skye.tools.engines.fastmcp import FastMCPClient  # noqa: E402

EPS = 1e-9


@pytest.fixture
def clients(mcp_server):
    return SkyeMCPClient(mcp_server.url), FastMCPClient(mcp_server.url)


async def test_list_tools_same_schema_subset(clients):
    b, f = clients
    sb = {c.get_schema().name: c.get_schema() for c in await b.list_tools()}
    sf = {c.get_schema().name: c.get_schema() for c in await f.list_tools()}
    assert sb.keys() == sf.keys() >= {"add", "echo", "boom"}
    for name in sb:
        assert sb[name].description == sf[name].description
        assert sb[name].parameters["properties"] == sf[name].parameters["properties"]
        assert sb[name].parameters.get("required") == sf[name].parameters.get("required")


async def test_call_tool_structured_and_text(clients):
    b, f = clients
    rb, rf = await b.call_tool("add", {"a": 1.5, "b": 2}), await f.call_tool("add", {"a": 1.5, "b": 2})
    assert rb.keys() == rf.keys() == {"result"}
    assert rb["result"] == pytest.approx(rf["result"], abs=EPS) == pytest.approx(3.5, abs=EPS)
    assert await b.call_tool("echo", {"text": "hi"}) == await f.call_tool("echo", {"text": "hi"}) == "hi"


async def test_call_tool_timing_value_epsilon(clients):
    b, f = clients
    assert (await b.call_tool("timing"))["elapsed"] == pytest.approx((await f.call_tool("timing"))["elapsed"], abs=EPS)


async def test_tool_error_same_category(clients):
    """isError tool result -> CapabilityExecutionError in both (fastmcp via raise_on_error=False)."""
    for c in clients:
        with pytest.raises(CapabilityExecutionError, match="kaboom"):
            await c.call_tool("boom")


async def test_unknown_tool_same_category(clients):
    """Protocol-level error (JSON-RPC error): both raise ProviderError with the same code."""
    codes = []
    for c in clients:
        with pytest.raises(ProviderError) as ei:
            await c.call_tool("nope")
        codes.append(ei.value.details.get("code"))
    assert codes[0] == codes[1]


async def test_list_prompts_equivalent(clients):
    b, f = clients
    assert await b.list_prompts() == await f.list_prompts()


async def test_get_prompt_equivalent(clients):
    b, f = clients
    mb, mf = await b.get_prompt("greet", {"who": "Ada"}), await f.get_prompt("greet", {"who": "Ada"})
    assert [(type(m).__name__, m.content) for m in mb] == [(type(m).__name__, m.content) for m in mf]
    assert mb[0].content == "Say hello to Ada"


async def test_list_resources_equivalent(clients):
    b, f = clients
    assert await b.list_resources() == await f.list_resources()


async def test_read_resource_text_and_blob(clients):
    b, f = clients
    tb, tf = await b.read_resource("file:///notes.txt"), await f.read_resource("file:///notes.txt")
    assert (tb.uri, tb.mime_type, tb.text, tb.data) == (tf.uri, tf.mime_type, tf.text, tf.data)
    assert tb.text == "hello notes"
    bb, bf = await b.read_resource("file:///blob.bin"), await f.read_resource("file:///blob.bin")
    assert bb.data == bf.data and bb.text is None and bf.text is None


async def test_headers_reach_server(mcp_server):
    h = {"Authorization": "Bearer secret"}
    assert await SkyeMCPClient(mcp_server.url, headers=h).call_tool("headers") == "Bearer secret"
    assert await FastMCPClient(mcp_server.url, headers=h).call_tool("headers") == "Bearer secret"
