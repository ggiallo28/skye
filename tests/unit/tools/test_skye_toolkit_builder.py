"""The builder ``skye.toolkit(name, **options)`` (task 18.4; Requirements 62.6 and 56.11 of steering)."""

from __future__ import annotations

import subprocess
import sys

import pytest

import skye
from skye import ConfigurationError
from skye.tools import CapabilityRegistry, capability
from skye.tools.toolkit import Toolkit
from tests.unit.plugins.registrar_state import restored_default_registrar


@pytest.fixture
def plugins():
    """The default handle, with the default registrar put back as it was after the test."""
    with restored_default_registrar():
        yield skye.Plugins()


def _jira(plugins: skye.Plugins, name: str = "jira") -> type[Toolkit]:
    @plugins.toolkit(name)
    class JiraToolkit(Toolkit):
        def __init__(self, *, base_url: str = "https://acme.example") -> None:
            self.base_url = base_url
            self.created: list[str] = []

        @capability
        def create_issue(self, title: str) -> str:
            """Create an issue and return its key."""
            self.created.append(title)
            return f"PROJ-{len(self.created)} at {self.base_url}"

    return JiraToolkit


async def _run(toolkit: Toolkit, name: str, **arguments: object):
    from skye.completion import CapabilityCall

    return await toolkit.run(CapabilityCall(id="1", name=name, arguments=arguments))


def test_a_toolkit_added_with_the_decorator_is_built_by_name(plugins):
    cls = _jira(plugins)
    built = skye.toolkit("jira")
    assert type(built) is cls
    assert built.toolkit_name == "jira"


def test_the_options_reach_the_constructor(plugins):
    _jira(plugins)
    assert (
        skye.toolkit("jira", base_url="https://other.example").base_url == "https://other.example"
    )


@pytest.mark.asyncio
async def test_the_tools_run_through_run_with_the_prefixed_name(plugins):
    _jira(plugins)
    toolkit = skye.toolkit("jira")
    assert [schema.name for schema in await toolkit.list_schemas()] == ["jira.create_issue"]
    message = await _run(toolkit, "jira.create_issue", title="Broken login")
    assert "PROJ-1" in message.content


@pytest.mark.asyncio
async def test_the_alias_is_the_prefix_and_two_builds_do_not_share_state(plugins):
    _jira(plugins)
    one = skye.toolkit("jira", alias="jira-eu", base_url="https://eu.example")
    two = skye.toolkit("jira", alias="jira-us", base_url="https://us.example")
    assert [s.name for s in await one.list_schemas()] == ["jira-eu.create_issue"]
    assert [s.name for s in await two.list_schemas()] == ["jira-us.create_issue"]
    await _run(one, "jira-eu.create_issue", title="a")
    await _run(one, "jira-eu.create_issue", title="b")
    assert one.created == ["a", "b"]
    assert two.created == []
    assert (await _run(two, "jira-us.create_issue", title="c")).content.startswith("PROJ-1 ")


def test_without_an_alias_the_prefix_is_the_registered_name(plugins):
    _jira(plugins, "tracker")
    assert skye.toolkit("tracker").alias is None
    assert skye.toolkit("tracker")._prefix() == "tracker"


def test_an_unknown_name_raises_and_lists_the_registered_toolkits(plugins):
    _jira(plugins)
    with pytest.raises(ConfigurationError) as caught:
        skye.toolkit("nope")
    assert "no toolkit named 'nope'" in str(caught.value)
    assert "jira" in str(caught.value)
    assert "jira" in caught.value.details["known"]


def test_replace_true_replaces_a_built_in_toolkit_and_the_builder_returns_the_new_one(plugins):
    class Other(Toolkit):
        @capability
        def read(self) -> str:
            """Read."""
            return "other"

    built_in = plugins.get("toolkit", "files")  # the toolkit that ships with Skye
    assert built_in.__name__ == "FilesToolkit"
    with pytest.raises(ConfigurationError):
        plugins.toolkit("files", Other)  # a duplicate is an error without replace=True
    assert plugins.get("toolkit", "files") is built_in
    plugins.toolkit("files", Other, replace=True)
    assert type(skye.toolkit("files")) is Other


