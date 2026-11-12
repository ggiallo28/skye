"""Prototype staging for the standard-library MCP client (structure spec, task 7.2, Requirement 15).

Task 14.3 already shipped :class:`~skye.tools.mcp_client.SkyeMCPClient`: a standard-library
JSON-RPC 2.0 client over stateless HTTP, built on ``skye.base.http`` (the base-layer home of
the shared stdlib transport, re-exported by ``skye.base.http``), behind the one
:class:`~skye.tools.mcp_client.MCPClientInterface` alongside the fastmcp implementation.

Task 14.4 is the *future target*: driving the MCP extra toward **zero third-party libraries** so
the built-in client can stand alone, while the ``fastmcp`` extra stays until that lands. This
module stages that target by pinning the property rather than changing any default:

* the built-in client's module closure (``mcp_client`` + ``mcp_boundary`` + ``mcp_resource``)
  imports none of the MCP protocol/transport third-party libraries (``fastmcp``, ``mcp``,
  ``httpx``, ``requests``);
* the built-in client runs its full JSON-RPC request/response cycle (framing, parsing, the
  single boundary conversion, and error handling) with those libraries forcibly absent from
  ``sys.modules``, using a mocked transport and no live network.

If this file ever needs ``fastmcp``/``mcp``/``httpx``/``requests`` to pass, the stdlib path has
regressed off the zero-third-party target and the regression is caught here.
"""

from __future__ import annotations

import ast
import importlib
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from skye.base import http
from skye.base.exceptions import ProviderError, ValidationError
from skye.base.messages import AssistantMessage, UserMessage
from skye.base.interfaces.capability import CapabilityInterface
from skye.tools.plugins.skyemcp import SkyeMCPClient
from skye.tools.mcp_resource import Resource

# The MCP protocol/transport libraries the future target drives to zero for the built-in path.
MCP_THIRD_PARTY = ("fastmcp", "mcp", "httpx", "requests")

