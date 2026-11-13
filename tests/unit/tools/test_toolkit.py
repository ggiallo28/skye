"""A toolkit from end to end, as the documentation shows it (task 18.6; Requirements 62.5 and 62.6
of steering).

The toolkit is the `jira` one of ``examples/plugins/custom_toolkit.py``, written here as a fake:
methods with
``@capability``, a name of its own, ``return_direct``, a function written outside the class and
added with ``tools=[...]``.
The details of each rule are in ``test_toolkit_base.py`` (the class), ``test_toolkit_tools.py``
(``tools=`` and the registry
function) and ``test_skye_toolkit_builder.py`` (the builder); this file reads them in the order a
user meets them.
"""

from __future__ import annotations

import pytest

import skye
from skye.completion import CapabilityCall
from skye.tools import CapabilityRegistry, capability
from tests.unit.plugins.registrar_state import restored_default_registrar


@capability
def slugify(title: str) -> str:
    """Make the part of an address that comes from a title."""
    return "-".join(title.lower().split())


@pytest.fixture
def plugins():
    """The default handle; what a test registered is taken away, and the default registrar is put
    back."""
    with restored_default_registrar() as registrar:
        before = set(registrar.names("toolkit"))
        try:
            yield skye.Plugins()
        finally:
            for name in set(registrar.names("toolkit")) - before:
                registrar.unregister(
                    "toolkit", name
                )  # this drops the `tools=` of the registration too


def register_jira(plugins: skye.Plugins) -> type[skye.Toolkit]:
    @plugins.toolkit("jira", tools=[slugify])  # a tool written outside the class, added here
    class JiraToolkit(skye.Toolkit):
        def __init__(self, *, base_url: str) -> None:
            self.base_url = base_url

        @capability
        def create_issue(self, title: str) -> str:
            """Create an issue and return its key."""
            return f"PROJ-1 created at {self.base_url}: {title}"

        @capability(return_direct=True)
        def issue_url(self, key: str) -> str:
            """The address of an issue, ready to be given back as it is."""
            return f"{self.base_url}/browse/{key}"

        @capability(
            name="close_issue",
            description="Close an issue that is done or no longer needed.",
        )
        def move_to_done(self, key: str) -> str:
            return f"{key} closed"

    return JiraToolkit


async def run(toolkit: skye.Toolkit, name: str, **arguments: object) -> str:
    message = await toolkit.run(CapabilityCall(id="1", name=name, arguments=arguments))
    return str(message.content)


@pytest.mark.asyncio
async def test_a_toolkit_is_built_by_name_and_lists_its_tools_with_the_prefix(plugins):
    register_jira(plugins)
    jira = skye.toolkit("jira", base_url="https://acme.example/jira")
    names = [schema.name for schema in await jira.list_schemas()]
    assert sorted(names) == [
        "jira.close_issue",  # the name of its own, not `move_to_done`
        "jira.create_issue",
        "jira.issue_url",
        "jira.slugify",  # the function written outside the class
    ]


@pytest.mark.asyncio
async def test_each_tool_runs_by_its_prefixed_name(plugins):
    register_jira(plugins)
    jira = skye.toolkit("jira", base_url="https://acme.example/jira")
    assert await run(jira, "jira.create_issue", title="Broken login") == (
        "PROJ-1 created at https://acme.example/jira: Broken login"
    )
    assert await run(jira, "jira.close_issue", key="PROJ-1") == "PROJ-1 closed"
    assert await run(jira, "jira.slugify", title="Broken Login Page") == "broken-login-page"
    assert await run(jira, "jira.issue_url", key="PROJ-1") == (
        "https://acme.example/jira/browse/PROJ-1"
    )


@pytest.mark.asyncio
async def test_a_name_without_the_prefix_is_an_error_message_and_does_not_raise(plugins):
    register_jira(plugins)
    jira = skye.toolkit("jira", base_url="https://acme.example/jira")
    message = await jira.run(CapabilityCall(id="1", name="create_issue", arguments={"title": "x"}))
    assert message.status.value == "error"


