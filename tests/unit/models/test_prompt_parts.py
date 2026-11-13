"""Prompt parts to native provider fields (Requirement 33.9, decisions D81, D101).

``PromptParts`` (``base``) carries the system text, the messages, the output schema and the
fallback text with no provider in them; each adapter puts them in its native fields, or into text
when the model capabilities lack the field.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

import skye
from skye.base.exceptions import ValidationError
from skye.base.interfaces import OutputSchema as ExportedOutputSchema
from skye.base.interfaces import PromptParts as ExportedPromptParts
from skye.base.messages import UserMessage
from skye.base.prompt_parts import OutputSchema, PromptParts
from skye.models.utilities.prompt_parts import request_from_parts
from skye.models.plugins.google.schema import gemini_schema
from skye.models.utilities.structured import STRUCTURED_TOOL, parse_structured
from tests.examples.fake_network import FakeResponse

SCHEMA = {
    "type": "object",
    "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
    "required": ["name", "age"],
}
OUTPUT = OutputSchema("person", SCHEMA)
ANSWER = {"name": "Alice", "age": 30}
PARTS = PromptParts(messages=(UserMessage(content="Who?"),), system="Be brief.", output=OUTPUT)


def _send(
    provider: str, model: str, reply: dict[str, Any], parts: PromptParts, **options: Any
) -> tuple[Any, dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    def urlopen(req: Any, timeout: float | None = None, **_: Any) -> FakeResponse:
        sent.append(json.loads(req.data))
        return FakeResponse(json.dumps(reply).encode())

    client = skye.provider(provider, **options)
    with patch("urllib.request.urlopen", urlopen):
        response = client.complete(parts, model=model)
    return response, sent[-1]


def _openai_reply(text: str) -> dict[str, Any]:
    return {
        "id": "c",
        "created": 1700000000,
        "model": "gpt-4o",
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def test_the_types_are_exported_with_the_prompt_ports():
    assert ExportedPromptParts is PromptParts and ExportedOutputSchema is OutputSchema


def test_openai_gets_a_system_message_and_a_strict_response_format():
    response, sent = _send(
        "openai", "gpt-4o", _openai_reply(json.dumps(ANSWER)), PARTS, api_key="k"
    )
    assert sent["messages"][0] == {"role": "system", "content": "Be brief."}
    fmt = sent["response_format"]
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["name"] == "person"
    assert (
        fmt["json_schema"]["strict"] is True
        and fmt["json_schema"]["schema"]["additionalProperties"] is False
    )
    assert response.structured_output == ANSWER


def test_openai_non_strict_when_the_parts_say_so():
    parts = PromptParts(
        messages=PARTS.messages, output=OutputSchema("person", SCHEMA, strict=False)
    )
    _, sent = _send("openai", "gpt-4o", _openai_reply(json.dumps(ANSWER)), parts, api_key="k")
    assert sent["response_format"]["json_schema"]["strict"] is False
    assert "additionalProperties" not in sent["response_format"]["json_schema"]["schema"]


def test_anthropic_gets_the_system_field_and_the_native_output_format():
    """Owner decision of 2026-11-11: no forced tool (a 400 on Opus 5.5, Sonnet 5.5, Fable 5.1)."""
    reply = {
        "id": "m",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": [{"type": "text", "text": json.dumps(ANSWER)}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    response, sent = _send("anthropic", "claude-opus-5-5", reply, PARTS, api_key="k")
    assert sent["system"] == "Be brief."
    assert all(m["role"] != "system" for m in sent["messages"])
    assert sent["output_config"]["format"]["type"] == "json_schema"
    assert sent["output_config"]["format"]["schema"]["properties"] == SCHEMA["properties"]
    assert "tool_choice" not in sent and "tools" not in sent
    assert response.structured_output == ANSWER


def test_bedrock_converse_gets_the_top_level_system_and_the_native_format():
    reply = {
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"text": json.dumps(ANSWER)}],
            }
        },
        "stopReason": "end_turn",
        "usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
    }
    response, sent = _send(
        "bedrock",
        "anthropic.claude-3-sonnet",
        reply,
        PARTS,
        region_name="us-east-1",
        aws_access_key_id="a",
        aws_secret_access_key="b",
    )
    assert sent["system"] == [{"text": "Be brief."}]
    assert [m["role"] for m in sent["messages"]] == ["user"]
    schema = json.loads(sent["outputConfig"]["textFormat"]["structure"]["jsonSchema"]["schema"])
    assert schema["properties"] == SCHEMA["properties"]
    assert "toolConfig" not in sent
    assert response.structured_output == ANSWER


def _gemini_reply(text: str) -> dict[str, Any]:
    return {
        "candidates": [
            {"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": "STOP"}
        ],
        "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2},
    }


def test_gemini_gets_system_instruction_and_a_native_response_schema():
    response, sent = _send(
        "google",
        "gemini-1.5-pro",
        _gemini_reply(json.dumps(ANSWER)),
        PARTS,
        project_id="p",
        location="us-central1",
        credentials="token",
    )
    assert sent["systemInstruction"] == {"parts": [{"text": "Be brief."}]}
    config = sent["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert config["responseSchema"] == {
        "type": "OBJECT",
        "properties": {"name": {"type": "STRING"}, "age": {"type": "INTEGER"}},
        "required": ["name", "age"],
    }
    assert response.structured_output == ANSWER


def test_gemini_falls_back_to_instructions_for_a_schema_outside_its_subset():
    schema = {
        "type": "object",
        "properties": {"x": {"$ref": "#/$defs/X"}},
        "$defs": {"X": {"type": "string"}},
    }
    parts = PromptParts(messages=PARTS.messages, output=OutputSchema("thing", schema))
    _, sent = _send(
        "google",
        "gemini-1.5-pro",
        _gemini_reply("{}"),
        parts,
        project_id="p",
        location="us-central1",
        credentials="token",
    )
    assert "responseSchema" not in sent["generationConfig"]
    assert "JSON Schema" in sent["systemInstruction"]["parts"][-1]["text"]


def test_gemini_schema_maps_null_to_nullable_and_drops_additional_properties():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "note": {"type": ["string", "null"]},
            "tag": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
    }
    assert gemini_schema(schema) == {
        "type": "OBJECT",
        "properties": {
            "note": {"type": "STRING", "nullable": True},
            "tag": {"type": "STRING", "nullable": True},
        },
    }


def test_no_schema_and_no_system_send_neither_field():
    parts = PromptParts(messages=(UserMessage(content="Hi"),))
    _, sent = _send("openai", "gpt-4o", _openai_reply("hello"), parts, api_key="k")
    assert "response_format" not in sent
    assert [m["role"] for m in sent["messages"]] == ["user"]


def test_a_model_without_structured_output_gets_the_fallback_text():
    info = {"supports_structured_output": False, "supports_function_calling": False}
    parts = PromptParts(
        messages=PARTS.messages,
        system="Be brief.",
        output=OUTPUT,
        fallback_text="Answer as JSON with name and age.",
    )
    request = request_from_parts(parts, model="m", info=info)
    assert request.response_schema is None
    assert request.messages[0].content == "Be brief.\n\nAnswer as JSON with name and age."


def test_without_fallback_text_the_schema_becomes_the_instruction():
    request = request_from_parts(
        PromptParts(messages=PARTS.messages, output=OUTPUT), model="m", info={}
    )
    assert request.response_schema is None
    assert "JSON Schema" in request.messages[0].content and '"age"' in request.messages[0].content


def test_a_model_without_system_messages_gets_the_text_before_the_first_user_message():
    request = request_from_parts(
        PARTS,
        model="m",
        info={"supports_system_messages": False, "supports_function_calling": True},
    )
    assert [m.role for m in request.messages] == ["user"]
    assert request.messages[0].content == "Be brief.\n\nWho?"
    assert request.response_schema is OUTPUT


def test_the_parts_are_not_changed():
    request_from_parts(PARTS, model="m", info={"supports_system_messages": False})
    assert PARTS.messages[0].content == "Who?"


def test_the_reply_must_be_an_object_with_the_required_keys():
    assert parse_structured(OUTPUT, json.dumps(ANSWER)) == ANSWER
    with pytest.raises(ValidationError, match="lacks the field 'age'"):
        parse_structured(OUTPUT, '{"name": "A"}')
    with pytest.raises(ValidationError, match="not a JSON object"):
        parse_structured(OUTPUT, "[1]")
    with pytest.raises(ValidationError, match="not JSON"):
        parse_structured(OUTPUT, "nope")


def test_parts_need_a_model_not_a_router():
    client = skye.provider("openai", api_key="k")
    with pytest.raises(ValueError, match="need a 'model'"):
        client.complete(PARTS, router=object())
