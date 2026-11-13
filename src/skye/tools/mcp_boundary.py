# Requirement 15
"""The single conversion point from MCP protocol shapes to Skye types.

Both MCP clients (built-in JSON-RPC and fastmcp) hand their raw payload to the ``to_*``
functions here: a plain ``dict`` (JSON-RPC) or an ``mcp.types``/``fastmcp`` object. Nothing
else in ``skye`` touches those types, and no protocol type is returned. Required fields
that are absent or malformed raise :class:`~skye.base.exceptions.ValidationError` naming
the MCP type and the field; no partially populated Skye type is ever returned.

This module imports no third-party library: fastmcp objects are read through
``model_dump`` / ``dataclasses`` / attributes, so it stays inside the stdlib footprint.
"""

from __future__ import annotations

import base64
import binascii
import dataclasses
from dataclasses import dataclass, field
from typing import Any

from skye.base.exceptions import ValidationError
from skye.base.interfaces.capability import CapabilitySchema
from skye.base.interfaces.resource import Resource

# the message types live in `base`; `tools` never imports `prompts`
from skye.base.messages import (
    AssistantMessage,
    SkyeMessage,
    UserMessage,
)

_UNSET: Any = object()


@dataclass(frozen=True)
class MCPPromptArgument:
    name: str
    description: str | None = None
    required: bool = False