@pytest.mark.asyncio
async def test_self_is_in_no_schema(plugins):
    register_jira(plugins)
    jira = skye.toolkit("jira", base_url="https://acme.example/jira")
    for schema in await jira.list_schemas():
        assert "self" not in schema.parameters["properties"], schema.name
        assert "self" not in schema.parameters.get("required", []), schema.name
        assert "self" not in str(schema.description), schema.name
    by_name = {schema.name: schema for schema in await jira.list_schemas()}
    assert list(by_name["jira.create_issue"].parameters["properties"]) == ["title"]
    assert list(by_name["jira.close_issue"].parameters["properties"]) == ["key"]
    assert (
        by_name["jira.close_issue"].description
        == "Close an issue that is done or no longer needed."
    )


@pytest.mark.asyncio
async def test_return_direct_is_on_the_schema_of_the_tool_that_asked_for_it(plugins):
    register_jira(plugins)
    jira = skye.toolkit("jira", base_url="https://acme.example/jira")
    flags = {schema.name: schema.return_direct for schema in await jira.list_schemas()}
    assert flags == {
        "jira.create_issue": False,
        "jira.issue_url": True,
        "jira.close_issue": False,
        "jira.slugify": False,
    }


@pytest.mark.asyncio
async def test_an_alias_is_the_prefix_when_one_toolkit_is_built_twice(plugins):
    register_jira(plugins)
    eu = skye.toolkit("jira", alias="jira-eu", base_url="https://eu.example")
    us = skye.toolkit("jira", base_url="https://us.example")
    assert "jira-eu.create_issue" in [schema.name for schema in await eu.list_schemas()]
    assert "jira.create_issue" in [schema.name for schema in await us.list_schemas()]
    assert "eu.example" in await run(
        eu, "jira-eu.create_issue", title="x"
    )  # each keeps its own state
    assert "us.example" in await run(us, "jira.create_issue", title="x")


@pytest.mark.asyncio
async def test_a_second_toolkit_is_built_by_its_own_name(plugins):
    register_jira(plugins)

    @plugins.toolkit("wiki")
    class WikiToolkit(skye.Toolkit):
        @capability
        def search(self, text: str) -> str:
            """Search the wiki."""
            return f"found {text}"

    jira = skye.toolkit("jira", base_url="https://acme.example/jira")
    wiki = skye.toolkit("wiki")
    assert await run(wiki, "wiki.search", text="plugins") == "found plugins"
    assert not any(schema.name.startswith("wiki.") for schema in await jira.list_schemas())
    assert not any(schema.name.startswith("jira.") for schema in await wiki.list_schemas())


@pytest.mark.asyncio
async def test_a_toolkit_is_replaced_and_the_builder_returns_the_new_one(plugins):
    old = register_jira(plugins)
    assert type(skye.toolkit("jira", base_url="https://acme.example")) is old

    class OtherToolkit(skye.Toolkit):
        @capability
        def ping(self) -> str:
            """Answer."""
            return "pong"

    plugins.toolkit("jira", OtherToolkit, replace=True)
    new = skye.toolkit("jira")
    assert type(new) is OtherToolkit
    names = [schema.name for schema in await new.list_schemas()]
    assert names == ["jira.ping"]  # the tools= of the old registration went with it
    assert await run(new, "jira.ping") == "pong"


@pytest.mark.asyncio
async def test_a_function_that_returns_a_registry_is_a_toolkit(plugins):
    @plugins.toolkit("notes")
    def notes(*, folder: str) -> CapabilityRegistry:
        registry = CapabilityRegistry()

        @capability
        def add_note(text: str) -> str:
            """Add a note."""
            return f"{folder}: {text}"

        registry.add(add_note)
        return registry

    built = skye.toolkit("notes", folder="work")
    assert [schema.name for schema in await built.list_schemas()] == ["notes.add_note"]
    assert await run(built, "notes.add_note", text="call back") == "work: call back"


def test_a_toolkit_with_no_class_is_the_list_of_its_functions(plugins):
    plugins.toolkit("text", tools=[slugify])
    assert skye.toolkit("text").toolkit_name == "text"


def test_a_method_and_a_listed_function_with_one_name_raise_and_name_both(plugins):
    @capability
    def create_issue(title: str) -> str:
        """The same name as the method."""
        return title

    @plugins.toolkit("jira", tools=[create_issue])
    class JiraToolkit(skye.Toolkit):
        @capability
        def create_issue(self, title: str) -> str:
            """Create an issue."""
            return title

    with pytest.raises(skye.ConfigurationError) as caught:
        skye.toolkit("jira")
    text = str(caught.value)
    assert "attribute 'create_issue'" in text and "listed function 'create_issue'" in text
