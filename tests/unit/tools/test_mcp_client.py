"""Tri-faceted MCP client: built-in against an in-process fake server, fastmcp via a fake module, boundary."""

import base64
import dataclasses
import json
import subprocess
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

import pytest

from skye.base.exceptions import (
    ConfigurationError,
    MissingExtraError,
    ProviderError,
    ValidationError,
)
from skye.base.messages import AssistantMessage, UserMessage
from skye.tools import mcp_boundary as b
from skye.tools.exceptions import CapabilityExecutionError
from skye.base.interfaces.capability import CapabilityInterface
from skye.tools.mcp_client import create_mcp_client
from skye.tools.engines.skyemcp import SkyeMCPClient
from skye.tools.mcp_resource import Resource

TOOLS = [
    {
        "name": "add",
        "description": "Add",
        "inputSchema": {"type": "object", "properties": {"a": {"type": "integer"}}},
    },
    {"name": "boom", "inputSchema": {"type": "object"}},
]
PROMPTS = [
    {"name": "greet", "description": "Greet", "arguments": [{"name": "who", "required": True}]}
]
RESOURCES = [{"uri": "file:///a.txt", "name": "a", "mimeType": "text/plain"}]


def _handle(method, params):
    if method == "tools/list":
        if params and params.get("cursor") == "p2":
            return {"tools": TOOLS[1:]}
        return {"tools": TOOLS[:1], "nextCursor": "p2"}
    if method == "tools/call":
        if params["name"] == "boom":
            return {"content": [{"type": "text", "text": "bad"}], "isError": True}
        return {"content": [{"type": "text", "text": str(params["arguments"]["a"] + 1)}]}
    if method == "prompts/list":
        return {"prompts": PROMPTS}
    if method == "prompts/get":
        return {
            "messages": [
                {
                    "role": "user",
                    "content": {"type": "text", "text": f"hi {params['arguments']['who']}"},
                },
                {"role": "assistant", "content": {"type": "text", "text": "ok"}},
            ]
        }
    if method == "resources/list":
        return {"resources": RESOURCES}
    if method == "resources/read":
        if params["uri"].endswith("bin"):
            return {
                "contents": [{"uri": params["uri"], "blob": base64.b64encode(b"\x00\x01").decode()}]
            }
        return {"contents": [{"uri": params["uri"], "mimeType": "text/plain", "text": "hello"}]}
    raise KeyError(method)


@pytest.fixture
def server():
    state = SimpleNamespace(sse=False, seen=[])

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state.seen.append((req, dict(self.headers)))
            try:
                msg = {
                    "jsonrpc": "2.0",
                    "id": req["id"],
                    "result": _handle(req["method"], req.get("params")),
                }
            except KeyError:
                msg = {
                    "jsonrpc": "2.0",
                    "id": req["id"],
                    "error": {"code": -32601, "message": "nope"},
                }
            body = json.dumps(msg)
            ctype = "application/json"
            if state.sse:
                body, ctype = f"event: message\ndata: {body}\n\n", "text/event-stream"
            data = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    state.url = f"http://127.0.0.1:{srv.server_port}/mcp"
    yield state
    srv.shutdown()
    srv.server_close()


@pytest.mark.asyncio
@pytest.mark.parametrize("sse", [False, True])
async def test_skyemcp_three_facets(server, sse):
    server.sse = sse
    c = SkyeMCPClient(server.url, headers={"Authorization": "Bearer x"})
    tools = await c.list_tools()  # follows nextCursor
    assert [t.get_schema().name for t in tools] == ["add", "boom"]
    assert all(isinstance(t, CapabilityInterface) for t in tools)
    assert tools[1].get_schema().description == "boom"
    assert await tools[0].aexecute(a=1) == "2"
    assert tools[0].execute(a=4) == "5"
    with pytest.raises(CapabilityExecutionError):
        await tools[1].aexecute()

    prompts = await c.list_prompts()
    assert prompts[0].name == "greet" and prompts[0].arguments[0].required
    msgs = await c.get_prompt("greet", {"who": "bob"})
    assert isinstance(msgs[0], UserMessage) and msgs[0].content == "hi bob"
    assert isinstance(msgs[1], AssistantMessage)

    assert await c.list_resources() == [
        Resource(uri="file:///a.txt", name="a", mime_type="text/plain")
    ]
    assert (await c.read_resource("file:///a.txt")).text == "hello"
    assert (await c.read_resource("file:///x.bin")).data == b"\x00\x01"
    assert server.seen[0][1]["Authorization"] == "Bearer x"
    assert server.seen[0][0]["jsonrpc"] == "2.0"


