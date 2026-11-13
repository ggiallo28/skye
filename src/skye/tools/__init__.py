"""Capability support for Skye.

This module provides a unified interface for registering, managing, and invoking
capabilities across different LLM providers. Capabilities can be local Python
functions, remote HTTP APIs, or MCP (Model Context Protocol) server capabilities.

``CapabilityInterface`` and ``CapabilitySchema`` are the base Port types (``skye.interfaces``),
re-exported here under the same names: a capability built from either import path registers.

Example:
    >>> from skye.tools import capability, CapabilityInterface, CapabilitySchema
    >>>
    >>> @capability
    ... def get_weather(location: str) -> str:
    ...     '''Get weather for a location.'''
    ...     return f"Weather for {location}"
    >>>
    >>> schema = get_weather.get_schema()
    >>> result = get_weather.execute(location="New York")

Codename: updraft.
"""

from skye.base.interfaces.capability import CapabilityInterface, CapabilitySchema
from skye.tools.capability_call_handler import CapabilityCallHandler
from skye.tools.capability_models import CapabilityCall, CapabilityResult
from skye.tools.decorator import capability
from skye.tools.exceptions import (
    CapabilityCallParsingError,
    CapabilityError,
    CapabilityExecutionError,
    CapabilityNotFoundError,
    CapabilityValidationError,
)
from skye.tools.local_function import LocalFunctionCapability
from skye.tools.mcp_boundary import MCPPrompt, MCPPromptArgument
from skye.tools.mcp_client import (
    MCPClientInterface,
    MCPToolCapability,
    create_mcp_client,
)
from skye.tools.engines.skyemcp import SkyeMCPClient
from skye.tools.mcp_resource import Resource, ResourceProviderInterface
from skye.tools.registry import CapabilityRegistry
from skye.tools.remote_api import RemoteAPICapability
from skye.base.lazy_import import lazy_names
from skye.tools.toolkit import Toolkit

# The offline checks are read at first use, so importing ``skye.tools`` does not import them.
_LAZY = {"check_mcp_client": "conformance", "check_toolkit": "conformance"}
__getattr__ = lazy_names(__name__, _LAZY)

__all__ = [
    *_LAZY,
    "CapabilityInterface",
    "CapabilitySchema",
    "LocalFunctionCapability",
    "RemoteAPICapability",
    "MCPClientInterface",
    "SkyeMCPClient",
    "MCPToolCapability",
    "MCPPrompt",
    "MCPPromptArgument",
    "Resource",
    "ResourceProviderInterface",
    "create_mcp_client",
    "capability",
    "CapabilityRegistry",
    "Toolkit",
    "CapabilityCallHandler",
    "CapabilityCall",
    "CapabilityResult",
    "CapabilityError",
    "CapabilityExecutionError",
    "CapabilityNotFoundError",
    "CapabilityValidationError",
    "CapabilityCallParsingError",
]
