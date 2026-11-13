"""The Claude models that refuse a forced capability choice are data in the profiles, not tuples in
the adapters (D109, Requirement 60.7)."""

from __future__ import annotations

import pytest

from skye.models.plugins.anthropic import AnthropicProvider
from skye.models.plugins.bedrock import BedrockProvider

# The rule the two adapters used to hold, kept here as the oracle: a substring match of four
# fragments anywhere in the model id.
OLD_FRAGMENTS = ("opus-5-5", "sonnet-5-5", "fable-5-1", "mythos-5-1")


def old_rule(model: str) -> bool:
    return bool(model) and any(fragment in model for fragment in OLD_FRAGMENTS)


ANTHROPIC_IDS = [
    "claude-opus-5-5",
    "claude-opus-5-5-20261101",
    "claude-opus-5-5-latest",
    "claude-sonnet-5-5",
    "claude-sonnet-5-5-20261101",
    "claude-sonnet-5-5@20261101",
    "claude-fable-5-1",
    "claude-mythos-5-1",
    "claude-opus-5",
    "claude-haiku-5-5",
    "claude-fable-5-2",
    "claude-opus-4-1",
    "claude-3-5-sonnet-20240620",
]
BEDROCK_IDS = [
    "anthropic.claude-opus-5-5-v1:0",
    "anthropic.claude-opus-5-5-20261101-v1:0",
    "us.anthropic.claude-sonnet-5-5-v1:0",
    "eu.anthropic.claude-opus-5-5-20261101-v1:0",
    "global.anthropic.claude-fable-5-1-v1:0",
    "apac.anthropic.claude-mythos-5-1-v1:0",
    "us-gov.anthropic.claude-sonnet-5-5-v1:0",
    "anthropic.claude-3-5-sonnet-20240620-v1:0",
    "us.anthropic.claude-haiku-5-5-v1:0",
    "meta.llama3-70b-instruct-v1:0",
    "amazon.nova-pro-v1:0",
]


@pytest.fixture(scope="module")
def anthropic() -> AnthropicProvider:
    return AnthropicProvider(api_key="sk-ant-test")


@pytest.fixture(scope="module")
def bedrock() -> BedrockProvider:
    return BedrockProvider(region_name="us-west-2")


@pytest.mark.parametrize("model", ANTHROPIC_IDS)
def test_the_anthropic_profile_gives_the_answer_of_the_old_substring_rule(anthropic, model):
    assert anthropic.refuses_forced_choice(model) is old_rule(model), model


@pytest.mark.parametrize("model", BEDROCK_IDS)
def test_the_bedrock_profile_gives_the_answer_of_the_old_substring_rule(bedrock, model):
    assert bedrock.refuses_forced_choice(model) is old_rule(model), model


def test_the_four_refusing_models_are_exactly_the_ones_the_profiles_name():
    from skye.models.plugins import profiles

    for provider, prefix in (("anthropic", "claude-"), ("bedrock", "anthropic.claude-")):
        refusing = {
            m
            for m, e in profiles()[provider].models.items()
            if e.info.get("supports_forced_capability_choice") is False
        }
        assert refusing == {prefix + fragment for fragment in OLD_FRAGMENTS}


def test_the_adapters_hold_no_list_any_more():
    from skye.models.plugins.bedrock import provider as bedrock_module
    from skye.models.utilities.anthropic_compatible import provider as compatible_module

    for module in (bedrock_module, compatible_module):
        assert not hasattr(module, "CLAUDE_REFUSING_FORCED_CHOICE")
    assert not hasattr(compatible_module, "claude_refuses_forced_choice")


def test_get_model_info_carries_the_profile_info_of_the_model(anthropic, bedrock):
    assert anthropic.get_model_info("claude-opus-5-5")["supports_forced_capability_choice"] is False
    assert (
        bedrock.get_model_info("us.anthropic.claude-opus-5-5-v1:0")[
            "supports_forced_capability_choice"
        ]
        is False
    )
    # the keys the adapter knows are still there, and a model with no entry has only those
    assert anthropic.get_model_info("claude-opus-5-5")["supports_streaming"] is True
    assert "supports_forced_capability_choice" not in anthropic.get_model_info("claude-haiku-5-5")
    assert "supports_forced_capability_choice" not in bedrock.get_model_info(
        "meta.llama3-70b-instruct-v1:0"
    )


def test_get_model_info_without_a_model_describes_the_default_model():
    refusing = AnthropicProvider(model="claude-sonnet-5-5", api_key="sk-ant-test")
    assert refusing.get_model_info()["supports_forced_capability_choice"] is False
    assert (
        "supports_forced_capability_choice"
        not in AnthropicProvider(model="claude-haiku-5-5", api_key="sk-ant-test").get_model_info()
    )


def test_a_plugin_profile_declares_which_of_its_models_refuse_a_forced_choice():
    """A third-party Anthropic-format provider declares it in its own profile, with no list in its
    class."""
    import skye.base.plugins as plugins_module
    from skye.base.plugins import Registrar
    from skye.base.profile import ModelProfile, ProviderProfile
    from skye.models.utilities.anthropic_compatible import AnthropicCompatibleProvider

    registrar = Registrar()
    registrar.provider(
        "acme-claude",
        AnthropicCompatibleProvider,
        profile=ProviderProfile(
            "acme-claude",
            models={"acme-1": ModelProfile(info={"supports_forced_capability_choice": False})},
        ),
        function="model",
    )

    class Acme(AnthropicCompatibleProvider):
        provider_name = "acme-claude"

    original = plugins_module._default
    plugins_module._default = registrar
    try:
        client = Acme(api_key="k", api_base="https://api.acme.example")
        assert client.refuses_forced_choice("acme-1-20270101")
        assert not client.refuses_forced_choice("acme-2")
    finally:
        plugins_module._default = original


# -- what the old substring rule caught and a profile entry does not (reported to the owner)
# -------------------------------


@pytest.mark.parametrize(
    "model", ["anthropic/claude-opus-5-5", "claude-opus-5-5-preview", "claude-opus-5-5-thinking"]
)
def test_ids_the_old_rule_caught_by_substring_and_the_profile_lookup_does_not(anthropic, model):
    """A provider-prefixed id or a suffix that is not a date, a version or ``latest`` is another
    name for ``find_model_profile`` (Requirement 59.4).

    The old rule matched them because it looked for a fragment anywhere. The router and the
    registrar pass the plain model id, so none of these reaches the
    adapter today; if one ever should, the extension is a field of ``ProviderProfile`` that lists
    the prefixes and suffixes its model ids may carry.
    """
    assert old_rule(model) is True
    assert anthropic.refuses_forced_choice(model) is False
