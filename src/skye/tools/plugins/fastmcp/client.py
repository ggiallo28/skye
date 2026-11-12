"""fastmcp-backed MCP client behind :class:`MCPClientInterface` (Requirement 15).

fastmcp is imported lazily when a client is constructed, never at ``import skye`` or
``import skye.tools``. Everything fastmcp returns goes straight into
``skye.tools.mcp_boundary``; no fastmcp/``mcp.types`` object leaves this module.
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, ParamSpec, TypeVar

from skye.base.exceptions import ProviderError, SkyeError
from skye.base.interfaces.capability import CapabilityInterface
from skye.base.interfaces.resource import Resource
from skye.base.lazy_import import missing_extra
from skye.base.messages import SkyeMessage
from skye.tools import mcp_boundary as boundary
from skye.tools.mcp_boundary import MCPPrompt
from skye.tools.mcp_client import MCPClientInterface, _tool_value, _ToolsFacet

_T = TypeVar("_T")
_P = ParamSpec("_P")


def _skye_errors(fn: Callable[_P, Awaitable[_T]]) -> Callable[_P, Coroutine[Any, Any, _T]]:
    """Convert what the fastmcp/mcp/httpx stack raises into ``ProviderError`` (built-in category).

    Without this a protocol error surfaces as ``mcp.shared.exceptions.MCPError`` (a library type
    leaking past the boundary); found by the differential tests.
    """

    @functools.wraps(fn)
    async def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _T:
        try:
            return await fn(*args, **kwargs)
        except SkyeError:
            raise
        except Exception as e:
            code = getattr(getattr(e, "error", None), "code", None)
            raise ProviderError(f"MCP error: {e}", provider="mcp", code=code) from e

    return wrapper


class FastMCPClient(_ToolsFacet, MCPClientInterface):
    """Each call opens a short-lived ``fastmcp.Client`` session (stateless, like the built-in)."""

    def __init__(
        self, target: Any, *, headers: dict[str, str] | None = None, timeout: float = 30.0
    ) -> None:
        self._fastmcp = missing_extra("fastmcp", extra="mcp")
        self._target = target
        self._kwargs: dict[str, Any] = {"timeout": timeout}
        if headers:
            from_transport = getattr(self._fastmcp, "client", None)
            transport_mod = getattr(from_transport, "transports", None)
            if transport_mod is not None and isinstance(target, str):
                self._target = transport_mod.StreamableHttpTransport(target, headers=headers)

    def _client(self) -> Any:
        return self._fastmcp.Client(self._target, **self._kwargs)

    @_skye_errors
    async def list_tools(self) -> list[CapabilityInterface]:
        async with self._client() as c:
            return self._capabilities(await c.list_tools())

    @_skye_errors
    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        async with self._client() as c:
            raw = await c.call_tool(name, arguments or {}, raise_on_error=False)
        return _tool_value(name, raw)

    @_skye_errors
    async def list_prompts(self) -> list[MCPPrompt]:
        async with self._client() as c:
            return [boundary.to_prompt(p) for p in await c.list_prompts()]

    @_skye_errors
    async def get_prompt(
        self, name: str, arguments: dict[str, str] | None = None
    ) -> list[SkyeMessage]:
        async with self._client() as c:
            return boundary.to_prompt_messages(await c.get_prompt(name, arguments or {}))

    @_skye_errors
    async def list_resources(self) -> list[Resource]:
        async with self._client() as c:
            return [boundary.to_resource(r) for r in await c.list_resources()]

    @_skye_errors
    async def read_resource(self, uri: str) -> Resource:
        async with self._client() as c:
            return boundary.to_read_resource(await c.read_resource(uri))
