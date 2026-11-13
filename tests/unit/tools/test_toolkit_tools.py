"""``tools=[...]`` of a toolkit, the toolkit with no class and the function that returns a registry
(task 18.3)."""

from __future__ import annotations

import asyncio

import pytest

from skye.base.completion import CapabilityCall
from skye.base.exceptions import ConfigurationError
from skye.base.interfaces.tool_provider import ToolProvider
from skye.base.messages import CapabilityStatus
from skye.base.plugins import Plugins, Registrar
from skye.tools import CapabilityRegistry, Toolkit, capability
from skye.tools.toolkit import ToolSet, build_toolkit


@capability
def slugify(title: str) -> str:
    """Make the part of an address that comes from a title."""
    return "-".join(title.lower().split())


@capability
def word_count(text: str) -> int:
    """Count the words of a text."""
    return len(text.split())


@capability(name="count_words")
def other_count(text: str) -> int:
    """Count the words of a text, under another name."""
    return len(text.split())


@pytest.fixture
def private() -> Registrar:
    return Registrar()


@pytest.fixture
def plugins(private: Registrar) -> Plugins:
    return Plugins(registrar=private)


def names(toolkit: Toolkit) -> list[str]:
    return [schema.name for schema in asyncio.run(toolkit.list_schemas())]


def run(toolkit: Toolkit, name: str, **arguments: object):
    return asyncio.run(toolkit.run(CapabilityCall(id="1", name=name, arguments=arguments)))


# -- the toolkit with no class
# -----------------------------------------------------------------------------


def test_a_toolkit_with_no_class_is_the_list_of_its_tools(plugins: Plugins, private: Registrar):
    plugins.toolkit("text", tools=[slugify, word_count])
    toolkit = build_toolkit("text", private)
    assert isinstance(toolkit, ToolSet)
    assert isinstance(toolkit, ToolProvider)
    assert names(toolkit) == ["text.slugify", "text.word_count"]
    assert run(toolkit, "text.slugify", title="Hello World").content == "hello-world"
    assert run(toolkit, "text.word_count", text="a b c").content == "3"


def test_the_class_of_a_toolkit_with_no_class_is_found_by_get(plugins: Plugins, private: Registrar):
    plugins.toolkit("text", tools=[slugify])
    assert private.get("toolkit", "text") is ToolSet


def test_the_tools_stay_the_functions_they_were(plugins: Plugins):
    plugins.toolkit("text", tools=[slugify])
    assert (
        slugify.get_schema().name == "slugify"
    )  # the toolkit prefixes a copy of the schema, not the capability


# -- the decorator form on a class
# --------------------------------------------------------------------------


def make_jira(plugins: Plugins):
    @plugins.toolkit("jira", tools=[slugify])
    class JiraToolkit(Toolkit):
        def __init__(self, *, base_url: str = "https://acme.example") -> None:
            self.base_url = base_url

        @capability
        def create_issue(self, title: str) -> str:
            """Create an issue and return its key."""
            return f"PROJ-1 at {self.base_url}: {title}"

    return JiraToolkit


def test_the_methods_and_the_listed_functions_are_all_tools_with_the_prefix(
    plugins: Plugins, private: Registrar
):
    make_jira(plugins)
    toolkit = build_toolkit("jira", private, base_url="https://x.example")
    assert names(toolkit) == ["jira.create_issue", "jira.slugify"]
    assert run(toolkit, "jira.create_issue", title="T").content == "PROJ-1 at https://x.example: T"
    assert run(toolkit, "jira.slugify", title="A B").content == "a-b"


def test_the_toolkit_name_is_the_registered_name(plugins: Plugins, private: Registrar):
    cls = make_jira(plugins)
    toolkit = build_toolkit("jira", private)
    assert isinstance(toolkit, cls)
    assert toolkit.toolkit_name == "jira"


def test_an_alias_takes_the_place_of_the_name_in_the_prefix(plugins: Plugins, private: Registrar):
    make_jira(plugins)
    toolkit = build_toolkit("jira", private)
    toolkit.alias = "jira-eu"
    assert names(toolkit) == ["jira-eu.create_issue", "jira-eu.slugify"]
    assert run(toolkit, "jira-eu.slugify", title="A B").content == "a-b"
    assert run(toolkit, "jira.slugify", title="A B").status == CapabilityStatus.ERROR


def test_two_builds_of_one_toolkit_do_not_share_the_tools(plugins: Plugins, private: Registrar):
    make_jira(plugins)
    first = build_toolkit("jira", private, base_url="https://one.example")
    second = build_toolkit("jira", private, base_url="https://two.example")
    assert "one.example" in run(first, "jira.create_issue", title="T").content
    assert "two.example" in run(second, "jira.create_issue", title="T").content


def test_a_toolkit_made_by_hand_does_not_have_the_registered_tools(plugins: Plugins):
    cls = make_jira(plugins)
    assert names(cls()) == [
        "jira.create_issue"
    ]  # only build_toolkit adds the tools= of the registration


def test_a_call_with_a_class_and_tools_does_the_same(plugins: Plugins, private: Registrar):
    class NotesToolkit(Toolkit):
        @capability
        def note(self, text: str) -> str:
            """Keep a note."""
            return text

    plugins.toolkit("notes", NotesToolkit, tools=[slugify])
    assert names(build_toolkit("notes", private)) == ["notes.note", "notes.slugify"]