@pytest.mark.parametrize("name", ["openapi", "files"])
def test_replace_true_replaces_the_built_in_openapi_and_files_toolkits(plugins, name):
    class Other(Toolkit):
        pass

    built_in = plugins.get("toolkit", name)
    with pytest.raises(ConfigurationError):
        plugins.toolkit(name, Other)
    assert plugins.get("toolkit", name) is built_in
    plugins.toolkit(name, Other, replace=True)
    assert type(skye.toolkit(name)) is Other


def test_a_plugin_builds_on_a_registered_toolkit_by_its_class(plugins):
    base = _jira(plugins, "tracker")
    assert plugins.get("toolkit", "tracker") is base

    @plugins.toolkit("acme-api")
    class AcmeApiToolkit(
        plugins.get("toolkit", "tracker")
    ):  # the idiom of examples/plugins/builtin_toolkit.py
        def __init__(self, *, api_key: str) -> None:
            super().__init__(base_url="https://api.acme.example")
            self.api_key = api_key

    built = skye.toolkit("acme-api", api_key="k")
    assert isinstance(built, base)
    assert built.base_url == "https://api.acme.example"
    assert built.api_key == "k"
    assert built.toolkit_name == "acme-api"


@pytest.mark.asyncio
async def test_the_tools_of_the_registration_are_applied(plugins):
    @capability
    def slugify(title: str) -> str:
        """Make a slug."""
        return "-".join(title.lower().split())

    plugins.toolkit("text", tools=[slugify])  # no class: a toolkit made of the listed functions
    toolkit = skye.toolkit("text")
    assert [s.name for s in await toolkit.list_schemas()] == ["text.slugify"]
    assert (
        await _run(toolkit, "text.slugify", title="Hello Big World")
    ).content == "hello-big-world"


@pytest.mark.asyncio
async def test_the_tools_of_the_registration_join_the_methods_of_the_class(plugins):
    @capability
    def slugify(title: str) -> str:
        """Make a slug."""
        return title.lower()

    @plugins.toolkit("jira", tools=[slugify])
    class JiraToolkit(Toolkit):
        @capability
        def create_issue(self, title: str) -> str:
            """Create an issue."""
            return "KEY"

    names = [s.name for s in await skye.toolkit("jira").list_schemas()]
    assert names == ["jira.create_issue", "jira.slugify"]


@pytest.mark.asyncio
async def test_a_function_that_returns_a_registry_is_a_toolkit(plugins):
    @plugins.toolkit("notes")
    def notes(*, prefix: str = "note") -> CapabilityRegistry:
        registry = CapabilityRegistry()

        @capability
        def add(text: str) -> str:
            """Add a note."""
            return f"{prefix}: {text}"

        registry.add(add)
        return registry

    toolkit = skye.toolkit("notes", prefix="memo", alias="notes-2")
    assert [s.name for s in await toolkit.list_schemas()] == ["notes-2.add"]
    assert (await _run(toolkit, "notes-2.add", text="x")).content == "memo: x"


def test_a_target_that_builds_something_else_is_an_error(plugins):
    plugins.toolkit("odd", lambda: 42)
    with pytest.raises(ConfigurationError):
        skye.toolkit("odd")


def test_the_builder_is_a_name_of_skye_and_import_skye_does_not_load_tools():
    assert "toolkit" in skye.__all__
    code = (
        "import sys, skye\n"
        "print('skye.tools' in sys.modules)\n"
        "try:\n"
        "    skye.toolkit('nope')\n"
        "except Exception as e:\n"
        "    print(type(e).__name__)\n"
        "print('skye.tools' in sys.modules)\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert done.stdout.splitlines() == ["False", "ConfigurationError", "True"]