@dataclass(frozen=True)
class MCPPrompt:
    """Descriptor of a server-side prompt; render it with ``client.get_prompt``."""

    name: str
    description: str | None = None
    arguments: tuple[MCPPromptArgument, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class MCPToolResult:
    """Outcome of a tool call: ``value`` is structured content or the joined text."""

    value: Any
    is_error: bool = False


def _fail(type_name: str, field_name: str, problem: str, value: Any = None) -> ValidationError:
    return ValidationError(
        f"MCP {type_name}: field '{field_name}' {problem}",
        field=f"{type_name}.{field_name}",
        value=value,
    )


def _as_dict(raw: Any, type_name: str) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if hasattr(raw, "model_dump"):
        dumped: dict[str, Any] = raw.model_dump(by_alias=True, mode="json")
        return dumped
    if dataclasses.is_dataclass(raw) and not isinstance(raw, type):
        return {f.name: getattr(raw, f.name) for f in dataclasses.fields(raw)}
    raise ValidationError(
        f"MCP {type_name}: expected an object or mapping, got {type(raw).__name__}",
        field=type_name,
        value=raw,
    )


def _get(d: dict[str, Any], *names: str) -> Any:
    for n in names:
        if n in d and d[n] is not None:
            return d[n]
    return _UNSET


def _required_str(d: dict[str, Any], type_name: str, *names: str) -> str:
    v = _get(d, *names)
    if v is _UNSET:
        raise _fail(type_name, names[0], "is required but absent")
    if not isinstance(v, str) or not v.strip():
        raise _fail(type_name, names[0], "must be a non-empty string", v)
    return v


def _optional_str(d: dict[str, Any], type_name: str, *names: str) -> str | None:
    v = _get(d, *names)
    if v is _UNSET:
        return None
    if not isinstance(v, str):
        raise _fail(type_name, names[0], "must be a string", v)
    return v


def _items(d: dict[str, Any], type_name: str, *names: str, required: bool) -> list[Any]:
    v = _get(d, *names)
    if v is _UNSET:
        if required:
            raise _fail(type_name, names[0], "is required but absent")
        return []
    if not isinstance(v, (list, tuple)):
        raise _fail(type_name, names[0], "must be a list", v)
    return list(v)


# --- tools -------------------------------------------------------------------------------


def to_tool_schema(raw: Any) -> CapabilitySchema:
    """``mcp.types.Tool`` -> :class:`CapabilitySchema` (name, description, inputSchema)."""
    d = _as_dict(raw, "Tool")
    name = _required_str(d, "Tool", "name")
    schema = _get(d, "inputSchema", "input_schema")
    if schema is _UNSET:
        raise _fail("Tool", "inputSchema", "is required but absent")
    if not isinstance(schema, dict):
        raise _fail("Tool", "inputSchema", "must be an object (JSON Schema)", schema)
    description = (
        _optional_str(d, "Tool", "description") or _optional_str(d, "Tool", "title") or name
    )
    return CapabilitySchema(
        name=name,
        description=description,
        parameters=schema,
        returns={"type": "object", "description": "Tool execution result"},
    )


def to_tool_result(raw: Any) -> MCPToolResult:
    """``mcp.types.CallToolResult`` -> :class:`MCPToolResult`."""
    d = _as_dict(raw, "CallToolResult")
    content = _items(d, "CallToolResult", "content", required=True)
    is_error = _get(d, "isError", "is_error")
    if is_error is _UNSET:
        is_error = False
    if not isinstance(is_error, bool):
        raise _fail("CallToolResult", "isError", "must be a boolean", is_error)
    texts: list[str] = []
    for i, item in enumerate(content):
        c = _as_dict(item, "CallToolResult.content")
        ctype = _required_str(c, f"CallToolResult.content[{i}]", "type")
        if ctype == "text":
            texts.append(_required_str(c, f"CallToolResult.content[{i}]", "text"))
        else:
            texts.append(f"[{ctype} content]")
    structured = _get(d, "structuredContent", "structured_content")
    value = structured if structured is not _UNSET else "\n".join(texts)
    return MCPToolResult(value=value, is_error=is_error)


# --- prompts -----------------------------------------------------------------------------


def to_prompt(raw: Any) -> MCPPrompt:
    """``mcp.types.Prompt`` -> :class:`MCPPrompt`."""
    d = _as_dict(raw, "Prompt")
    args: list[MCPPromptArgument] = []
    for i, a in enumerate(_items(d, "Prompt", "arguments", required=False)):
        ad = _as_dict(a, "PromptArgument")
        req = _get(ad, "required")
        if req is not _UNSET and not isinstance(req, bool):
            raise _fail("PromptArgument", "required", "must be a boolean", req)
        args.append(
            MCPPromptArgument(
                name=_required_str(ad, "PromptArgument", "name"),
                description=_optional_str(ad, "PromptArgument", "description"),
                required=bool(req) if req is not _UNSET else False,
            )
        )
    return MCPPrompt(
        name=_required_str(d, "Prompt", "name"),
        description=_optional_str(d, "Prompt", "description"),
        arguments=tuple(args),
    )


def to_prompt_messages(raw: Any) -> list[SkyeMessage]:
    """``mcp.types.GetPromptResult`` -> the ``prompts`` message objects (user/assistant)."""
    d = _as_dict(raw, "GetPromptResult")
    out: list[SkyeMessage] = []
    for i, m in enumerate(_items(d, "GetPromptResult", "messages", required=True)):
        where = f"GetPromptResult.messages[{i}]"
        md = _as_dict(m, "PromptMessage")
        role = _required_str(md, "PromptMessage", "role")
        if role not in ("user", "assistant"):
            raise _fail("PromptMessage", "role", "must be 'user' or 'assistant'", role)
        content = _get(md, "content")
        if content is _UNSET:
            raise _fail("PromptMessage", "content", "is required but absent")
        cd = _as_dict(content, "PromptMessage.content")
        if _required_str(cd, where + ".content", "type") != "text":
            raise _fail(
                "PromptMessage",
                "content.type",
                "must be 'text' (other content is not consumed)",
                cd.get("type"),
            )
        text = _required_str(cd, "PromptMessage.content", "text")
        out.append((UserMessage if role == "user" else AssistantMessage)(content=text))
    return out


# --- resources ---------------------------------------------------------------------------


def to_resource(raw: Any) -> Resource:
    """``mcp.types.Resource`` -> :class:`Resource` (metadata only)."""
    d = _as_dict(raw, "Resource")
    return Resource(
        uri=str(_required_str(d, "Resource", "uri")),
        name=_required_str(d, "Resource", "name"),
        mime_type=_optional_str(d, "Resource", "mimeType", "mime_type"),
        description=_optional_str(d, "Resource", "description"),
    )


def to_resource_contents(raw: Any) -> Resource:
    """``Text`` / ``BlobResourceContents`` -> :class:`Resource` with content."""
    d = _as_dict(raw, "ResourceContents")
    uri = str(_required_str(d, "ResourceContents", "uri"))
    mime = _optional_str(d, "ResourceContents", "mimeType", "mime_type")
    text, blob = _get(d, "text"), _get(d, "blob")
    if text is _UNSET and blob is _UNSET:
        raise _fail("ResourceContents", "text", "or 'blob' is required but both are absent")
    if text is not _UNSET and blob is not _UNSET:
        raise _fail("ResourceContents", "text", "and 'blob' are mutually exclusive")
    if text is not _UNSET:
        if not isinstance(text, str):
            raise _fail("ResourceContents", "text", "must be a string", text)
        return Resource(uri=uri, name=uri, mime_type=mime, text=text)
    if not isinstance(blob, str):
        raise _fail("ResourceContents", "blob", "must be a base64 string", blob)
    try:
        data = base64.b64decode(blob, validate=True)
    except (binascii.Error, ValueError) as e:
        raise _fail("ResourceContents", "blob", "is not valid base64", blob) from e
    return Resource(uri=uri, name=uri, mime_type=mime, data=data)


def to_read_resource(raw: Any) -> Resource:
    """``ReadResourceResult`` (``{"contents": [...]}``) or a bare contents list -> first content."""
    contents = raw
    if not isinstance(raw, (list, tuple)):
        contents = _items(
            _as_dict(raw, "ReadResourceResult"), "ReadResourceResult", "contents", required=True
        )
    if not contents:
        raise _fail("ReadResourceResult", "contents", "is empty")
    return to_resource_contents(contents[0])
