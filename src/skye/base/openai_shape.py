# Requirement 22
"""Accept messages and tool definitions in the OpenAI data shape and return Skye types.

SDK compatibility is at the level of data, not classes: plain dicts in the OpenAI
chat format come in, ``SkyeMessage`` subclasses and ``CapabilitySchema`` come out. No vendor
SDK class is mirrored, subclassed or re-exported here. Input that does not conform is rejected
with a ``ValidationError`` naming the invalid field; the input is never modified.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from skye.base.capability_schema import CapabilitySchema
from skye.base.exceptions import ValidationError
from skye.base.messages import (
    AssistantMessage,
    CapabilityMessage,
    SkyeMessage,
    SystemMessage,
    UserMessage,
)

_TEXT_ROLES = {"system": SystemMessage, "user": UserMessage}


def _invalid(path: str, expected: str, value: Any) -> ValidationError:
    return ValidationError(
        f"Invalid OpenAI-shaped input at '{path}': expected {expected}", field=path, value=value
    )


def _text(content: Any, path: str, *, allow_none: bool = False) -> str:
    if content is None and allow_none:
        return ""
    if isinstance(content, str):
        return content
    raise _invalid(path, "a string", content)


def _tool_calls(raw: Any, path: str) -> list[dict[str, Any]]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise _invalid(path, "a list of tool calls", raw)
    calls: list[dict[str, Any]] = []
    for i, call in enumerate(raw):
        here = f"{path}[{i}]"
        if not isinstance(call, Mapping):
            raise _invalid(here, "an object", call)
        fn = call.get("function")
        if not isinstance(fn, Mapping):
            raise _invalid(f"{here}.function", "an object", fn)
        name = fn.get("name")
        if not isinstance(name, str) or not name:
            raise _invalid(f"{here}.function.name", "a non-empty string", name)
        args = fn.get("arguments", "{}")
        if isinstance(args, str):
            try:
                args = json.loads(args or "{}")
            except ValueError as e:
                raise _invalid(f"{here}.function.arguments", "a JSON object string", args) from e
        if not isinstance(args, Mapping):
            raise _invalid(f"{here}.function.arguments", "a JSON object", args)
        calls.append({"id": call.get("id"), "name": name, "args": dict(args)})
    return calls


def messages_from_openai(messages: Sequence[Mapping[str, Any]]) -> list[SkyeMessage]:
    """Convert OpenAI chat messages (system/user/assistant/tool) to Skye messages."""
    if not isinstance(messages, Sequence) or isinstance(messages, (str, bytes)):
        raise _invalid("messages", "a list of message objects", messages)
    out: list[SkyeMessage] = []
    call_names: dict[str, str] = {}
    for i, msg in enumerate(messages):
        here = f"messages[{i}]"
        if not isinstance(msg, Mapping):
            raise _invalid(here, "an object", msg)
        role = msg.get("role")
        if role in _TEXT_ROLES:
            out.append(_TEXT_ROLES[role](content=_text(msg.get("content"), f"{here}.content")))
        elif role == "assistant":
            calls = _tool_calls(msg["tool_calls"], f"{here}.tool_calls") if msg.get("tool_calls") else []
            call_names.update({c["id"]: c["name"] for c in calls if isinstance(c["id"], str)})
            content = _text(msg.get("content"), f"{here}.content", allow_none=bool(calls))
            out.append(AssistantMessage(content=content, capability_calls=calls))
        elif role == "tool":
            call_id = msg.get("tool_call_id")
            if not isinstance(call_id, str) or not call_id:
                raise _invalid(f"{here}.tool_call_id", "a non-empty string", call_id)
            name = msg.get("name") or call_names.get(call_id)
            if not isinstance(name, str) or not name:
                raise _invalid(f"{here}.name", "a tool name (or a matching assistant tool_call id)", name)
            out.append(
                CapabilityMessage(
                    content=_text(msg.get("content"), f"{here}.content"),
                    capability_id=call_id,
                    capability_name=name,
                )
            )
        else:
            raise _invalid(f"{here}.role", "one of system, user, assistant, tool", role)
    return out


def capability_from_openai_tool(tool: Mapping[str, Any]) -> CapabilitySchema:
    """Convert one OpenAI tool definition (``{"type": "function", "function": {...}}``)."""
    if not isinstance(tool, Mapping):
        raise _invalid("tool", "an object", tool)
    if tool.get("type", "function") != "function":
        raise _invalid("tool.type", "'function'", tool.get("type"))
    fn = tool.get("function")
    if not isinstance(fn, Mapping):
        raise _invalid("tool.function", "an object", fn)
    name, description = fn.get("name"), fn.get("description", "")
    if not isinstance(name, str) or not name.strip():
        raise _invalid("tool.function.name", "a non-empty string", name)
    if not isinstance(description, str):
        raise _invalid("tool.function.description", "a string", description)
    params = fn.get("parameters", {})
    if not isinstance(params, Mapping):
        raise _invalid("tool.function.parameters", "a JSON Schema object", params)
    return CapabilitySchema(name=name, description=description or name, parameters=dict(params))


def capabilities_from_openai_tools(tools: Sequence[Mapping[str, Any]]) -> list[CapabilitySchema]:
    """Convert a list of OpenAI tool definitions."""
    if not isinstance(tools, Sequence) or isinstance(tools, (str, bytes)):
        raise _invalid("tools", "a list of tool objects", tools)
    return [capability_from_openai_tool(t) for t in tools]


__all__ = ["capabilities_from_openai_tools", "capability_from_openai_tool", "messages_from_openai"]
