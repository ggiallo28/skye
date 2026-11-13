"""Structured output on dataclasses: the declared shape goes to every provider and the reply is validated (D24, Requirement 27)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

import pytest

import skye
from skye.base.exceptions import ValidationError
from skye.base.messages import UserMessage
from skye.base.validated import validated
from skye.models.utilities.structured import STRUCTURED_TOOL, parse_structured, schema_of, strict_schema
from tests.examples.fake_network import FakeResponse


@dataclass
class Person:
    name: str
    age: int


@validated
class Team:
    lead: Person
    members: list[Person] = field(default_factory=list)
    note: str | None = None


ANSWER = {"name": "Alice", "age": 30}


def _run(provider: str, model: str, reply: dict[str, Any], schema: type = Person, **options: Any):
    sent: list[dict[str, Any]] = []

    def urlopen(req: Any, timeout: float | None = None, **_: Any) -> FakeResponse:
        sent.append(json.loads(req.data))
        return FakeResponse(json.dumps(reply).encode())

    client = skye.provider(provider, **options)
    with patch("urllib.request.urlopen", urlopen):
        response = client.complete(messages=[UserMessage(content="x")], model=model, response_schema=schema)
    return response, sent[-1]


def _openai(text: str) -> dict[str, Any]:
    return {"id": "c", "created": 1700000000, "model": "gpt-4", "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}


def test_schema_of_a_dataclass_lists_its_fields():
    schema = schema_of(Person)
    assert schema["properties"]["age"] == {"type": "integer"}
    assert schema["required"] == ["name", "age"]


def test_a_class_that_is_not_a_dataclass_is_rejected():
    with pytest.raises(ValidationError):
        schema_of(int)


def test_strict_mode_only_when_every_property_is_required():
    assert strict_schema(schema_of(Person))["additionalProperties"] is False
    assert strict_schema(schema_of(Team)) is None  # optional fields: not usable in strict mode


def test_openai_asks_with_the_dataclass_schema_and_returns_an_instance():
    response, sent = _run("openai", "gpt-4", _openai(json.dumps(ANSWER)), api_key="k")
    fmt = sent["response_format"]["json_schema"]
    assert fmt["name"] == "Person" and fmt["strict"] is True
    assert fmt["schema"]["properties"]["name"] == {"type": "string"}
    assert response.structured_output == Person(name="Alice", age=30)


def test_openai_non_strict_for_optional_fields_and_nested_models_are_built():
    reply = _openai(json.dumps({"lead": ANSWER, "members": [ANSWER]}))
    response, sent = _run("openai", "gpt-4", reply, schema=Team, api_key="k")
    assert sent["response_format"]["json_schema"]["strict"] is False
    team = response.structured_output
    assert isinstance(team, Team) and team.lead == Person("Alice", 30) and team.members == [Person("Alice", 30)]


@pytest.mark.parametrize(
    "text, field_name",
    [
        (json.dumps({"name": "Alice", "age": "old"}), "age"),
        (json.dumps({"name": "Alice"}), "age"),
        (json.dumps([1, 2]), "<root>"),
    ],
)
def test_a_reply_that_does_not_conform_names_the_field(text, field_name):
    with pytest.raises(ValidationError) as caught:
        _run("openai", "gpt-4", _openai(text), api_key="k")
    assert caught.value.details["field"] == field_name


def test_not_json_is_a_validation_error():
    with pytest.raises(ValidationError):
        parse_structured(Person, "not json")


def test_anthropic_uses_the_native_output_format_and_reads_the_text():
    """No forced tool: ``tool_choice`` ``tool``/``any`` is a 400 on Opus 5.5, Sonnet 5.5, Fable 5.1."""
    reply = {"id": "m", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
             "stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(ANSWER)}],
             "usage": {"input_tokens": 1, "output_tokens": 1}}
    response, sent = _run("anthropic", "claude-opus-5-5", reply, api_key="k")
    schema = sent["output_config"]["format"]["schema"]
    assert sent["output_config"]["format"]["type"] == "json_schema"
    assert schema["properties"]["age"] == {"type": "integer"}
    assert schema.get("additionalProperties") is False
    assert "tool_choice" not in sent and "tools" not in sent
    assert response.structured_output == Person("Alice", 30)
    assert not response.capability_calls


def test_bedrock_forces_one_tool_on_a_model_without_native_output():
    reply = {"output": {"message": {"role": "assistant", "content": [{"toolUse": {"toolUseId": "t", "name": STRUCTURED_TOOL, "input": ANSWER}}]}},
             "stopReason": "tool_use", "usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2}}
    response, sent = _run("bedrock", "meta.llama3-70b-instruct-v1:0", reply, region_name="us-east-1", aws_access_key_id="a", aws_secret_access_key="b")
    tool = sent["toolConfig"]["tools"][0]["toolSpec"]
    assert tool["name"] == STRUCTURED_TOOL and tool["inputSchema"]["json"]["properties"]["name"] == {"type": "string"}
    assert sent["toolConfig"]["toolChoice"] == {"tool": {"name": STRUCTURED_TOOL}}
    assert response.structured_output == Person("Alice", 30)
    assert not response.capability_calls


def test_google_sends_the_schema_natively_as_response_schema():
    reply = {"candidates": [{"content": {"role": "model", "parts": [{"text": json.dumps(ANSWER)}]}, "finishReason": "STOP"}],
             "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2}}
    response, sent = _run("google", "gemini-1.5-pro", reply, project_id="p", location="us-central1", credentials="token")
    assert sent["generationConfig"]["responseMimeType"] == "application/json"
    assert sent["generationConfig"]["responseSchema"]["properties"]["age"] == {"type": "INTEGER"}
    assert "systemInstruction" not in sent
    assert response.structured_output == Person("Alice", 30)
