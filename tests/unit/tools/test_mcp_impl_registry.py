"""MCP client implementations are chosen by name through the registrar (plugins:9.2 and 7.7,
Requirements 58.2 and 10.7)."""

from __future__ import annotations

import subprocess
import sys

import pytest

from skye.base.exceptions import ConfigurationError
from skye.base.plugins import Registrar, get_registrar
from skye.tools import create_mcp_client
from skye.tools import engines as tools_engines
from skye.tools.engines.skyemcp import SkyeMCPClient
from skye.tools.mcp_client import MCPClientInterface


def test_the_built_in_plugin_registers_both_names_by_text():
    registrar = Registrar()
    tools_engines.register(registrar)
    assert registrar.names("mcp_client") == ["fastmcp", "skyemcp"]
    assert registrar.get("mcp_client", "skyemcp") is SkyeMCPClient


def test_registering_imports_neither_the_fastmcp_adapter_nor_fastmcp():
    code = (
        "import sys\n"
        "from skye.base.plugins import Registrar\n"
        "from skye.tools import engines as _plugin\n"
        "r = Registrar(); _plugin.register(r)\n"
        "assert 'skye.tools.engines.fastmcp.client' not in sys.modules "
        "and 'fastmcp' not in sys.modules\n"
        "r.get('mcp_client', 'skyemcp')\n"
        "assert 'skye.tools.engines.fastmcp.client' not in sys.modules "
        "and 'fastmcp' not in sys.modules\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_the_default_registrar_knows_the_built_in_names():
    assert {"skyemcp", "fastmcp"} <= set(get_registrar().names("mcp_client"))


def test_an_unknown_impl_lists_the_registered_names():
    with pytest.raises(ConfigurationError) as caught:
        create_mcp_client("http://x", impl="nope")
    assert caught.value.details["kind"] == "mcp_client"
    assert "skyemcp" in caught.value.details["known"] and "fastmcp" in caught.value.details["known"]
    assert "'nope'" in str(caught.value)


class ThirdPartyClient(SkyeMCPClient):
    """A client a plugin adds: it keeps what it was built with so the test can see the factory
    contract."""

    def __init__(self, target, *, headers=None, timeout=30.0):
        super().__init__(target, headers=headers, timeout=timeout)
        self.built_with = (target, headers, timeout)


@pytest.fixture
def third_party_name():
    name = "acme-mcp"
    yield name
    get_registrar().unregister("mcp_client", name)  # leave the default registrar as it was


def test_a_third_party_client_is_chosen_by_name(third_party_name):
    get_registrar().mcp_client(third_party_name, ThirdPartyClient)
    client = create_mcp_client("http://x", impl=third_party_name, headers={"A": "b"}, timeout=5.0)
    assert isinstance(client, ThirdPartyClient) and isinstance(client, MCPClientInterface)
    assert client.built_with == ("http://x", {"A": "b"}, 5.0)


def test_a_third_party_client_given_as_a_function_and_as_text(third_party_name):
    get_registrar().mcp_client(third_party_name, "skye.tools.engines.skyemcp:SkyeMCPClient")
    assert isinstance(create_mcp_client("http://x", impl=third_party_name), SkyeMCPClient)


def test_a_third_party_name_does_not_replace_a_built_in_without_replace():
    with pytest.raises(ConfigurationError):
        get_registrar().mcp_client("skyemcp", ThirdPartyClient)
    assert get_registrar().get("mcp_client", "skyemcp") is SkyeMCPClient