# -- the clash of two names
# ---------------------------------------------------------------------------------


def test_a_method_and_a_listed_function_with_one_name_raise_and_name_both(
    plugins: Plugins, private: Registrar
):
    class ClashToolkit(Toolkit):
        @capability(name="slugify")
        def make_slug(self, title: str) -> str:
            """The same name as the listed function."""
            return title

    plugins.toolkit("clash", ClashToolkit, tools=[slugify])
    with pytest.raises(ConfigurationError) as caught:
        build_toolkit("clash", private)
    text = str(caught.value)
    assert "make_slug" in text and "slugify" in text


def test_two_listed_functions_with_one_name_raise_and_name_both(
    plugins: Plugins, private: Registrar
):
    @capability(name="slugify")
    def second(title: str) -> str:
        """Another function with the name of the first."""
        return title

    plugins.toolkit("text", tools=[slugify, second])
    with pytest.raises(ConfigurationError) as caught:
        build_toolkit("text", private)
    assert "slugify" in str(caught.value) and "second" in str(caught.value)


def test_a_listed_function_and_a_tool_of_the_registry_with_one_name_raise_and_name_both(
    plugins: Plugins, private: Registrar
):
    @plugins.toolkit("jira", tools=[slugify])
    def jira() -> CapabilityRegistry:
        registry = CapabilityRegistry()
        registry.add(slugify)
        return registry

    with pytest.raises(ConfigurationError) as caught:
        build_toolkit("jira", private)
    text = str(caught.value)
    assert "registry" in text and "slugify" in text


# -- the function that returns a registry
# -------------------------------------------------------------------


def make_registry_function(plugins: Plugins):
    @plugins.toolkit("jira")
    def jira(*, base_url: str = "https://acme.example") -> CapabilityRegistry:
        registry = CapabilityRegistry()

        @capability
        def create_issue(title: str) -> str:
            """Create an issue and return its key."""
            return f"PROJ-1 at {base_url}: {title}"

        registry.add(create_issue)
        return registry

    return jira


def test_a_function_that_returns_a_registry_is_a_toolkit_with_the_prefix(
    plugins: Plugins, private: Registrar
):
    make_registry_function(plugins)
    toolkit = build_toolkit("jira", private, base_url="https://x.example")
    assert isinstance(toolkit, ToolProvider)
    assert names(toolkit) == ["jira.create_issue"]
    message = run(toolkit, "jira.create_issue", title="T")
    assert message.content == "PROJ-1 at https://x.example: T"
    assert message.capability_name == "jira.create_issue"  # the answer carries the prefixed name


def test_a_registry_toolkit_takes_an_alias_and_the_listed_functions(
    plugins: Plugins, private: Registrar
):
    make_registry_function(plugins)
    plugins.toolkit("jira", lambda: CapabilityRegistry(), tools=[slugify], replace=True)
    toolkit = build_toolkit("jira", private)
    toolkit.alias = "jira-eu"
    assert names(toolkit) == ["jira-eu.slugify"]


def test_a_registry_toolkit_runs_the_tools_of_the_registry_and_the_listed_ones(
    plugins: Plugins, private: Registrar
):
    @plugins.toolkit("both", tools=[word_count])
    def both() -> CapabilityRegistry:
        registry = CapabilityRegistry()
        registry.add(slugify)
        return registry

    toolkit = build_toolkit("both", private)
    assert names(toolkit) == ["both.slugify", "both.word_count"]
    assert run(toolkit, "both.slugify", title="A B").content == "a-b"
    assert run(toolkit, "both.word_count", text="a b").content == "2"
    assert run(toolkit, "both.nope").status == CapabilityStatus.ERROR


def test_close_goes_to_the_registry(plugins: Plugins, private: Registrar):
    make_registry_function(plugins)
    asyncio.run(build_toolkit("jira", private).close())


def test_a_function_that_builds_something_else_is_refused(plugins: Plugins, private: Registrar):
    plugins.toolkit("odd", lambda: 42)
    with pytest.raises(ConfigurationError, match="neither a Toolkit nor a ToolProvider"):
        build_toolkit("odd", private)


def test_an_object_that_is_not_callable_takes_no_options(plugins: Plugins, private: Registrar):
    plugins.toolkit("fixed", ToolSet())
    assert build_toolkit("fixed", private).toolkit_name == "fixed"
    with pytest.raises(ConfigurationError, match="takes no options"):
        build_toolkit("fixed", private, x=1)


def test_an_unknown_toolkit_lists_the_registered_names(plugins: Plugins, private: Registrar):
    plugins.toolkit("text", tools=[slugify])
    with pytest.raises(ConfigurationError) as caught:
        build_toolkit("nope", private)
    assert "text" in str(caught.value)


def test_the_default_registrar_is_the_one_that_is_read_when_none_is_given():
    from tests.unit.plugins.registrar_state import restored_default_registrar

    with restored_default_registrar():
        plugins = Plugins()
        plugins.toolkit("on_default", tools=[slugify])
        assert names(build_toolkit("on_default")) == ["on_default.slugify"]