# The modules that make up the standard-library built-in MCP client path.
BUILTIN_PATH_MODULES = (
    "src/skye/tools/mcp_client.py",
    "src/skye/tools/plugins/skyemcp/client.py",
    "src/skye/tools/mcp_boundary.py",
    "src/skye/tools/mcp_resource.py",
)

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _top_level_imports(path: Path) -> set[str]:
    """Every top-level module name imported statically or in a function in ``path``."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_skyemcp_path_source_imports_no_mcp_third_party() -> None:
    """Static check: none of mcp_client/boundary/resource names an MCP protocol/transport lib."""
    offenders: list[str] = []
    for rel in BUILTIN_PATH_MODULES:
        path = _REPO_ROOT / rel
        for name in _top_level_imports(path):
            if name in MCP_THIRD_PARTY:
                offenders.append(f"{rel} imports '{name}'")
    assert not offenders, (
        "The standard-library MCP client path must stay free of MCP third-party libraries "
        f"(future target, task 14.4): {offenders}"
    )


def test_skyemcp_client_importable_with_mcp_third_party_absent() -> None:
    """A fresh import of the built-in path works with fastmcp/mcp/httpx/requests blocked."""
    blocked = {name: None for name in MCP_THIRD_PARTY}
    skyemcp_modules = [
        "skye.tools.mcp_client",
        "skye.tools.plugins.skyemcp",
        "skye.tools.plugins.skyemcp.client",
        "skye.tools.mcp_boundary",
        "skye.tools.mcp_resource",
    ]
    saved = {name: sys.modules.pop(name, None) for name in skyemcp_modules}
    try:
        with patch.dict(sys.modules, blocked):
            module = importlib.import_module("skye.tools.plugins.skyemcp")
            assert module.SkyeMCPClient is not None
            # Each name stays blocked (value None): importing the built-in path never pulled in
            # a real fastmcp/mcp/httpx/requests module.
            assert all(sys.modules.get(name) is None for name in MCP_THIRD_PARTY)
    finally:
        for name in skyemcp_modules:
            sys.modules.pop(name, None)
        for name, mod in saved.items():
            if mod is not None:
                sys.modules[name] = mod
        importlib.import_module("skye.tools.mcp_client")


class _FakeTransport:
    """Mocked ``skye.base.http.request`` recording calls and replying with canned JSON-RPC."""

    def __init__(self, handler: Any) -> None:
        self._handler = handler
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        url: str,
        method: str = "GET",
        *,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
        provider: str = "http",
        **_: Any,
    ) -> http.HttpResponse:
        self.calls.append({"url": url, "method": method, "body": json_body, "headers": headers})
        result = self._handler(json_body["method"], json_body.get("params"))
        reply: dict[str, Any] = {"jsonrpc": "2.0", "id": json_body["id"]}
        if isinstance(result, dict) and "error" in result:
            reply["error"] = result["error"]
        else:
            reply["result"] = result
        return http.HttpResponse(status_code=200, text=json.dumps(reply))


_TOOLS = [
    {"name": "add", "description": "Add", "inputSchema": {"type": "object"}},
    {"name": "boom", "inputSchema": {"type": "object"}},
]


def _handler(method: str, params: dict[str, Any] | None) -> Any:
    if method == "tools/list":
        return {"tools": _TOOLS}
    if method == "tools/call":
        assert params is not None
        if params["name"] == "boom":
            return {"content": [{"type": "text", "text": "bad"}], "isError": True}
        return {"content": [{"type": "text", "text": str(params["arguments"]["a"] + 1)}]}
    if method == "prompts/get":
        return {
            "messages": [
                {"role": "user", "content": {"type": "text", "text": "hi"}},
                {"role": "assistant", "content": {"type": "text", "text": "ok"}},
            ]
        }
    if method == "resources/read":
        return {"contents": [{"uri": params["uri"], "mimeType": "text/plain", "text": "body"}]}
    if method == "unknown/method":
        return {"error": {"code": -32601, "message": "method not found"}}
    raise AssertionError(f"unexpected method {method}")


@pytest.fixture
def fake_transport() -> _FakeTransport:
    """Patch the stdlib transport the built-in client calls, with MCP libs blocked too."""
    transport = _FakeTransport(_handler)
    # While the client runs, fastmcp/mcp/httpx/requests are blocked (value None in sys.modules):
    # any attempt to import one of them would raise, proving the stdlib path needs none of them.
    with patch.dict(sys.modules, {name: None for name in MCP_THIRD_PARTY}):
        with patch("skye.tools.plugins.skyemcp.client.http.request", transport):
            yield transport


@pytest.mark.asyncio
async def test_stdlib_client_tools_facet(fake_transport: _FakeTransport) -> None:
    """Framing, parsing and the tools->Capability boundary all run on stdlib only."""
    client = SkyeMCPClient("https://server/mcp", headers={"Authorization": "Bearer t"})
    tools = await client.list_tools()

    assert [t.get_schema().name for t in tools] == ["add", "boom"]
    assert all(isinstance(t, CapabilityInterface) for t in tools)
    # request framing: JSON-RPC 2.0 envelope, protocol-version header, caller header preserved.
    first = fake_transport.calls[0]
    assert first["body"]["jsonrpc"] == "2.0"
    assert first["body"]["method"] == "tools/list"
    assert first["headers"]["MCP-Protocol-Version"]
    assert first["headers"]["Authorization"] == "Bearer t"
    # response parsing + boundary conversion end to end.
    assert await tools[0].aexecute(a=1) == "2"


@pytest.mark.asyncio
async def test_stdlib_client_prompt_and_resource_facets(fake_transport: _FakeTransport) -> None:
    """prompts->Skye messages and resources->Resource convert at the single boundary."""
    client = SkyeMCPClient("https://server/mcp")

    messages = await client.get_prompt("greet", {"who": "x"})
    assert isinstance(messages[0], UserMessage)
    assert isinstance(messages[1], AssistantMessage)

    resource = await client.read_resource("file:///a.txt")
    assert isinstance(resource, Resource)
    assert resource.text == "body"
    assert resource.mime_type == "text/plain"


@pytest.mark.asyncio
async def test_stdlib_client_tool_error_maps_to_skye(fake_transport: _FakeTransport) -> None:
    """A tool-level MCP error surfaces as a Skye error, not a protocol type."""
    from skye.tools.exceptions import CapabilityExecutionError

    client = SkyeMCPClient("https://server/mcp")
    tools = await client.list_tools()
    with pytest.raises(CapabilityExecutionError):
        await tools[1].aexecute()


@pytest.mark.asyncio
async def test_stdlib_client_rpc_error_maps_to_provider_error(
    fake_transport: _FakeTransport,
) -> None:
    """A JSON-RPC error object becomes a ProviderError naming the message (no protocol leak)."""
    client = SkyeMCPClient("https://server/mcp")
    import asyncio

    with pytest.raises(ProviderError, match="method not found"):
        await asyncio.to_thread(client._rpc, "unknown/method")


@pytest.mark.asyncio
async def test_stdlib_client_rejects_malformed_result(fake_transport: _FakeTransport) -> None:
    """A JSON-RPC reply without 'result' or 'error' is rejected, naming the missing field."""
    import asyncio

    client = SkyeMCPClient("https://server/mcp")

    def _bare(
        url: str, method: str = "GET", *, json_body: Any = None, **_: Any
    ) -> http.HttpResponse:
        # A well-formed JSON-RPC envelope that carries neither 'result' nor 'error'.
        return http.HttpResponse(
            status_code=200,
            text=json.dumps({"jsonrpc": "2.0", "id": json_body["id"]}),
        )

    with patch("skye.tools.plugins.skyemcp.client.http.request", _bare):
        with pytest.raises(ValidationError, match="result"):
            await asyncio.to_thread(client._rpc, "tools/list")
