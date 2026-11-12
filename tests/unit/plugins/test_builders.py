"""The builders as lazy names of `skye` (task 16.1, Requirements 56.11 and 62.9): the word that adds a kind is the word that builds it."""

from __future__ import annotations

import subprocess
import sys
from typing import Any

import pytest

import skye
from skye.base.exceptions import ConfigurationError
from tests.unit.plugins.registrar_state import restored_default_registrar

BUILDERS = ["agent", "backend", "mcp_client", "credential_source", "routing_strategy"]


@pytest.fixture
def plugins():
    """The default handle, with the default registrar put back as it was after the test."""
    with restored_default_registrar():
        yield skye.Plugins()


def _lists_names(error: ConfigurationError, known: str) -> bool:
    return known in str(error) or known in str(error.details)


# -- what a decorator registers is built by the builder of the same word -----------------------------------------------------------


def test_agent_builds_what_the_decorator_registered(plugins):
    @plugins.agent("test-agent")
    class TestAgent:
        def __init__(self, *, loud: bool = False) -> None:
            self.loud = loud

        async def invoke(self, input: Any) -> Any:
            return input

    agent = skye.agent("test-agent", loud=True)
    assert isinstance(agent, TestAgent)
    assert agent.loud is True


def test_backend_builds_what_the_decorator_registered(plugins):
    @plugins.backend("test-backend")
    class TestBackend:
        def __init__(self, **config: Any) -> None:
            self.config = config

    backend = skye.backend("test-backend", path="x")
    assert isinstance(backend, TestBackend)
    assert backend.config == {"path": "x"}


def test_mcp_client_builds_what_the_decorator_registered(plugins):
    @plugins.mcp_client("test-mcp")
    class TestClient:
        def __init__(
            self, target: Any, *, headers: dict[str, str] | None = None, timeout: float = 30.0
        ) -> None:
            self.target, self.headers, self.timeout = target, headers, timeout

    client = skye.mcp_client("http://x/mcp", "test-mcp", headers={"a": "b"}, timeout=5.0)
    assert isinstance(client, TestClient)
    assert (client.target, client.headers, client.timeout) == ("http://x/mcp", {"a": "b"}, 5.0)
    assert skye.mcp_client("http://x/mcp", impl="test-mcp").timeout == 30.0


def test_credential_source_builds_what_the_decorator_registered(plugins):
    @plugins.credential_source("test-source")
    class TestSource:
        def __init__(self, **config: Any) -> None:
            self.config = config

    source = skye.credential_source("test-source", token="t")
    assert isinstance(source, TestSource)
    assert source.config == {"token": "t"}


def test_routing_strategy_returns_what_the_decorator_registered(plugins):
    @plugins.routing_strategy("test-strategy")
    def shortest(models: list[str]) -> str:
        return min(models, key=len)

    assert skye.routing_strategy("test-strategy") is shortest
    assert skye.routing_strategy("test-strategy")(["abc", "d"]) == "d"


def test_routing_strategy_returns_the_class_of_a_built_in():
    from skye.router.routing_strategies import RouterStrategy

    strategy = skye.routing_strategy("round_robin")
    assert isinstance(strategy, type) and issubclass(strategy, RouterStrategy)
    assert skye.routing_strategy("lazy_complex") is not strategy


# -- the registered names are found by the builder and by `names` ------------------------------------------------------------------


@pytest.mark.parametrize("word", BUILDERS)
def test_a_registered_name_is_listed_by_names_and_found_by_the_builder(plugins, word):
    name = f"test-{word}"
    register = getattr(plugins, word)
    register(name, lambda *args, **options: ("built", args, options))
    assert name in plugins.names(word)
    assert callable(getattr(skye, word))
    if word == "routing_strategy":
        assert skye.routing_strategy(name)(["a"]) == ("built", (["a"],), {})
    elif word == "mcp_client":
        assert skye.mcp_client("http://x", name)[0] == "built"
    else:
        assert getattr(skye, word)(name)[0] == "built"


# -- an unknown name raises ConfigurationError that lists the registered names -----------------------------------------------------


@pytest.mark.parametrize(
    ("call", "known"),
    [
        (lambda: skye.agent("nope"), "react"),
        (lambda: skye.backend("nope"), "memory"),
        (lambda: skye.mcp_client("http://x", impl="nope"), "skyemcp"),
        (lambda: skye.credential_source("nope"), "aws"),
        (lambda: skye.routing_strategy("nope"), "round_robin"),
    ],
    ids=BUILDERS,
)
def test_an_unknown_name_lists_the_registered_names(call, known):
    with pytest.raises(ConfigurationError) as caught:
        call()
    assert _lists_names(caught.value, known)


# -- the old function names still work and give the same type ---------------------------------------------------------------------


def test_the_old_function_names_give_the_same_objects(plugins):
    from skye.agents import REACT, create_agent
    from skye.auth import resolve_credential_source
    from skye.store import backend as store_backend
    from skye.tools import create_mcp_client

    @plugins.agent("old-agent")
    class OldAgent:
        async def invoke(self, input: Any) -> Any:
            return input

    @plugins.credential_source("old-source")
    class OldSource:
        def __init__(self, **config: Any) -> None:
            self.config = config

    @plugins.mcp_client("old-mcp")
    class OldClient:
        def __init__(self, target: Any, *, headers: Any = None, timeout: float = 30.0) -> None:
            self.target = target

    assert type(skye.agent("old-agent")) is type(create_agent("old-agent"))
    assert type(skye.agent(REACT)) is type(create_agent(REACT))
    assert type(skye.backend("memory")) is type(store_backend("memory"))
    assert type(skye.mcp_client("http://x", "old-mcp")) is type(
        create_mcp_client("http://x", "old-mcp")
    )
    assert type(skye.credential_source("old-source")) is type(
        resolve_credential_source("old-source")
    )


def test_the_default_mcp_implementation_is_skyemcp():
    from skye.tools import SkyeMCPClient

    assert type(skye.mcp_client("http://localhost:1/mcp")) is SkyeMCPClient


# -- `import skye` stays light ------------------------------------------------------------------------------------------------------


def test_the_builders_are_in_all_and_import_skye_loads_no_component():
    for word in BUILDERS:
        assert word in skye.__all__
    code = (
        "import sys, skye\n"
        "components = ('skye.agents', 'skye.store', 'skye.tools', 'skye.auth', 'skye.router')\n"
        "print([m for m in components if m in sys.modules])\n"
        "skye.backend('memory')\n"
        "print('skye.store' in sys.modules)\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    before, after = done.stdout.splitlines()
    assert before == "[]"
    assert after == "True"
