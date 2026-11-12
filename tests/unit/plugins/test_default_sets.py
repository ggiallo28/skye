"""The registries held per instance are views of the registrar (plugins:7.3, Requirements 56.7 and 56.8).

The registrar holds the default set of prompt filters that every new prompt builder starts with; a registration made on an instance stays
local to it. A ``CapabilityRegistry`` has no default set and starts empty (Requirement 62.1). The agent types and the tokenizers are views of the registrar tables. Every test works on a private registrar, so the default one is left alone.
"""

from __future__ import annotations

import asyncio

import pytest

from skye.agents import registry as agents_registry
from skye.base.exceptions import ConfigurationError
from skye.base.interfaces.plugin import RegistrarInterface
from skye.base.plugins import KINDS, Registrar
from skye.prompts import BasePromptBuilder
from skye.tools import CapabilityRegistry, capability
from skye.models.token_counter import TokenCounter


@pytest.fixture
def registrar(monkeypatch):
    """A private registrar that the three registries read instead of the default one."""
    private = Registrar(builtin_plugins=("skye.agents.plugins:register",))
    import skye.base.plugins as plugins_module

    monkeypatch.setattr(plugins_module, "_default", private)
    monkeypatch.setattr(agents_registry, "_registrar", lambda: private)
    return private


@capability
def word_count(text: str) -> int:
    """Count the words of a text."""
    return len(text.split())


@capability
def char_count(text: str) -> int:
    """Count the characters of a text."""
    return len(text)


# -- CapabilityRegistry: no default set (Requirements 62.1 and 56.8) ----------------------------------------------


def test_the_registrar_has_no_capability_kind_and_no_capability_method(registrar):
    assert "capability" not in KINDS
    assert not hasattr(registrar, "capability")
    assert not hasattr(RegistrarInterface, "capability")


def test_a_default_set_of_capabilities_is_an_unknown_kind(registrar):
    with pytest.raises(ConfigurationError, match="unknown kind 'capability'"):
        registrar.default_set("capability")
    with pytest.raises(ConfigurationError, match="unknown kind 'capability'"):
        registrar.names("capability")


def test_a_new_registry_starts_empty_whatever_the_plugins_did(registrar):
    # A plugin cannot add a capability to every registry: the method is gone, and the registry never reads the registrar.
    with pytest.raises(AttributeError):
        registrar.capability("word_count", word_count)  # type: ignore[attr-defined]
    assert CapabilityRegistry().list_all() == []
    CapabilityRegistry.reset_instance()
    try:
        assert CapabilityRegistry.get_instance().list_all() == []
    finally:
        CapabilityRegistry.reset_instance()


def test_a_registry_is_not_a_view_of_the_registrar(registrar):
    import skye.tools.registry as tools_registry

    assert not hasattr(tools_registry, "get_registrar")
    assert not hasattr(CapabilityRegistry, "KIND")


def test_a_local_registration_stays_local(registrar):
    mine = CapabilityRegistry(capabilities=[word_count])
    mine.register(char_count)
    other = CapabilityRegistry()
    assert sorted(mine.list_all()) == ["char_count", "word_count"]
    assert other.list_all() == []  # the other registry never saw it


def test_unregister_and_clear_touch_only_that_registry(registrar):
    registry = CapabilityRegistry(capabilities=[word_count])
    other = CapabilityRegistry(capabilities=[word_count])
    registry.unregister("word_count")
    assert not registry.exists("word_count") and other.exists("word_count")
    registry.clear()
    assert other.list_all() == ["word_count"]


def test_the_singleton_still_works_and_starts_empty(registrar):
    CapabilityRegistry.reset_instance()
    try:
        assert CapabilityRegistry.get_instance().list_all() == []
        assert CapabilityRegistry.get_instance() is CapabilityRegistry.get_instance()
    finally:
        CapabilityRegistry.reset_instance()


def test_every_old_public_call_of_the_capability_registry_still_works(registrar):
    registry = CapabilityRegistry(capabilities=[word_count])
    registry.register(char_count)
    assert registry.count() == 2 and registry.exists("char_count")
    assert registry.search("count words")[0][0] == "word_count"
    assert registry.get("nope") is None
    registry.unregister("char_count")
    assert registry.list_all() == ["word_count"]


def test_namespaces_still_work(registrar):
    @capability(name="text.words")
    def words(text: str) -> int:
        """Count the words of a text."""
        return len(text.split())

    registry = CapabilityRegistry(capabilities=[words, char_count])
    assert [c.get_schema().name for c in registry.get_by_namespace("text")] == ["text.words"]


# -- prompt filters ----------------------------------------------------------------------------------------------


def test_a_filter_of_the_default_set_works_in_every_new_builder(registrar):
    registrar.template_filter("shout", lambda value: str(value).upper() + "!")
    builder = BasePromptBuilder()
    builder.register_template("greeting", "Hello {{ name | shout }}", from_string=True)
    assert builder.render("greeting", {"name": "Ada"})[-1].content == "Hello ADA!"
    second = BasePromptBuilder()
    second.register_template("greeting", "Hello {{ name | shout }}", from_string=True)
    assert second.render("greeting", {"name": "Bob"})[-1].content == "Hello BOB!"


