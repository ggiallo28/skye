"""Bedrock Converse: native structured output for Claude models (owner decision of 2026-11-11).

Claude models on Bedrock take ``outputConfig.textFormat`` (a JSON schema sent as a string), so no tool is forced:
forced ``toolChoice`` fails on Claude Opus 5.5, Sonnet 5.5 and Fable 5.1. Other Converse models keep the forced
answer tool. Source: https://docs.aws.amazon.com/bedrock/latest/userguide/structured-output.html
"""

from __future__ import annotations

import json
from typing import Any

from skye.base.completion import CompleteRequest
from skye.base.messages import UserMessage
from skye.base.prompt_parts import OutputSchema
from skye.models.plugins.bedrock.provider import BedrockProvider
from skye.models.utilities.structured import STRUCTURED_TOOL

ANSWER = OutputSchema(
    "answer",
    {"type": "object", "properties": {"word": {"type": "string"}}, "required": ["word"]},
)


class _Capability:
    name = "lookup"

    def get_schema(self) -> Any:
        from skye.interfaces import CapabilitySchema

        return CapabilitySchema(name="lookup", description="Look up", parameters={"type": "object"})


def _body(model: str, **kwargs: Any) -> dict[str, Any]:
    client = BedrockProvider(region_name="us-west-2")
    request = CompleteRequest(
        messages=[UserMessage(content="x")], model=model, response_schema=ANSWER, **kwargs
    )
    return client._transform_request(request)


def test_claude_gets_output_config_text_format_and_no_forced_tool() -> None:
    body = _body("anthropic.claude-opus-5-5")
    fmt = body["outputConfig"]["textFormat"]
    assert fmt["type"] == "json_schema"
    schema = json.loads(fmt["structure"]["jsonSchema"]["schema"])
    assert schema["properties"]["word"] == {"type": "string"}
    assert schema["additionalProperties"] is False
    assert fmt["structure"]["jsonSchema"]["name"] == "answer"
    assert "toolConfig" not in body


def test_claude_with_tools_keeps_the_tools_and_the_native_format() -> None:
    body = _body("us.anthropic.claude-sonnet-5-5", capabilities=[_Capability()])
    assert [t["toolSpec"]["name"] for t in body["toolConfig"]["tools"]] == ["lookup"]
    assert "toolChoice" not in body["toolConfig"]
    assert "outputConfig" in body
    assert not any('"word"' in block.get("text", "") for block in body.get("system", []))


def test_other_converse_models_keep_the_forced_answer_tool() -> None:
    body = _body("meta.llama3-70b-instruct-v1:0")
    assert body["toolConfig"]["toolChoice"] == {"tool": {"name": STRUCTURED_TOOL}}
    assert "outputConfig" not in body


def test_the_json_text_answer_is_parsed() -> None:
    client = BedrockProvider(region_name="us-west-2")
    response = client._transform_response(
        {
            "output": {"message": {"role": "assistant", "content": [{"text": '{"word": "hi"}'}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
        }
    )
    assert json.loads(response.content) == {"word": "hi"}
