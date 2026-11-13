# decision D26
"""``Resource`` for the MCP clients: re-exported from the resource Port in ``base``.

The type and its Port (``ResourceProviderInterface``) live in ``base`` so that ``prompts`` and
``memory`` consume MCP resources without importing ``tools``; this module keeps the
``skye.tools.mcp_resource`` path working.
"""

from skye.base.interfaces.resource import Resource, ResourceProviderInterface

__all__ = ["Resource", "ResourceProviderInterface"]
