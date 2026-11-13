"""``return_direct`` on ``@capability`` (task 18.5 of plugins, Requirements 62.2 and 62.3).

The flag is stored on the capability, validated as a bool and put on the schema, so that an agent
reads it through the
``ToolProvider`` Port. No adapter sends it to a model: the rules of the flag are the agents spec
(O70).
"""

import asyncio
import dataclasses
import json

import pytest

from skye.base.completion import CompleteRequest
from skye.base.interfaces.capability import CapabilitySchema
from skye.base.messages import UserMessage
from skye.models import OpenAICompatibleProvider
from skye.models.utilities.anthropic_compatible.capabilities import (
    transform_capabilities as anthropic_tools,
)
from skye.models.utilities.openai_compatible.capabilities import (
    transform_capabilities as openai_tools,
)
from skye.tools import CapabilityRegistry, LocalFunctionCapability, capability
from skye.tools.exceptions import CapabilityValidationError


@capability
def plain(text: str) -> str:
    """Repeat a text."""
    return text


@capability(return_direct=True)
def direct(text: str) -> str:
    """Repeat a text."""
    return text


@capability(name="shout", description="Repeat a text loudly.", return_direct=True)
def loud(text: str) -> str:
    return text.upper()


def test_the_default_is_false() -> None:
    assert plain.get_schema().return_direct is False
    assert CapabilitySchema(name="n", description="d").return_direct is False
    assert (
        LocalFunctionCapability(lambda text: text, name="echo").get_schema().return_direct is False
    )


def test_the_flag_is_on_the_schema() -> None:
    assert direct.get_schema().return_direct is True


def test_the_three_options_together() -> None:
    schema = loud.get_schema()
    assert (schema.name, schema.description, schema.return_direct) == (
        "shout",
        "Repeat a text loudly.",
        True,
    )


def test_the_name_and_the_description_keep_their_defaults() -> None:
    schema = direct.get_schema()
    assert schema.name == "direct"
    assert schema.description == "Repeat a text."


def test_the_bare_form_still_works() -> None:
    assert isinstance(plain, LocalFunctionCapability)


def test_the_flag_does_not_change_what_the_tool_does() -> None:
    assert direct.execute(text="a") == "a"
    assert asyncio.run(direct.aexecute(text="a")) == "a"


@pytest.mark.parametrize("bad", ["yes", 1, 0, None])
def test_the_capability_refuses_a_flag_that_is_not_a_bool(bad: object) -> None:
    with pytest.raises(CapabilityValidationError, match="return_direct"):
        LocalFunctionCapability(lambda text: text, return_direct=bad)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", ["yes", 1, 0, None])
def test_the_decorator_refuses_a_flag_that_is_not_a_bool(bad: object) -> None:
    with pytest.raises(CapabilityValidationError, match="return_direct"):
        capability(return_direct=bad)(lambda text: text)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", ["yes", 1, 0, None])
def test_the_schema_refuses_a_flag_that_is_not_a_bool(bad: object) -> None:
    with pytest.raises(Exception, match="return_direct"):
        CapabilitySchema(name="n", description="d", return_direct=bad)  # type: ignore[arg-type]


def test_the_schema_with_the_flag_is_frozen_and_equal_by_value() -> None:
    schema = CapabilitySchema(name="n", description="d", return_direct=True)
    assert schema == CapabilitySchema(name="n", description="d", return_direct=True)
    assert schema != CapabilitySchema(name="n", description="d")
    with pytest.raises(dataclasses.FrozenInstanceError):
        schema.return_direct = False  # type: ignore[misc]


def test_a_schema_override_keeps_its_own_flag() -> None:
    override = CapabilitySchema(name="o", description="d", return_direct=True)
    assert LocalFunctionCapability(lambda: None, schema_override=override).get_schema() == override


def test_a_flag_given_with_a_schema_override_is_put_on_it() -> None:
    override = CapabilitySchema(name="o", description="d")
    schema = LocalFunctionCapability(
        lambda: None, schema_override=override, return_direct=True
    ).get_schema()
    assert schema.return_direct is True
    assert (schema.name, schema.description) == ("o", "d")
    assert override.return_direct is False


def test_a_method_keeps_the_flag_when_it_is_bound() -> None:
    class Shop:
        @capability(return_direct=True)
        def confirm(self, order: str) -> str:
            """Confirm an order."""
            return f"{order} confirmed"

    bound = Shop().confirm
    assert bound.get_schema().return_direct is True
    assert bound.execute(order="42") == "42 confirmed"


def test_the_registry_passes_the_flag_through_the_port() -> None:
    registry = CapabilityRegistry()
    registry.add(plain)
    registry.add(direct)
    schemas = {schema.name: schema for schema in asyncio.run(registry.list_schemas())}
    assert schemas["plain"].return_direct is False
    assert schemas["direct"].return_direct is True


def _unflagged() -> LocalFunctionCapability:
    return LocalFunctionCapability(lambda text: text, name="repeat", description="Repeat a text.")


def _flagged() -> LocalFunctionCapability:
    return LocalFunctionCapability(
        lambda text: text, name="repeat", description="Repeat a text.", return_direct=True
    )


def test_the_openai_tool_is_the_same_with_and_without_the_flag() -> None:
    assert openai_tools([_flagged()]) == openai_tools([_unflagged()])
    assert "return_direct" not in json.dumps(openai_tools([_flagged()]))


def test_the_anthropic_tool_is_the_same_with_and_without_the_flag() -> None:
    assert anthropic_tools([_flagged()]) == anthropic_tools([_unflagged()])
    assert "return_direct" not in json.dumps(anthropic_tools([_flagged()]))


def test_the_openai_request_does_not_carry_the_flag() -> None:
    provider = OpenAICompatibleProvider(model="gpt-4o-mini", api_key="not-a-real-key")
    request = CompleteRequest(
        model="gpt-4o-mini",
        messages=[UserMessage(content="hello")],
        capabilities=[_flagged()],
    )
    same = CompleteRequest(
        model="gpt-4o-mini",
        messages=[UserMessage(content="hello")],
        capabilities=[_unflagged()],
    )
    body = provider._transform_request(request)
    assert body == provider._transform_request(same)
    assert "return_direct" not in json.dumps(body)