@pytest.mark.asyncio
async def test_skyemcp_rpc_error_and_transport(server):
    c = SkyeMCPClient(server.url)
    with pytest.raises(ProviderError, match="nope"):
        await asyncio_to(c, "bogus/method")
    with pytest.raises(ProviderError):
        await SkyeMCPClient("http://127.0.0.1:1/x", timeout=1).list_prompts()


async def asyncio_to(c, method):
    import asyncio

    return await asyncio.to_thread(c._rpc, method)


def test_empty_url_and_unknown_impl():
    with pytest.raises(ConfigurationError):
        SkyeMCPClient(" ")
    with pytest.raises(ConfigurationError):
        create_mcp_client("http://x", impl="nope")
    assert isinstance(create_mcp_client("http://x"), SkyeMCPClient)


# --- boundary ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fn,raw,field",
    [
        (b.to_tool_schema, {"inputSchema": {}}, "Tool.name"),
        (b.to_tool_schema, {"name": "t"}, "Tool.inputSchema"),
        (b.to_tool_schema, {"name": "t", "inputSchema": []}, "Tool.inputSchema"),
        (b.to_tool_schema, {"name": 3, "inputSchema": {}}, "Tool.name"),
        (b.to_prompt, {"description": "x"}, "Prompt.name"),
        (b.to_prompt, {"name": "p", "arguments": [{"required": True}]}, "PromptArgument.name"),
        (b.to_prompt, {"name": "p", "arguments": "x"}, "Prompt.arguments"),
        (b.to_prompt_messages, {}, "GetPromptResult.messages"),
        (
            b.to_prompt_messages,
            {"messages": [{"role": "system", "content": {"type": "text", "text": "x"}}]},
            "PromptMessage.role",
        ),
        (b.to_prompt_messages, {"messages": [{"role": "user"}]}, "PromptMessage.content"),
        (
            b.to_prompt_messages,
            {"messages": [{"role": "user", "content": {"type": "image"}}]},
            "PromptMessage.content.type",
        ),
        (
            b.to_prompt_messages,
            {"messages": [{"role": "user", "content": {"type": "text"}}]},
            "PromptMessage.content.text",
        ),
        (b.to_resource, {"name": "n"}, "Resource.uri"),
        (b.to_resource, {"uri": "u"}, "Resource.name"),
        (b.to_resource, {"uri": "u", "name": "n", "mimeType": 1}, "Resource.mimeType"),
        (b.to_read_resource, {"contents": [{"uri": "u"}]}, "ResourceContents.text"),
        (
            b.to_read_resource,
            {"contents": [{"uri": "u", "text": "a", "blob": "AA=="}]},
            "ResourceContents.text",
        ),
        (b.to_read_resource, {"contents": [{"uri": "u", "blob": "!!"}]}, "ResourceContents.blob"),
        (b.to_read_resource, {"contents": []}, "ReadResourceResult.contents"),
        (b.to_tool_result, {"content": [{"text": "x"}]}, "type"),
        (b.to_tool_result, {}, "CallToolResult.content"),
        (b.to_tool_result, {"content": [], "isError": "yes"}, "CallToolResult.isError"),
        (b.to_tool_schema, 42, "Tool"),
    ],
)
def test_boundary_rejects_naming_type_and_field(fn, raw, field):
    with pytest.raises(ValidationError) as e:
        fn(raw)
    assert field in str(e.value) or field.split(".")[-1] in str(e.value)
    assert field.split(".")[0] in str(e.value)


