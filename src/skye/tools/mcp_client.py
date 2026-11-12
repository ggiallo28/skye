"""Tri-faceted MCP client in ``tools``: tools, prompts and resources behind one Port (Req. 15).

* :class:`MCPClientInterface` is the one Port. ``SkyeMCPClient`` (stdlib JSON-RPC over
  stateless HTTP, built on ``skye.base.http``; ``skye.tools.plugins.skyemcp``) and ``FastMCPClient``
  (``skye.tools.plugins.fastmcp``, lazily imported) both implement it and return the same
  Skye types: ``CapabilityInterface``
  objects for tools, ``base`` messages for prompts (never ``prompts`` objects, D26),
  :class:`Resource` for resources.
* The resources facet is the resource Port of ``base`` (``ResourceProviderInterface``, D26):
  every MCP client implements it.
* Protocol shapes are converted in exactly one place, ``skye.tools.mcp_boundary``.
* Choice: :func:`create_mcp_client` takes an explicit ``impl`` argument, the name of a registered implementation
  (``"skyemcp"`` by default, ``"fastmcp"`` opt-in, or one a plugin registers). No environment variable, no config entry, no fallback (Requirement 21).
* The built-in client only consumes MCP servers over HTTP: no stdio transport, no subprocess,
  it never starts a server (Requirement 21).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from abc import ABC, abstractmethod
from typing import Any

from skye.base.interfaces.capability import CapabilityInterface, CapabilitySchema
from skye.base.interfaces.resource import Resource, ResourceProviderInterface
from skye.base.messages import SkyeMessage
from skye.base.plugins import get_registrar
from skye.tools import mcp_boundary as boundary
from skye.tools.exceptions import CapabilityExecutionError
from skye.tools.mcp_boundary import MCPPrompt

PROTOCOL_VERSION = "2025-06-18"


class MCPClientInterface(ResourceProviderInterface, ABC):
    """The MCP client Port: three facets, identical Skye return types in every implementation.

    The resources facet is the ``base`` resource Port (``ResourceProviderInterface``, D26), so an
    MCP client can be passed wherever a resource provider is expected.
    """

    # tools
    @abstractmethod
    async def list_tools(self) -> list[CapabilityInterface]: ...

    @abstractmethod
    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any: ...

    # prompts
    @abstractmethod
    async def list_prompts(self) -> list[MCPPrompt]: ...

    @abstractmethod
    async def get_prompt(
        self, name: str, arguments: dict[str, str] | None = None
    ) -> list[SkyeMessage]: ...

    # resources
    @abstractmethod
    async def list_resources(self) -> list[Resource]: ...

    @abstractmethod
    async def read_resource(self, uri: str) -> Resource: ...


class MCPToolCapability(CapabilityInterface):
    """A Skye capability backed by a tool on an MCP server (executes through the client)."""

    def __init__(self, schema: CapabilitySchema, client: MCPClientInterface) -> None:
        self._schema = schema
        self._client = client

    def get_schema(self) -> CapabilitySchema:
        return self._schema

    async def aexecute(self, **kwargs: Any) -> Any:
        return await self._client.call_tool(self._schema.name, kwargs)

    def execute(self, **kwargs: Any) -> Any:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.aexecute(**kwargs))
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, self.aexecute(**kwargs)).result()


def _tool_value(name: str, raw: Any) -> Any:
    result = boundary.to_tool_result(raw)
    if result.is_error:
        raise CapabilityExecutionError(
            f"MCP tool '{name}' reported an error: {result.value}", capability_name=name
        )
    return result.value


class _ToolsFacet:
    def _capabilities(self, raws: list[Any]) -> list[CapabilityInterface]:
        return [MCPToolCapability(boundary.to_tool_schema(r), self) for r in raws]  # type: ignore[arg-type]


def create_mcp_client(
    target: Any,
    impl: str = "skyemcp",
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> MCPClientInterface:
    """Build the MCP client for ``target`` (an HTTP URL, or anything fastmcp accepts).

    ``impl`` is the name of a registered implementation: ``"skyemcp"`` (default, standard library), ``"fastmcp"``, or one a plugin
    added with ``registrar.mcp_client``. An unknown name raises ``ConfigurationError`` listing the registered names and returns no
    client. The choice is this argument only: no environment variable, no configuration entry, no fallback. ``impl="fastmcp"``
    without fastmcp installed raises ``MissingExtraError`` naming the extra ``mcp``.
    """
    factory = get_registrar().get("mcp_client", impl)
    client: MCPClientInterface = factory(target, headers=headers, timeout=timeout)
    return client
