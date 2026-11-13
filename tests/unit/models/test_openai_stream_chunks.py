"""OpenAI stream chunks as the real API sends them: keys it has nothing to say about are absent, not null."""

from __future__ import annotations

import skye
from skye.models.utilities.rest import wrap


def _provider():
    return skye.provider("openai", api_key="k")


def test_last_chunk_has_an_empty_delta():
    chunk = wrap({"id": "c1", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
    out = _provider()._transform_stream_chunk(chunk)
    assert out.delta == "" and out.finish_reason == "stop"


def test_a_usage_only_chunk_has_no_choices():
    chunk = wrap({"id": "c1", "choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}})
    out = _provider()._transform_stream_chunk(chunk)
    assert out.delta == "" and out.finish_reason is None


def test_a_content_chunk_keeps_its_text():
    chunk = wrap({"id": "c1", "choices": [{"index": 0, "delta": {"content": "Hi"}, "finish_reason": None}]})
    assert _provider()._transform_stream_chunk(chunk).delta == "Hi"