def test_a_filter_registered_on_a_builder_stays_local(registrar):
    mine = BasePromptBuilder()
    mine.register_filter("twice", lambda value: f"{value}{value}")
    mine.register_template("t", "{{ x | twice }}", from_string=True)
    assert mine.render("t", {"x": "ab"})[-1].content == "abab"
    assert registrar.names("template_filter") == []  # the registrar did not change
    other = BasePromptBuilder()
    other.register_template("t", "{{ x | twice }}", from_string=True)
    with pytest.raises(Exception, match="Unknown filter"):
        other.render("t", {"x": "ab"})


def test_a_local_filter_wins_over_a_default_of_the_same_name(registrar):
    registrar.template_filter("shout", lambda value: "default")
    builder = BasePromptBuilder()
    builder.register_filter("shout", lambda value: "local")
    builder.register_template("t", "{{ x | shout }}", from_string=True)
    assert builder.render("t", {"x": "a"})[-1].content == "local"


def test_a_partial_builder_keeps_the_filters_and_does_not_share_the_dict(registrar):
    registrar.template_filter("shout", lambda value: str(value).upper())
    builder = BasePromptBuilder()
    part = builder.partial(x="a")
    part.register_filter("only_part", lambda value: value)
    assert "only_part" not in builder._custom_filters and "shout" in part._custom_filters


# -- agent types -------------------------------------------------------------------------------------------------


class _Echo:
    async def invoke(self, input):
        return input


def test_an_agent_type_registered_with_the_registrar_is_created_by_name(registrar):
    registrar.agent("echo", _Echo)
    assert "echo" in agents_registry.list_agent_types()
    agent = agents_registry.create_agent("echo")
    assert asyncio.run(agent.invoke("hi")) == "hi"


def test_an_agent_type_registered_by_the_old_function_is_in_the_registrar(registrar):
    agents_registry.register_agent_type("echo", _Echo)
    assert registrar.get("agent", "echo") is _Echo


def test_react_comes_from_the_built_in_plugin_and_is_not_imported_until_used(registrar):
    assert registrar.has("agent", "react")
    assert registrar._tables["agent"]["react"].target == "skye.agents.plugins.react:ReActAgent"


def test_the_old_errors_keep_their_text_and_details(registrar):
    agents_registry.register_agent_type("dup", _Echo)
    with pytest.raises(ConfigurationError, match="Agent type already registered: 'dup'"):
        agents_registry.register_agent_type("dup", _Echo)
    with pytest.raises(ConfigurationError, match="Unknown agent type: 'nope'") as caught:
        agents_registry.get_agent_type("nope")
    assert "react" in caught.value.details["available"]
    with pytest.raises(ConfigurationError, match="non-empty string"):
        agents_registry.register_agent_type("", _Echo)


# -- tokenizers (a view since plugins:6.2) -----------------------------------------------------------------------


def test_register_tokenizer_is_outside_the_registrar(monkeypatch):
    import skye.models.token_counter as token_counter

    private = Registrar()
    monkeypatch.setattr(token_counter, "get_registrar", lambda: private)

    class Words:
        def encode(self, text):
            return text.split()

    before = private.names("tokenizer")
    TokenCounter.register_tokenizer("my-model", Words())
    try:
        assert private.names("tokenizer") == before  # the call keeps its own table
        assert not private.has("tokenizer", "my-model")
        assert TokenCounter.count_tokens("one two three", "my-model-v2") == 3
    finally:
        assert TokenCounter.unregister_tokenizer("my-model") is True


# -- Registrar.default_set ---------------------------------------------------------------------------------------

_SCANS: list[int] = []


def _counting_discover(registrar):
    _SCANS.append(1)


def _registering_discover(registrar):
    _SCANS.append(1)
    registrar.template_filter("from_scan", str.title)


def test_default_set_scans_once_and_loads_no_built_in(monkeypatch):
    import skye.base.plugins as plugins_module

    monkeypatch.setattr(
        plugins_module, "DISCOVER", "tests.unit.plugins.test_default_sets:_counting_discover"
    )
    _SCANS.clear()
    private = Registrar(scan=True, builtin_plugins=("skye.models.plugins:register",))
    assert private.default_set("template_filter") == {}
    assert _SCANS == [1]  # one scan, whatever the number of reads
    assert private._builtins_loaded is False  # reading a default set loads no built-in plugin


def test_what_the_scan_registers_is_in_the_default_set(monkeypatch):
    import skye.base.plugins as plugins_module

    monkeypatch.setattr(
        plugins_module, "DISCOVER", "tests.unit.plugins.test_default_sets:_registering_discover"
    )
    _SCANS.clear()
    private = Registrar(scan=True)
    assert list(private.default_set("template_filter")) == ["from_scan"]
    assert _SCANS == [1]


def test_default_set_of_a_private_registrar_is_what_was_registered():
    private = Registrar()
    assert private.default_set("template_filter") == {}
    private.template_filter("shout", str.upper)
    assert private.default_set("template_filter") == {"shout": str.upper}


def test_default_set_skips_a_target_that_does_not_import(caplog):
    private = Registrar()
    private.template_filter("broken", "no_such_module_for_default_set:thing")
    private.template_filter("ok", str.upper)
    with caplog.at_level("WARNING"):
        assert private.default_set("template_filter") == {"ok": str.upper}
    assert any("broken" in r.getMessage() for r in caplog.records)
