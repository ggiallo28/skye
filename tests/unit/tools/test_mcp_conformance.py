"""Conformance of ``tools`` to D24 and D26 (tasks tools:1.3, 6.1, 6.2, 6.3).

* 1.3: the capability data types are validated dataclasses, not pydantic, and invalid data raises ``ValidationError`` with the field.
* 6.1: ``Resource`` and its Port live in ``base``; every MCP client implements the resource Port.
* 6.2: the MCP prompt facet returns ``base`` messages; ``tools`` imports no ``prompts`` module and implements no prompt Port.
* 6.3: ``fastmcp`` is imported only by ``tools/engines/fastmcp/client.py``; the legacy probes are gone.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import inspect
import pkgutil
from pathlib import Path
from typing import Any

import pytest

import skye.interfaces as interfaces
import skye.tools
from skye.base.exceptions import ValidationError
from skye.base.interfaces.resource import Resource as BaseResource
from skye.base.interfaces.resource import ResourceProviderInterface
from skye.base.messages import AssistantMessage, SkyeMessage, UserMessage
from skye.base.validated import Validated
from skye.tools import CapabilityCall, CapabilityResult, CapabilitySchema, Resource
from skye.tools.mcp_client import MCPClientInterface
from skye.tools.engines.skyemcp import SkyeMCPClient
from skye.utils.validation import port_signature_mismatches

TOOLS_DIR = Path(skye.tools.__file__).resolve().parent


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
    return names


# --- 1.3: dataclasses, not pydantic --------------------------------------------------------------------------------------


def test_no_module_of_tools_imports_pydantic():
    offenders = [
        p.name
        for p in TOOLS_DIR.rglob("*.py")
        if any(n.split(".")[0] == "pydantic" for n in _imports(p))
    ]
    assert not offenders


@pytest.mark.parametrize("cls", [CapabilitySchema, CapabilityResult, CapabilityCall])
def test_capability_types_are_validated_dataclasses(cls: type):
    assert dataclasses.is_dataclass(cls)
    assert issubclass(cls, Validated)
    assert not any(base.__module__.split(".")[0] == "pydantic" for base in cls.__mro__)


@pytest.mark.parametrize(
    "build,field",
    [
        (
            lambda: CapabilitySchema(name="x", description="d", parameters="not a dict"),
            "parameters",
        ),
        (lambda: CapabilityCall(id="1", name="x", arguments=[1]), "arguments"),
        (lambda: CapabilityResult(capability_call_id=3, name="x"), "capability_call_id"),
    ],
)
def test_invalid_data_raises_validation_error_with_field_context(build: Any, field: str):
    with pytest.raises(ValidationError) as info:
        build()
    assert info.value.details["field"] == field
    assert field in str(info.value)


# --- 6.1: the resource Port in base -------------------------------------------------------------------------------------


def test_resource_is_the_base_type_everywhere():
    from skye.tools import mcp_boundary, mcp_resource

    assert Resource is BaseResource is mcp_resource.Resource is interfaces.Resource
    assert mcp_boundary.Resource is BaseResource
    assert interfaces.ResourceProviderInterface is ResourceProviderInterface


def test_every_mcp_client_implements_the_resource_port():
    assert issubclass(MCPClientInterface, ResourceProviderInterface)
    client = SkyeMCPClient("http://localhost:1/mcp")
    assert isinstance(client, ResourceProviderInterface)
    assert port_signature_mismatches(SkyeMCPClient, ResourceProviderInterface) == []
    from skye.tools.engines.fastmcp import FastMCPClient  # importing it never imports fastmcp

    assert port_signature_mismatches(FastMCPClient, ResourceProviderInterface) == []


def test_resource_is_a_validated_frozen_dataclass():
    listed = Resource(uri="file:///a.txt", name="a", mime_type="text/plain")
    assert not listed.has_content
    assert Resource(uri="u", name="u", data=b"\x00").has_content
    with pytest.raises(dataclasses.FrozenInstanceError):
        listed.text = "x"  # type: ignore[misc]
    with pytest.raises(ValidationError) as both:
        Resource(uri="u", name="u", text="t", data=b"d")
    assert both.value.details["field"] == "data"
    with pytest.raises(ValidationError) as empty:
        Resource(uri="", name="u")
    assert empty.value.details["field"] == "uri"
    with pytest.raises(ValidationError) as wrong:
        Resource(uri="u", name="u", data="not bytes")
    assert wrong.value.details["field"] == "data"


async def test_a_plain_class_satisfies_the_resource_port():
    class Notes:
        async def list_resources(self) -> list[Resource]:
            return []

        async def read_resource(self, uri: str) -> Resource:
            return Resource(uri=uri, name=uri, text="hi")

    assert isinstance(Notes(), ResourceProviderInterface)
    assert port_signature_mismatches(Notes, ResourceProviderInterface) == []
    assert (await Notes().read_resource("n://1")).text == "hi"


# --- 6.2: the prompt facet returns base messages ------------------------------------------------------------------------


async def test_get_prompt_returns_base_messages(monkeypatch: pytest.MonkeyPatch):
    client = SkyeMCPClient("http://localhost:1/mcp")
    reply = {
        "messages": [
            {"role": "user", "content": {"type": "text", "text": "hi"}},
            {"role": "assistant", "content": {"type": "text", "text": "ok"}},
        ]
    }
    monkeypatch.setattr(client, "_rpc", lambda method, params=None: reply)
    messages = await client.get_prompt("greet", {"who": "bob"})
    assert [type(m) for m in messages] == [UserMessage, AssistantMessage]
    assert all(
        isinstance(m, SkyeMessage) and type(m).__module__ == "skye.base.messages" for m in messages
    )
    assert inspect.signature(MCPClientInterface.get_prompt).return_annotation in (
        "list[SkyeMessage]",
        list[SkyeMessage],
    )


def test_tools_imports_no_prompts_module():
    offenders = [
        f"{p.name}: {name}"
        for p in TOOLS_DIR.rglob("*.py")
        for name in _imports(p)
        if name == "skye.prompts"
        or name.startswith("skye.prompts.")
        or name == "skye.base.interfaces.prompt"
    ]
    assert not offenders


def test_no_tools_class_implements_a_prompt_port():
    prompt_ports = tuple(
        getattr(interfaces, n)
        for n in interfaces.__all__
        if n.startswith("Prompt") and n.endswith("Interface")
    )
    assert prompt_ports
    found = []
    for info in pkgutil.iter_modules([str(TOOLS_DIR)], "skye.tools."):
        try:
            module = importlib.import_module(info.name)
        except ImportError:  # pragma: no cover - every tools module imports without an extra
            continue
        for name, obj in vars(module).items():
            if (
                inspect.isclass(obj)
                and obj.__module__ == info.name
                and issubclass(obj, prompt_ports)
            ):
                found.append(f"{info.name}.{name}")
    assert not found


# --- 6.3: the legacy probes are gone ------------------------------------------------------------------------------------


def test_only_the_fastmcp_client_imports_fastmcp():
    for legacy in ("mcp_capability", "mcp_server_client"):
        assert not (TOOLS_DIR / f"{legacy}.py").exists()
        with pytest.raises(ImportError):
            importlib.import_module(f"skye.tools.{legacy}")
    importers = sorted(
        str(p.relative_to(TOOLS_DIR))
        for p in TOOLS_DIR.rglob("*.py")
        if any(n.split(".")[0] == "fastmcp" for n in _imports(p))
    )
    assert importers in ([], ["plugins/fastmcp/client.py"])
