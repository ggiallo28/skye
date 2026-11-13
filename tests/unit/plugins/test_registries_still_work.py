"""Every call to a registry of today works as before (task 7.4, Requirement 56.7).

One compact case for each registry: it registers through the old call, finds what it registered
through the new word (``plugins.names`` or
``plugins.get``) where the registry is a view of the registrar, builds it through the old call, and
removes it. The registries are tested one
by one in more depth elsewhere (``test_provider_registry_view.py``, ``test_store_view.py``,
``test_default_sets.py``, ``tests/unit/auth/test_registry.py``,
``tests/unit/agents/test_registry.py``, ``tests/unit/tools/test_mcp_impl_registry.py``); this file
is the one place that runs them all next to each
other against the default registrar, which it puts back after each test.

``create_embedding_provider`` is not a function of the library (the embedding providers are built by
``ProviderRegistry.get_embedding_provider`` and
by ``skye.provider(..., provider_type="embedding")``), so the embedding case uses those two.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

import skye
from skye import Plugins
from skye.agents import create_agent, get_agent_type, list_agent_types, register_agent_type
from skye.auth import register_credential_source, resolve_credential_source
from skye.auth.registry import list_credential_sources, unregister_credential_source
from skye.base.exceptions import ConfigurationError, ValidationError
from skye.base.interfaces.model import ModelInterface
from skye.base.interfaces.vector_encoder import VectorEncoderInterface
from skye.base.plugins import KINDS, get_registrar
from skye.models import TokenCounter, create_decision_model
from skye.models.registry import ProviderRegistry
from skye.prompts import BasePromptBuilder
from skye.store import available_backends, backend, register_backend
from skye.tools import CapabilityRegistry, SkyeMCPClient, capability, create_mcp_client
from tests.unit.plugins.registrar_state import restored_default_registrar


class FakeModel(ModelInterface):
    def __init__(self, **config: Any) -> None:
        self.config = config

    def complete(self, request: Any) -> Any: ...
    def stream(self, request: Any) -> Any: ...
    async def acomplete(self, request: Any) -> Any: ...
    async def astream(self, request: Any) -> Any: ...
    def get_capabilities(self) -> dict[str, Any]:
        return {}

    def get_model_info(self) -> dict[str, Any]:
        return {}


class FakeEncoder(VectorEncoderInterface):
    def __init__(self, **config: Any) -> None:
        self.config = config

    def encode(self, text: str) -> list[float]:
        return [0.0]

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] for _ in texts]

    async def aencode(self, text: str) -> list[float]:
        return [0.0]

    async def aencode_batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] for _ in texts]

    def get_vector_dimension(self) -> int:
        return 1


class Echo:
    def __init__(self, *, loud: bool = False) -> None:
        self.loud = loud

    async def invoke(self, input: str) -> str:
        return input.upper() if self.loud else input


class Decider:
    def __init__(self, **config: Any) -> None:
        self.config = config

    async def decide(
        self, prompt: str, options: Any
    ) -> Any:  # the shape is enough for the registry
        return options[0]


class Words:
    def encode(self, text: str) -> list[str]:
        return text.split()


@pytest.fixture(autouse=True)
def default_registrar_put_back():
    with restored_default_registrar() as registrar:
        yield registrar


@pytest.fixture
def plugins() -> Plugins:
    return Plugins()


# -- ProviderRegistry (models)
# -----------------------------------------------------------------------------------


def test_provider_registry_model_and_embedding_calls_work_and_are_found_by_the_new_word(plugins):
    ProviderRegistry.register_model_provider("zz-model", FakeModel)
    ProviderRegistry.register_embedding_provider("zz-embed", FakeEncoder)

    assert "zz-model" in plugins.names("provider", function="model")
    assert "zz-embed" in plugins.names("provider", function="embedding")
    assert plugins.get("provider", "zz-model") is FakeModel
    assert "zz-model" in ProviderRegistry.list_model_providers()
    assert "zz-embed" in ProviderRegistry.list_embedding_providers()

    model = ProviderRegistry.get_model_provider("zz-model", flavour="plain")
    assert isinstance(model, FakeModel) and model.config == {"flavour": "plain"}
    encoder = ProviderRegistry.get_embedding_provider("zz-embed", size=2)
    assert isinstance(encoder, FakeEncoder) and encoder.config == {"size": 2}
    assert isinstance(skye.provider("zz-model"), FakeModel)  # the builder reads the same table
    assert isinstance(skye.provider("zz-embed", provider_type="embedding"), FakeEncoder)

    assert plugins.unregister("provider", "zz-model", "model")
    assert plugins.unregister("provider", "zz-embed", "embedding")
    assert "zz-model" not in ProviderRegistry.list_model_providers()
    assert "zz-embed" not in ProviderRegistry.list_embedding_providers()


def test_decision_models_are_built_by_create_decision_model_from_the_provider_kind(plugins):
    plugins.provider("zz-decider", Decider)  # the function `decide` is deduced
    assert "zz-decider" in plugins.names("provider", function="decision")
    model = create_decision_model("zz-decider", endpoint="http://x")
    assert isinstance(model, Decider) and model.config == {"endpoint": "http://x"}
    assert "jev" in plugins.names("provider", function="decision")  # the built-in one stays
    with pytest.raises(ConfigurationError) as caught:
        create_decision_model("zz-nope")
    assert "zz-decider" in str(caught.value)


# -- skye.store
# --------------------------------------------------------------------------------------------------


def test_store_register_backend_and_backend_work_and_the_name_is_found_by_the_new_word(plugins):
    register_backend("zz-store", lambda **config: ("backend", config))
    assert "zz-store" in available_backends()
    assert "zz-store" in plugins.names("backend")
    assert callable(plugins.get("backend", "zz-store"))
    assert backend("zz-store", region="x") == ("backend", {"region": "x"})
    assert skye.backend("zz-store", region="y") == ("backend", {"region": "y"})
    with pytest.raises(ConfigurationError):  # a duplicate is still refused without replace
        register_backend("zz-store", lambda **config: None)
    register_backend("zz-store", lambda **config: "replaced", replace=True)
    assert backend("zz-store") == "replaced"
    assert plugins.unregister("backend", "zz-store")
    assert "zz-store" not in available_backends()


# -- skye.auth
# --------------------------------------------------------------------------------------------------


def test_auth_register_resolve_list_and_unregister_work_and_the_name_is_found_by_the_new_word(
    plugins,
):
    register_credential_source("zz-source", lambda **config: ("source", config))
    assert "zz-source" in list_credential_sources()
    assert "zz-source" in plugins.names("credential_source")
    assert resolve_credential_source("zz-source", token="t") == ("source", {"token": "t"})
    assert skye.credential_source("zz-source", token="u") == ("source", {"token": "u"})
    with pytest.raises(ConfigurationError):
        register_credential_source("zz-source", lambda **config: None)
    unregister_credential_source("zz-source")
    assert "zz-source" not in list_credential_sources()
    assert "aws" in list_credential_sources()  # a built-in one is never lost by this


# -- skye.agents
# --------------------------------------------------------------------------------------------------


def test_agents_register_get_create_and_list_work_and_the_name_is_found_by_the_new_word(plugins):
    register_agent_type("zz-echo", Echo)
    assert "zz-echo" in list_agent_types() and list_agent_types() == sorted(list_agent_types())
    assert "zz-echo" in plugins.names("agent")
    assert get_agent_type("zz-echo") is Echo
    agent = create_agent("zz-echo", loud=True)
    assert isinstance(agent, Echo) and asyncio.run(agent.invoke("hi")) == "HI"
    assert isinstance(skye.agent("zz-echo"), Echo)
    with pytest.raises(ConfigurationError):
        register_agent_type("zz-echo", Echo)
    register_agent_type("zz-echo", Echo, replace=True)
    assert plugins.unregister("agent", "zz-echo")
    with pytest.raises(ConfigurationError):
        get_agent_type("zz-echo")
    assert "react" in list_agent_types()  # the built-in one stays


# -- skye.tools: the MCP clients
# ---------------------------------------------------------------------------------------


def test_mcp_create_mcp_client_builds_the_built_in_and_a_plugin_client_by_impl(plugins):
    assert {"skyemcp", "fastmcp"} <= set(plugins.names("mcp_client"))
    assert isinstance(create_mcp_client("http://x", impl="skyemcp"), SkyeMCPClient)
    assert isinstance(create_mcp_client("http://x"), SkyeMCPClient)  # the default impl

    class OtherClient(SkyeMCPClient):
        pass

    plugins.mcp_client("zz-mcp", OtherClient)
    assert plugins.get("mcp_client", "zz-mcp") is OtherClient
    assert isinstance(create_mcp_client("http://x", impl="zz-mcp", timeout=3.0), OtherClient)
    assert isinstance(skye.mcp_client("http://x", impl="zz-mcp"), OtherClient)
    with pytest.raises(ConfigurationError) as caught:
        create_mcp_client("http://x", impl="zz-unknown")
    assert "skyemcp" in str(caught.value)


# -- TokenCounter.register_tokenizer: outside the plugin interface, and it still works
# ----------------------------------------


def test_token_counter_register_tokenizer_and_unregister_work_outside_the_registrar(plugins):
    before = plugins.names("tokenizer")
    TokenCounter.register_tokenizer("zz-tok-model", Words())
    try:
        assert TokenCounter.count_tokens("one two three four five", "zz-tok-model") == 5
        assert (
            TokenCounter.count_tokens("one two three four five", "zz-tok-model-2026") == 5
        )  # by prefix
        assert plugins.names("tokenizer") == before  # it does not write to the registrar
    finally:
        assert TokenCounter.unregister_tokenizer("zz-tok-model") is True
    assert TokenCounter.unregister_tokenizer("zz-tok-model") is False


# -- the prompt builder: register_filter and the default set
# ---------------------------------------------------------------------


def test_prompt_builder_register_filter_stays_local_and_the_default_set_is_a_view(plugins):
    builder = BasePromptBuilder()
    builder.register_filter("zz_shout", lambda value: f"{str(value).upper()}!")
    builder.register_template("zz-t", "{{ name | zz_shout }}")
    assert builder.render("zz-t", {"name": "ada"})[0].content == "ADA!"
    other = BasePromptBuilder()
    other.register_template("zz-t", "{{ name | zz_shout }}")
    with pytest.raises(ValidationError):  # the filter of one builder is not in another
        other.render("zz-t", {"name": "ada"})

    plugins.template_filter(
        "zz_default", lambda value: f"<{value}>"
    )  # the default set every new builder starts with
    assert "zz_default" in plugins.names("template_filter")
    fresh = BasePromptBuilder()
    fresh.register_template("zz-d", "{{ name | zz_default }}")
    assert fresh.render("zz-d", {"name": "ada"})[0].content == "<ada>"


# -- CapabilityRegistry: not a view of the registrar, and it works on its own
# ----------------------------------------------------


def test_capability_registry_works_on_its_own_and_is_not_a_view_of_the_registrar(plugins):
    @capability
    def word_count(text: str) -> int:
        """Count the words of a text."""
        return len(text.split())

    @capability(name="text_chars")
    def char_count(text: str) -> int:
        """Count the characters of a text."""
        return len(text)

    registry = CapabilityRegistry()
    assert registry.list_all() == []  # it starts empty, whatever the plugins did
    registry.register(word_count)
    registry.register(char_count)
    assert registry.count() == 2 and registry.exists("word_count")
    assert registry.get("word_count") is word_count
    assert [c.get_schema().name for c in registry.get_by_namespace("text")] == ["text_chars"]
    assert registry.get("word_count").execute(text="one two") == 2
    registry.unregister("word_count")
    assert registry.list_all() == ["text_chars"]

    assert "capability" not in KINDS and not hasattr(get_registrar(), "capability")
    assert CapabilityRegistry().list_all() == []  # nothing a registry holds is in a new one
