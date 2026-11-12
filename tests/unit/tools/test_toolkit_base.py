"""``skye.tools.Toolkit``: the methods of a class marked with ``@capability`` as one provider of tools (task 18.2)."""

import pytest

from skye.base.completion import CapabilityCall
from skye.base.exceptions import ConfigurationError
from skye.base.interfaces.tool_provider import ToolProvider
from skye.base.messages import CapabilityStatus
from skye.tools import Toolkit, capability


@capability
def slugify(title: str) -> str:
    """Make the part of an address that comes from a title."""
    return "-".join(title.lower().split())


class JiraToolkit(Toolkit):
    def __init__(self, *, base_url: str = "https://acme.example") -> None:
        self.base_url = base_url
        self.closed = False

    @capability
    def create_issue(self, title: str) -> str:
        """Create an issue and return its key."""
        return f"PROJ-1 at {self.base_url}: {title}"

    @capability(name="close_issue", description="Close an issue that is done.")
    def move_to_done(self, key: str) -> str:
        return f"{key} closed"

    @capability
    async def fetch(self, key: str) -> str:
        """Read an issue."""
        return f"{key} from {self.base_url}"

    slugify = staticmethod(slugify)

    async def close(self) -> None:
        self.closed = True


def _call(name: str, **arguments: object) -> CapabilityCall:
    return CapabilityCall(id="1", name=name, arguments=arguments)


async def test_methods_are_listed_with_the_prefix_of_the_class_name():
    schemas = await JiraToolkit().list_schemas()
    assert [schema.name for schema in schemas] == [
        "jira.close_issue",
        "jira.create_issue",
        "jira.fetch",
        "jira.slugify",
    ]


async def test_a_name_of_its_own_and_a_description_are_kept():
    by_name = {schema.name: schema for schema in await JiraToolkit().list_schemas()}
    assert by_name["jira.close_issue"].description == "Close an issue that is done."


async def test_a_call_runs_by_the_prefixed_name():
    message = await JiraToolkit(base_url="https://x.example").run(
        _call("jira.create_issue", title="Broken login")
    )
    assert message.status == CapabilityStatus.OK
    assert message.content == "PROJ-1 at https://x.example: Broken login"
    assert message.capability_name == "jira.create_issue"


async def test_an_async_method_runs():
    message = await JiraToolkit().run(_call("jira.fetch", key="A-1"))
    assert message.content == "A-1 from https://acme.example"


async def test_two_instances_keep_their_own_state():
    first, second = JiraToolkit(base_url="https://one"), JiraToolkit(base_url="https://two")
    one = await first.run(_call("jira.fetch", key="K"))
    two = await second.run(_call("jira.fetch", key="K"))
    assert (one.content, two.content) == ("K from https://one", "K from https://two")


async def test_a_staticmethod_capability_is_a_tool_with_no_self():
    toolkit = JiraToolkit()
    message = await toolkit.run(_call("jira.slugify", title="Broken Login Page"))
    assert message.content == "broken-login-page"
    # The same function stays a free tool outside the toolkit.
    assert slugify.execute(title="A B") == "a-b"


async def test_self_is_in_no_schema():
    for schema in await JiraToolkit().list_schemas():
        assert "self" not in schema.parameters.get("properties", {})
        assert "self" not in schema.parameters.get("required", [])


async def test_the_toolkit_name_is_the_prefix_when_it_is_set():
    toolkit = JiraToolkit()
    toolkit.toolkit_name = "tracker"
    assert [s.name for s in await toolkit.list_schemas()][0] == "tracker.close_issue"
    assert (await toolkit.run(_call("tracker.fetch", key="K"))).status == CapabilityStatus.OK


async def test_an_alias_replaces_the_toolkit_name():
    eu = JiraToolkit(base_url="https://eu")
    eu.toolkit_name, eu.alias = "jira", "jira-eu"
    us = JiraToolkit(base_url="https://us")
    us.toolkit_name, us.alias = "jira", "jira-us"
    assert (await eu.run(_call("jira-eu.fetch", key="K"))).content == "K from https://eu"
    assert (await us.run(_call("jira-us.fetch", key="K"))).content == "K from https://us"
    unknown = await eu.run(_call("jira.fetch", key="K"))
    assert unknown.status == CapabilityStatus.ERROR


async def test_a_prefix_set_after_the_first_use_is_taken():
    toolkit = JiraToolkit()
    await toolkit.list_schemas()
    toolkit.alias = "late"
    assert (await toolkit.run(_call("late.fetch", key="K"))).status == CapabilityStatus.OK


async def test_an_unknown_name_is_an_error_message_and_does_not_raise():
    message = await JiraToolkit().run(_call("jira.nothing"))
    assert message.status == CapabilityStatus.ERROR
    assert "not found" in message.content


async def test_a_failing_tool_is_an_error_message():
    class Failing(Toolkit):
        @capability
        def boom(self) -> str:
            """Always fails."""
            raise RuntimeError("no luck")

    message = await Failing().run(_call("failing.boom"))
    assert message.status == CapabilityStatus.ERROR
    assert "no luck" in message.content


async def test_close_is_awaited_and_is_a_no_op_by_default():
    toolkit = JiraToolkit()
    await toolkit.close()
    assert toolkit.closed is True

    class Quiet(Toolkit):
        @capability
        def ping(self) -> str:
            """Answer."""
            return "pong"

    assert await Quiet().close() is None


def test_two_tools_with_the_same_prefixed_name_raise_at_construction():
    class Clash(Toolkit):
        @capability(name="issue")
        def first(self) -> str:
            """One."""
            return "1"

        @capability(name="issue")
        def second(self) -> str:
            """Two."""
            return "2"

    with pytest.raises(ConfigurationError) as caught:
        Clash()
    message = str(caught.value)
    assert "first" in message and "second" in message and "issue" in message


def test_a_subclass_that_overrides_a_tool_with_a_plain_method_loses_the_tool():
    class Base(Toolkit):
        @capability
        def ping(self) -> str:
            """Answer."""
            return "pong"

    class Child(Base):
        def ping(self) -> str:  # type: ignore[override]
            return "not a tool"

    assert Child()._tools() == {}


async def test_a_toolkit_with_no_tool_lists_nothing():
    class Empty(Toolkit):
        pass

    assert await Empty().list_schemas() == []


def test_a_toolkit_is_a_tool_provider():
    assert isinstance(JiraToolkit(), ToolProvider)


async def test_a_toolkit_without_the_class_suffix_uses_its_whole_name():
    class Weather(Toolkit):
        @capability
        def today(self) -> str:
            """Today."""
            return "sunny"

    assert [s.name for s in await Weather().list_schemas()] == ["weather.today"]
