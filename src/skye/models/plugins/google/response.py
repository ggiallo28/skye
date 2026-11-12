"""Google (Gemini): how a response and a stream chunk are read (D110).

A ``generateContent`` JSON response becomes a ``CompleteResponse`` and one SSE event of ``streamGenerateContent`` becomes a ``StreamChunk``. Plain
functions, so the provider class stays thin; ``GoogleProvider`` keeps the same methods and calls these.
"""

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from skye.base.completion import CompleteResponse, StreamChunk, TokenUsage
from skye.models.plugins.google.capabilities import (
    extract_capability_calls as default_extract_capability_calls,
)
from skye.models.cost import usage_of
from skye.models.utilities.rest import JsonObject, wrap


def first_candidate(response: JsonObject) -> JsonObject | None:
    """The first candidate of a response or of a stream event, or ``None``."""
    candidates = response.get("candidates") or []
    return candidates[0] if candidates else None


def finish_reason(candidate: JsonObject) -> str | None:
    """The finish reason of a candidate in lower case; ``None`` when it has none or says it is unspecified."""
    raw = candidate.get("finishReason")
    if raw is None:
        return None
    reason = str(raw).lower()
    if reason in ("none", "finish_reason_unspecified"):
        return None
    return reason


def transform_response(
    response: Any,
    capability_extractor: Callable[[Any], list[Any] | None] = default_extract_capability_calls,
) -> CompleteResponse:
    """Transform a ``generateContent`` JSON response to CompleteResponse (``capability_extractor`` is the provider's own method)."""
    response = wrap(response)
    content = ""
    reason = "stop"
    metadata: dict[str, Any] = {}

    candidate = first_candidate(response)
    if candidate is not None:
        reason = finish_reason(candidate) or "stop"
        parts = (candidate.get("content") or JsonObject({})).get("parts") or []
        texts = [p.get("text") for p in parts if p.get("text") is not None]
        content = "".join(texts)

    capability_calls = capability_extractor(response)
    if capability_calls:
        metadata = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"functionCall": {"name": c.name, "args": c.arguments}}
                            for c in capability_calls
                        ]
                    }
                }
            ]
        }

    usage = response.get("usageMetadata") or JsonObject({})
    return CompleteResponse(
        id=response.get("responseId", "") or "",
        model=response.get("modelVersion", "") or "",
        provider="google",
        content=content,
        structured_output=None,
        role="assistant",
        finish_reason=reason,
        usage=TokenUsage(
            prompt_tokens=usage.get("promptTokenCount", 0),
            completion_tokens=usage.get("candidatesTokenCount", 0),
            total_tokens=usage.get("totalTokenCount", 0),
        ),
        capability_calls=capability_calls,
        created_at=datetime.now(tz=timezone.utc),
        metadata=metadata,
    )


def transform_stream_chunk(chunk: Any) -> StreamChunk:
    """Transform one SSE event of ``streamGenerateContent`` to StreamChunk."""
    chunk = wrap(chunk)
    content = ""
    reason: str | None = None
    candidate = first_candidate(chunk)
    if candidate is not None:
        reason = finish_reason(candidate)
        parts = (candidate.get("content") or JsonObject({})).get("parts") or []
        content = "".join(p.get("text") for p in parts if p.get("text") is not None)
    # usageMetadata, when an event has it, is a running count of the whole call.
    reported = chunk.get("usageMetadata")
    usage = (
        usage_of(
            reported.get("promptTokenCount"),
            reported.get("candidatesTokenCount"),
            reported.get("totalTokenCount"),
        )
        if reported
        else None
    )
    return StreamChunk(id="", delta=content, finish_reason=reason, index=0, usage=usage)
