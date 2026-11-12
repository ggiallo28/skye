"""Bedrock native JSON output is data, not a rule in the adapter (task 6.7, Requirement 60.7).

Which Converse models take ``outputConfig.textFormat`` is the ``supports_structured_output`` key of the ``info`` of a model
in the Bedrock profile, read through ``get_model_info()``. The table below is what the old function ``_native_json_output``
answered (the Anthropic Claude models: an id with ``anthropic.`` or ``claude`` in it) for the ids that Bedrock has.
"""

from __future__ import annotations

from typing import Any

import pytest

from skye.base.completion import CompleteRequest
from skye.base.messages import UserMessage
from skye.base.plugins import Plugins, get_registrar
from skye.base.profile import ModelProfile, ProviderProfile
from skye.base.prompt_parts import OutputSchema
from skye.models.plugins.bedrock.provider import BedrockProvider

CLAUDE = [
    "anthropic.claude-3-opus-20240229-v1:0",
    "anthropic.claude-3-sonnet-20240229-v1:0",
    "anthropic.claude-3-haiku-20240307-v1:0",
    "anthropic.claude-3-5-sonnet-20240620-v1:0",
    "anthropic.claude-3-5-sonnet-20241022-v2:0",
    "anthropic.claude-3-5-haiku-20241022-v1:0",
    "anthropic.claude-3-7-sonnet-20250219-v1:0",
    "anthropic.claude-opus-4-20250514-v1:0",
    "anthropic.claude-sonnet-4-20250514-v1:0",
    "anthropic.claude-opus-4-1-20250805-v1:0",
    "anthropic.claude-sonnet-4-5-20250929-v1:0",
    "anthropic.claude-haiku-4-5-20251001-v1:0",
    "anthropic.claude-3-opus",
    "anthropic.claude-3-sonnet",
    "anthropic.claude-3-haiku",
    "anthropic.claude-instant-v1",
    "anthropic.claude-v2",
    "anthropic.claude-v2:1",
    "anthropic.claude-opus-5-5",
    "anthropic.claude-sonnet-5-5",
    "anthropic.claude-fable-5-1",
    "anthropic.claude-mythos-5-1",
    "anthropic.claude-sonnet-5-5-v1:0",
    "us.anthropic.claude-sonnet-5-5-v1:0",
    "eu.anthropic.claude-3-haiku-20240307-v1:0",
    "apac.anthropic.claude-3-5-sonnet-20240620-v1:0",
    "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
]

OTHERS = [
    "amazon.titan-text-express-v1",
    "amazon.titan-text-premier-v1:0",
    "amazon.nova-pro-v1:0",
    "amazon.nova-lite-v1:0",
    "meta.llama3-70b-instruct-v1:0",
    "meta.llama3-1-405b-instruct-v1:0",
    "us.meta.llama3-2-90b-instruct-v1:0",
    "mistral.mistral-large-2402-v1:0",
    "mistral.mixtral-8x7b-instruct-v0:1",
    "cohere.command-r-plus-v1:0",
    "cohere.command-text-v14",
    "ai21.jamba-1-5-large-v1:0",
    "ai21.j2-ultra-v1",
    "deepseek.r1-v1:0",
    "us.deepseek.r1-v1:0",
    "openai.gpt-oss-120b-1:0",
    "",
    None,
]

TABLE: dict[str | None, bool] = {**{m: True for m in CLAUDE}, **{m: False for m in OTHERS}}

ANSWER = OutputSchema(
    "answer",
    {"type": "object", "properties": {"word": {"type": "string"}}, "required": ["word"]},
)


def _info(model: str | None) -> dict[str, Any]:
    return BedrockProvider(region_name="us-west-2").get_model_info(model)


@pytest.mark.parametrize("model", list(TABLE), ids=lambda m: repr(m))
def test_get_model_info_answers_what_the_old_function_answered(model: str | None) -> None:
    assert bool(_info(model).get("supports_structured_output")) is TABLE[model]


@pytest.mark.parametrize("model", [m for m in TABLE if m], ids=lambda m: repr(m))
def test_the_request_takes_the_native_format_for_the_same_models(model: str) -> None:
    client = BedrockProvider(region_name="us-west-2")
    body = client._transform_request(
        CompleteRequest(messages=[UserMessage(content="x")], model=model, response_schema=ANSWER)
    )
    assert ("outputConfig" in body) is TABLE[model]
    assert ("toolConfig" in body) is (not TABLE[model])


def test_the_adapter_has_no_function_that_decides_by_the_name_of_the_model() -> None:
    from skye.models.plugins.bedrock import provider

    assert not hasattr(provider, "_native_json_output")


def test_a_plugin_provider_of_the_converse_format_declares_it_in_its_own_profile() -> None:
    class AcmeConverse(BedrockProvider):
        provider_name = "acme-converse"

    plugins = Plugins()
    registrar = get_registrar()
    plugins.provider(
        "acme-converse",
        AcmeConverse,
        profile=ProviderProfile(
            "acme-converse",
            models={"acme.model-1": ModelProfile(info={"supports_structured_output": True})},
        ),
        function="model",
    )
    try:
        client = AcmeConverse(region_name="us-west-2")
        assert client.get_model_info("acme.model-1")["supports_structured_output"] is True
        assert client.get_model_info("acme.model-2")["supports_structured_output"] is False
        body = client._transform_request(
            CompleteRequest(
                messages=[UserMessage(content="x")], model="acme.model-1", response_schema=ANSWER
            )
        )
        assert "outputConfig" in body
        other = client._transform_request(
            CompleteRequest(
                messages=[UserMessage(content="x")], model="acme.model-2", response_schema=ANSWER
            )
        )
        assert "outputConfig" not in other
    finally:
        registrar.unregister("provider", "acme-converse", function="model")


def test_an_id_that_is_not_in_the_profile_takes_the_forced_tool() -> None:
    """The old rule matched any id with ``claude`` in it; the data names the models, so an unknown id degrades to the forced tool."""
    assert _info("custom-claude-model").get("supports_structured_output") is False