def test_boundary_accepts_objects_like_mcp_types():
    class Tool:  # pydantic-like
        def model_dump(self, by_alias=False, mode="python"):
            return {"name": "t", "inputSchema": {"type": "object"}, "description": "d"}

    s = b.to_tool_schema(Tool())
    assert (s.name, s.description, s.parameters) == ("t", "d", {"type": "object"})
    r = b.to_tool_result(
        {
            "content": [{"type": "text", "text": "x"}],
            "structured_content": {"k": 1},
            "is_error": False,
        }
    )
    assert r.value == {"k": 1}


# --- fastmcp implementation, with a fake module (fastmcp is not a dev dependency here) -----


class _Dump:
    def __init__(self, d):
        self.d = d

    def model_dump(self, by_alias=False, mode="python"):
        return self.d


@dataclasses.dataclass
class _CallToolResult:  # shaped like fastmcp.client.client.CallToolResult
    content: list
    structured_content: dict | None = None
    is_error: bool = False


def _fake_fastmcp():
    class Client:
        def __init__(self, target, **kw):
            self.target = target

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def list_tools(self):
            return [_Dump(t) for t in TOOLS]

        async def call_tool(self, name, args, raise_on_error=True):
            r = _handle("tools/call", {"name": name, "arguments": args})
            return _CallToolResult(
                content=[_Dump(c) for c in r["content"]], is_error=r.get("isError", False)
            )

        async def list_prompts(self):
            return [_Dump(p) for p in PROMPTS]

        async def get_prompt(self, name, args):
            return _Dump(_handle("prompts/get", {"name": name, "arguments": args}))

        async def list_resources(self):
            return [_Dump(r) for r in RESOURCES]

        async def read_resource(self, uri):
            return [_Dump(c) for c in _handle("resources/read", {"uri": uri})["contents"]]

    return types.SimpleNamespace(Client=Client, __name__="fastmcp")


@pytest.mark.asyncio
async def test_fastmcp_returns_identical_skye_types(server, monkeypatch):
    monkeypatch.setitem(sys.modules, "fastmcp", _fake_fastmcp())
    fc = create_mcp_client("http://x", impl="fastmcp")
    bi = SkyeMCPClient(server.url)
    f_tools, b_tools = await fc.list_tools(), await bi.list_tools()
    assert [t.get_schema() for t in f_tools][:1] == [t.get_schema() for t in b_tools][:1]
    assert await f_tools[0].aexecute(a=1) == await b_tools[0].aexecute(a=1) == "2"
    with pytest.raises(CapabilityExecutionError):
        await f_tools[1].aexecute()
    assert await fc.list_prompts() == await bi.list_prompts()
    fm, bm = await fc.get_prompt("greet", {"who": "z"}), await bi.get_prompt("greet", {"who": "z"})
    assert [(type(m), m.content) for m in fm] == [(type(m), m.content) for m in bm]
    assert await fc.list_resources() == await bi.list_resources()
    assert await fc.read_resource("file:///x.bin") == await bi.read_resource("file:///x.bin")


def test_fastmcp_missing_raises_without_fallback(monkeypatch):
    monkeypatch.setitem(sys.modules, "fastmcp", None)
    with pytest.raises(MissingExtraError) as exc:
        create_mcp_client("http://x", impl="fastmcp")
    assert exc.value.extra == "mcp"


def test_impl_is_an_argument_only(monkeypatch):
    """Requirement 21: no environment variable or config entry selects the client."""
    monkeypatch.setenv("SKYE_MCP_IMPL", "sdk")
    monkeypatch.setenv("SKYE_IMPL", "sdk")
    assert isinstance(create_mcp_client("http://x"), SkyeMCPClient)
    with pytest.raises(ConfigurationError):
        create_mcp_client("http://x", impl="sdk")


def test_fastmcp_not_imported_with_skye_or_tools():
    code = "import sys, skye, skye.tools; from skye.tools import create_mcp_client; create_mcp_client('http://x'); assert 'fastmcp' not in sys.modules"
    subprocess.run([sys.executable, "-c", code], check=True)
