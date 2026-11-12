"""A forced capability choice, emulated for the models that refuse one (decision D109).

Claude Opus 5.5, Sonnet 5.5, Fable 5.1 and Mythos 5.1 answer a forced ``tool_choice`` (``any`` or
``tool``) with a 400. For them Skye sends ``auto`` plus an instruction appended at the end, checks
the answer, retries once, then raises ``CapabilityChoiceError``; the conversation stays append-only.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from skye.base.completion import CompleteRequest
from skye.base.exceptions import CapabilityChoiceError, ValidationError
from skye.base.messages import AssistantMessage, UserMessage
from skye.models.plugins.anthropic.provider import AnthropicProvider
from skye.models.plugins.bedrock.provider import BedrockProvider
from skye.models.utilities.capability_choice import instruction
from skye.models.utilities.rest import JsonObject

POST = "skye.models.utilities.rest.post_json"
REFUSING = "claude-opus-5-5"


class _Capability:
    def __init__(self, name: str) -> None:
        self.name = name

    def get_schema(self) -> Any:
        from skye.interfaces import CapabilitySchema

        return CapabilitySchema(
            name=self.name, description=self.name, parameters={"type": "object"}
        )


TOOLS = [_Capability("search"), _Capability("calculator"), _Capability("send_email")]


def _answer(*blocks: dict[str, Any]) -> JsonObject:
    stop = "tool_use" if any(b["type"] == "tool_use" for b in blocks) else "end_turn"
    return JsonObject({
        "id": "msg_1", "model": REFUSING, "type": "message", "role": "assistant",
        "content": list(blocks), "stop_reason": stop, "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    })


def _call(name: str) -> dict[str, Any]:
    return {"type": "tool_use", "id": f"tu_{name}", "name": name, "input": {}}


TEXT = {"type": "text", "text": "I would rather answer in words."}


def _provider() -> AnthropicProvider:
    return AnthropicProvider(model=REFUSING, api_key="sk-ant-test")


def _request(choice: str = "search", model: str = REFUSING, **kwargs: Any) -> CompleteRequest:
    messages = kwargs.pop("messages", [UserMessage(content="Find the weather in Rome")])
    return CompleteRequest(
        messages=messages, model=model, capabilities=TOOLS, capability_choice=choice, **kwargs
    )


def test_refusing_models_are_known_by_the_adapters() -> None:
    client = _provider()
    for model in ("claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1", "claude-mythos-5-1"):
        assert client.refuses_forced_choice(model)
    assert not client.refuses_forced_choice("claude-opus-5")
    assert not client.refuses_forced_choice("claude-haiku-5-5")
    bedrock = BedrockProvider(region_name="us-west-2")
    assert bedrock.refuses_forced_choice("us.anthropic.claude-sonnet-5-5-v1:0")
    assert not bedrock.refuses_forced_choice("meta.llama3-70b-instruct-v1:0")


def test_named_choice_sends_auto_every_tool_and_an_appended_instruction() -> None:
    with patch(POST, return_value=_answer(_call("search"))) as post:
        response = _provider().complete(_request())
    body = post.call_args.args[1]
    assert body["tool_choice"] == {"type": "auto"}
    assert [t["name"] for t in body["tools"]] == ["search", "calculator", "send_email"]
    assert body["messages"][0] == {"role": "user", "content": "Find the weather in Rome"}
    assert body["messages"][-1] == {"role": "user", "content": instruction("search")}
    assert post.call_count == 1
    assert [c.name for c in response.capability_calls or []] == ["search"]
    assert [m.content for m in response.added_messages] == [instruction("search")]
    assert response.metadata["capability_choice_emulated"] is True


def test_force_choice_sends_only_the_named_capability() -> None:
    with patch(POST, return_value=_answer(_call("search"))) as post:
        _provider().complete(_request(force_choice=True))
    assert [t["name"] for t in post.call_args.args[1]["tools"]] == ["search"]


def test_force_choice_after_the_first_answer_is_refused_before_any_call() -> None:
    history = [
        UserMessage(content="hi"),
        AssistantMessage(content="hello"),
        UserMessage(content="Find the weather in Rome"),
    ]
    with patch(POST) as post, pytest.raises(ValidationError) as info:
        _provider().complete(_request(force_choice=True, messages=history))
    assert info.value.details["field"] == "force_choice"
    post.assert_not_called()


def test_a_name_that_is_not_offered_is_refused() -> None:
    with patch(POST) as post, pytest.raises(ValidationError):
        _provider().complete(_request(choice="translate"))
    post.assert_not_called()


def test_required_accepts_any_call() -> None:
    with patch(POST, return_value=_answer(_call("calculator"))) as post:
        response = _provider().complete(_request(choice="required"))
    assert post.call_args.args[1]["messages"][-1]["content"] == instruction("required")
    assert response.capability_calls and response.capability_calls[0].name == "calculator"


def test_one_retry_then_success() -> None:
    with patch(POST, side_effect=[_answer(TEXT), _answer(_call("search"))]) as post:
        response = _provider().complete(_request())
    assert post.call_count == 2
    first, second = (c.args[1] for c in post.call_args_list)
    assert first == second  # the failed attempt is dropped: nothing of it reaches the history
    assert response.capability_calls and response.capability_calls[0].name == "search"


def test_a_wrong_call_counts_as_no_call() -> None:
    with patch(POST, return_value=_answer(_call("calculator"))) as post:
        with pytest.raises(CapabilityChoiceError) as info:
            _provider().complete(_request())
    assert post.call_count == 2
    assert info.value.capability_choice == "search"
    assert info.value.status_code is None


def test_two_answers_without_the_call_raise() -> None:
    with patch(POST, return_value=_answer(TEXT)) as post:
        with pytest.raises(CapabilityChoiceError):
            _provider().complete(_request())
    assert post.call_count == 2


def test_models_that_accept_forcing_are_sent_the_forced_choice() -> None:
    with patch(POST, return_value=_answer(_call("search"))) as post:
        response = _provider().complete(_request(model="claude-opus-5"))
    body = post.call_args.args[1]
    assert body["tool_choice"] == {"type": "tool", "name": "search"}
    assert body["messages"] == [{"role": "user", "content": "Find the weather in Rome"}]
    assert response.added_messages == []


def test_auto_and_no_choice_are_untouched() -> None:
    with patch(POST, return_value=_answer(TEXT)) as post:
        _provider().complete(_request(choice="auto"))
    assert post.call_args.args[1]["tool_choice"] == {"type": "auto"}
    assert len(post.call_args.args[1]["messages"]) == 1


def test_bedrock_merges_the_instruction_into_the_last_user_turn() -> None:
    client = BedrockProvider(region_name="us-west-2")
    from skye.models.utilities.capability_choice import emulated_request

    changed, added = emulated_request(_request(model="us.anthropic.claude-opus-5-5-v1:0"))
    body = client._transform_request(changed)
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["user"]
    assert [b["text"] for b in body["messages"][0]["content"]] == [
        "Find the weather in Rome",
        instruction("search"),
    ]
    assert body["toolConfig"].get("toolChoice", {"auto": {}}) == {"auto": {}}
    assert len(added) == 1
