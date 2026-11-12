"""The built-in MCP client of ``tools``: standard-library JSON-RPC over stateless HTTP (Requirement 15, 21; D16; plugins:7.7).

It implements :class:`~skye.tools.mcp_client.MCPClientInterface` on ``skye.base.http`` and consumes MCP servers over HTTP only: no stdio transport, no
subprocess, it never starts a server, and it needs no extra. It is the default ``impl`` of ``create_mcp_client``, registered as ``"skyemcp"``.

Raises: ``ConfigurationError`` for an empty URL; ``ProviderError`` for a JSON-RPC error or a malformed reply; ``ValidationError`` for a reply that lacks a field.
Missing: not applicable.
Concurrency: a client keeps a request counter and is meant for one task at a time; build one per task, as ``create_mcp_client`` does.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from skye.base import http
from skye.base.exceptions import ConfigurationError, ProviderError, ValidationError
from skye.base.interfaces.capability import CapabilityInterface
from skye.base.interfaces.resource import Resource
from skye.base.messages import SkyeMessage
from skye.tools import mcp_boundary as boundary
from skye.tools.mcp_boundary import MCPPrompt
from skye.tools.mcp_client import PROTOCOL_VERSION, MCPClientInterface, _tool_value, _ToolsFacet


class SkyeMCPClient(_ToolsFacet, MCPClientInterface):
    """Standard-library MCP client: JSON-RPC 2.0 over stateless HTTP POST (no session)."""

    def __init__(
        self, url: str, *, headers: dict[str, str] | None = None, timeout: float = 30.0
    ) -> None:
        if not isinstance(url, str) or not url.strip():
            raise ConfigurationError("MCP server url cannot be empty")
        self._url = url
        self._headers = {
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
            **(headers or {}),
        }
        self._timeout = timeout
        self._next_id = 0

    def _rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self._next_id += 1
        rid = self._next_id
        body: dict[str, Any] = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            body["params"] = params
        resp = http.request(
            self._url,
            "POST",
            json_body=body,
            headers=self._headers,
            timeout=self._timeout,
            provider="mcp",
        )
        msg = _decode_response(resp.text, rid)
        if "error" in msg:
            err = msg["error"] if isinstance(msg["error"], dict) else {}
            raise ProviderError(
                f"MCP error on {method}: {err.get('message', msg['error'])}",
                provider="mcp",
                code=err.get("code"),
            )
        if "result" not in msg:
            raise ValidationError(
                f"MCP {method}: field 'result' is required but absent",
                field=f"{method}.result",
                value=msg,
            )
        return msg["result"]

    async def _list(self, method: str, key: str) -> list[Any]:
        items: list[Any] = []
        cursor: str | None = None
        while True:
            result = await asyncio.to_thread(
                self._rpc, method, {"cursor": cursor} if cursor else None
            )
            page = result.get(key) if isinstance(result, dict) else None
            if not isinstance(page, list):
                raise ValidationError(
                    f"MCP {method}: field '{key}' must be a list",
                    field=f"{method}.{key}",
                    value=page,
                )
            items += page
            cursor = result.get("nextCursor")
            if not cursor:
                return items

    async def list_tools(self) -> list[CapabilityInterface]:
        return self._capabilities(await self._list("tools/list", "tools"))

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        raw = await asyncio.to_thread(
            self._rpc, "tools/call", {"name": name, "arguments": arguments or {}}
        )
        return _tool_value(name, raw)

    async def list_prompts(self) -> list[MCPPrompt]:
        return [boundary.to_prompt(r) for r in await self._list("prompts/list", "prompts")]

    async def get_prompt(
        self, name: str, arguments: dict[str, str] | None = None
    ) -> list[SkyeMessage]:
        raw = await asyncio.to_thread(
            self._rpc, "prompts/get", {"name": name, "arguments": arguments or {}}
        )
        return boundary.to_prompt_messages(raw)

    async def list_resources(self) -> list[Resource]:
        return [boundary.to_resource(r) for r in await self._list("resources/list", "resources")]

    async def read_resource(self, uri: str) -> Resource:
        raw = await asyncio.to_thread(self._rpc, "resources/read", {"uri": uri})
        return boundary.to_read_resource(raw)


def _decode_response(text: str, rid: int) -> dict[str, Any]:
    """Body of a JSON-RPC reply: plain JSON, or an SSE stream carrying the reply with our id."""
    stripped = text.lstrip()
    try:
        if stripped.startswith(("event:", "data:", ":")):
            for block in re.split(r"\r?\n\r?\n", stripped):
                data = "\n".join(
                    ln[5:].lstrip() for ln in block.splitlines() if ln.startswith("data:")
                )
                if not data:
                    continue
                msg = json.loads(data)
                if isinstance(msg, dict) and msg.get("id") == rid:
                    return msg
            raise ValueError(f"no reply with id {rid} in event stream")
        msg = json.loads(stripped)
    except ValueError as e:
        raise ProviderError(f"MCP: malformed JSON-RPC response: {e}", provider="mcp") from e
    if not isinstance(msg, dict):
        raise ProviderError("MCP: JSON-RPC response must be an object", provider="mcp")
    return msg
