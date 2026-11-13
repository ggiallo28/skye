"""One rule for the name of every capability that can reach a model provider."""

from __future__ import annotations

import asyncio

import pytest

from skye.base.exceptions import ValidationError
from skye.base.interfaces.capability import CapabilitySchema, check_wire_name, wire_name
from skye.tools import MCPToolCapability, capability
from skye.tools import mcp_boundary as boundary
from skye.tools.exceptions import CapabilityValidationError
from skye.tools.local_function import LocalFunctionCapability
from skye.tools.remote_api import RemoteAPICapability


@pytest.mark.parametrize(
    "name", ["math_add", "math-add", "A1", "x", "a" * 64, "jira-eu_create_issue"]
)
def test_a_valid_name_is_accepted(name):
    assert CapabilitySchema(name=name, description="d").name == name
    assert check_wire_name(name) == name


@pytest.mark.parametrize(
    ("name", "suggestion"),
    [
        ("math.add", "math_add"),
        ("math add", "math_add"),
        ("math/add", "math_add"),
        ("café", "caf_"),
        ("a" * 65, "a" * 64),
    ],
)
def test_an_invalid_name_is_refused_and_a_name_is_suggested(name, suggestion):
    with pytest.raises(ValidationError) as caught:
        CapabilitySchema(name=name, description="d")
    message = str(caught.value)
    assert "letters, digits, '_' and '-'" in message and "64" in message
    assert f"'{suggestion}'" in message


def test_the_suggestion_is_a_valid_name():
    assert wire_name("weather.current") == "weather_current"
    assert wire_name("  a b.c  ") == "a_b_c"
    assert wire_name("x" * 100) == "x" * 64
    for raw in ("weather.current", "a b", "ü"):
        check_wire_name(wire_name(raw))


def test_a_local_function_with_a_bad_name_is_refused_when_it_is_decorated():
    with pytest.raises(CapabilityValidationError) as caught:

        @capability(name="math.add", description="Add")
        def add(a: int, b: int) -> int:
            return a + b

    assert "math_add" in str(caught.value) and "math.add" in str(caught.value)


def test_a_lambda_needs_a_name():
    with pytest.raises(CapabilityValidationError) as caught:
        LocalFunctionCapability(lambda text: text)
    assert "name=" in str(caught.value)
    assert LocalFunctionCapability(lambda text: text, name="echo").get_schema().name == "echo"


def test_a_remote_api_capability_with_a_bad_name_is_refused():
    with pytest.raises(ValidationError):
        RemoteAPICapability("github.search", "Search", "https://api.example.com/search")
    assert RemoteAPICapability("github_search", "Search", "https://api.example.com/search")


def test_the_registry_groups_by_an_underscore():
    from skye.tools import CapabilityRegistry

    registry = CapabilityRegistry()
    for name in ("weather_current", "weather_forecast", "weather-station_read", "database_query"):
        registry.register(LocalFunctionCapability(lambda: None, name=name, description="d"))
    names = sorted(c.get_schema().name for c in registry.get_by_namespace("weather"))
    assert names == ["weather_current", "weather_forecast"]


class _FakeClient:
    def __init__(self):
        self.calls = []

    async def call_tool(self, name, arguments=None):
        self.calls.append((name, arguments))
        return {"content": [{"type": "text", "text": "ok"}], "isError": False}


def test_an_mcp_tool_with_a_bad_name_gets_a_valid_name_and_keeps_its_own_for_the_call():
    raw = {
        "name": "github.create issue",
        "description": "Create",
        "inputSchema": {"type": "object"},
    }
    schema = boundary.to_tool_schema(raw)
    assert schema.name == "github_create_issue"
    assert boundary.tool_name(raw) == "github.create issue"
    client = _FakeClient()
    cap = MCPToolCapability(schema, client, boundary.tool_name(raw))
    asyncio.run(cap.aexecute(title="x"))
    assert client.calls == [("github.create issue", {"title": "x"})]


def test_an_mcp_tool_with_a_valid_name_is_unchanged():
    raw = {"name": "search_web", "description": "Search", "inputSchema": {"type": "object"}}
    assert boundary.to_tool_schema(raw).name == "search_web"
    assert boundary.tool_name(raw) == "search_web"
