"""D119: a toolkit tool is ``<toolkit>_<name>``; a decorated function stays callable."""

import pytest

from skye.base.exceptions import ConfigurationError
from skye.completion import CapabilityCall
from skye.tools import Toolkit, capability


class Notes(Toolkit):
    @capability
    def add(self, text: str) -> str:
        """Add a note."""
        return f"noted {text}"


async def test_the_name_joins_the_prefix_and_the_tool_with_an_underscore():
    names = [schema.name for schema in await Notes().list_schemas()]
    assert names == ["notes_add"]


async def test_an_alias_replaces_the_prefix_and_keeps_the_underscore():
    toolkit = Notes()
    toolkit.alias = "docs-eu"
    assert [schema.name for schema in await toolkit.list_schemas()] == ["docs-eu_add"]
    message = await toolkit.run(CapabilityCall(id="1", name="docs-eu_add", arguments={"text": "x"}))
    assert message.content == "noted x"


@pytest.mark.parametrize("alias", ["has space", "dot.ted", "slash/ed", "é"])
async def test_a_name_a_provider_would_refuse_is_an_error_that_says_how_to_fix_it(alias):
    toolkit = Notes()
    toolkit.alias = alias
    with pytest.raises(ConfigurationError, match="letters, digits, '_' and '-'"):
        await toolkit.list_schemas()


async def test_a_name_longer_than_64_characters_is_an_error():
    toolkit = Notes()
    toolkit.alias = "a" * 61  # 61 + "_add" is 65
    with pytest.raises(ConfigurationError, match="64 characters at most"):
        await toolkit.list_schemas()


async def test_a_name_of_exactly_64_characters_is_accepted():
    toolkit = Notes()
    toolkit.alias = "a" * 60  # 60 + "_add" is 64
    names = [schema.name for schema in await toolkit.list_schemas()]
    assert [len(name) for name in names] == [64]


def test_a_decorated_function_stays_callable():
    @capability
    def shout(text: str) -> str:
        """Shout."""
        return text.upper()

    assert shout("hi") == "HI"
    assert shout.execute(text="hi") == "HI"


async def test_a_decorated_async_function_stays_awaitable():
    @capability
    async def shout(text: str) -> str:
        """Shout."""
        return text.upper()

    assert await shout("hi") == "HI"


def test_a_method_capability_read_through_an_instance_is_called_without_self():
    notes = Notes()
    assert notes.add("x") == "noted x"
    assert Notes.add(notes, "x") == "noted x"
