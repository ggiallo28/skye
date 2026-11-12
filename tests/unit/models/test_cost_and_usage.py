"""The cost of a call (Requirement 19).

Covers ``metadata["cost"]``, ``pricing=``, the running counter of a stream and the tokenizers.

The provider's own token count is used when it reports one; the tokens are estimated only when
it reports none.
"""

from __future__ import annotations

import io
import json
from typing import Any
from unittest.mock import patch

import pytest

import skye
from skye.base.completion import StreamChunk, TokenUsage
from skye.base.exceptions import ValidationError
from skye.models.plugins.azure.provider import AzureOpenAIProvider
from skye.models.plugins.openai.provider import OpenAIProvider
from skye.models.cost import CostCalculator, check_pricing, usage_of
from skye.models.utilities.rest import wrap
from skye.models.token_counter import TokenCounter


class _Body(io.BytesIO):
    status = 200

    def __enter__(self) -> _Body:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _chat(
    prompt: int, completion: int, model: str = "gpt-4", content: str = "hi"
) -> dict[str, Any]:
    return {
        "id": "c1",
        "object": "chat.completion",
        "created": 1700000000,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
        },
    }


def _complete(reply: dict[str, Any], model: str = "gpt-4", **config: Any) -> Any:
    client = OpenAIProvider(api_key="k", **config)
    with patch("urllib.request.urlopen", lambda req, timeout=0: _Body(json.dumps(reply).encode())):
        return client.complete("hello there", model=model)


# --- the cost of a response ---


def test_the_cost_is_split_in_prompt_and_completion_and_uses_the_providers_count() -> None:
    response = _complete(_chat(1000, 500))
    cost = response.metadata["cost"]
    assert cost["currency"] == "USD" and cost["exact"] is True
    assert cost["prompt"] == pytest.approx(0.03) and cost["completion"] == pytest.approx(0.03)
    assert cost["total"] == pytest.approx(0.06)
    assert response.usage.prompt_tokens == 1000 and "usage_estimated" not in response.metadata


def test_a_dated_model_name_finds_the_price_of_its_family() -> None:
    cost = _complete(_chat(1000, 0, model="gpt-4-0613"), model="gpt-4-0613").metadata["cost"]
    assert cost is not None and cost["prompt"] == pytest.approx(0.03)


def test_a_model_with_no_price_has_no_cost_not_a_free_one() -> None:
    assert _complete(_chat(10, 10, model="mystery"), model="mystery").metadata["cost"] is None


def test_pricing_of_the_client_prices_the_calls_with_your_numbers() -> None:
    response = _complete(
        _chat(1_000_000, 2_000_000, model="mystery"),
        model="mystery",
        pricing={"prompt": 1, "completion": 4},
    )
    cost = response.metadata["cost"]
    assert (cost["prompt"], cost["completion"], cost["total"]) == (1.0, 8.0, 9.0)


@pytest.mark.parametrize(
    "bad",
    [
        {"prompt": 1},
        {"prompt": 1, "completion": -1},
        {"prompt": "1", "completion": 2},
        {"prompt": 1, "completion": 1, "x": 1},
        [1, 2],
    ],
)
def test_bad_pricing_is_a_validation_error(bad: Any) -> None:
    with pytest.raises(ValidationError):
        OpenAIProvider(api_key="k", pricing=bad)
    with pytest.raises(ValidationError):
        check_pricing(bad)


def test_when_the_provider_reports_no_tokens_they_are_estimated_and_marked() -> None:
    response = _complete(_chat(0, 0, content="a fairly long answer to estimate by length"))
    assert response.usage.prompt_tokens > 0 and response.usage.completion_tokens > 0
    assert (
        response.usage.total_tokens
        == response.usage.prompt_tokens + response.usage.completion_tokens
    )
    assert response.metadata["usage_estimated"] is True
    assert response.metadata["cost"]["exact"] is False


# --- the running counter of a stream ---


def _delta(text: str | None, finish: str | None = None) -> Any:
    delta = {} if text is None else {"content": text}
    return wrap({"id": "s", "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]})


def _stream(events: list[Any], model: str = "gpt-4", **config: Any) -> list[StreamChunk]:
    client = OpenAIProvider(api_key="k", **config)
    client._call_provider_stream = lambda request: iter(events)  # type: ignore[method-assign]
    return list(client.stream("tell me something", model=model))


def test_every_chunk_carries_the_counter_and_a_free_chunk_repeats_the_one_before() -> None:
    usage_chunk = wrap(
        {
            "id": "s",
            "choices": [],
            "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
        }
    )
    chunks = _stream(
        [_delta(None), _delta("Hello wor"), _delta("ld, again"), _delta(None, "stop"), usage_chunk]
    )

    assert all(c.usage is not None and c.cost is not None for c in chunks)
    first, hello, again, stop, final = chunks
    # the first chunk costs nothing yet: the prompt is counted, the completion is 0
    assert first.usage.completion_tokens == 0 and first.usage.prompt_tokens > 0
    # a chunk with text moves the counter; the estimate never goes down while the text grows
    assert (
        hello.usage.completion_tokens >= 1
        and again.usage.completion_tokens >= hello.usage.completion_tokens
    )
    assert first.cost["exact"] is False and again.cost["exact"] is False
    # a chunk with no text repeats the value of the one before it
    assert stop.usage == again.usage and stop.cost == again.cost
    # the provider's count replaces the estimate, and the cost is then exact
    assert (final.usage.prompt_tokens, final.usage.completion_tokens, final.usage.total_tokens) == (
        7,
        3,
        10,
    )
    assert final.cost["exact"] is True
    assert final.cost["prompt"] == pytest.approx(7 / 1e6 * 30) and final.cost[
        "completion"
    ] == pytest.approx(3 / 1e6 * 60)


def test_the_chunks_do_not_share_their_counter() -> None:
    chunks = _stream([_delta(None), _delta(None, "stop")])
    chunks[0].usage.prompt_tokens = 999  # type: ignore[union-attr]
    chunks[0].cost["total"] = 1.0  # type: ignore[index]
    assert chunks[1].usage.prompt_tokens != 999 and chunks[1].cost["total"] != 1.0  # type: ignore[union-attr,index]


def test_a_model_with_no_price_still_counts_tokens_and_has_no_cost() -> None:
    chunks = _stream([_delta("some words here")], model="mystery")
    assert chunks[0].usage.completion_tokens > 0 and chunks[0].cost is None  # type: ignore[union-attr]


def test_pricing_of_the_client_applies_to_the_stream() -> None:
    chunks = _stream(
        [_delta("hello world, hello")],
        model="mystery",
        pricing={"prompt": 1_000_000, "completion": 1_000_000},
    )
    usage, cost = chunks[0].usage, chunks[0].cost
    assert cost["total"] == pytest.approx(usage.total_tokens)  # type: ignore[union-attr,index]


def test_only_the_official_openai_client_asks_for_the_usage_of_a_stream() -> None:
    assert OpenAIProvider.streams_usage is True and AzureOpenAIProvider.streams_usage is False
    sent: list[dict[str, Any]] = []

    def capture(url: str, body: dict[str, Any], **kwargs: Any) -> Any:
        sent.append(body)
        return iter(())

    client = skye.provider("openai", api_key="k")
    with patch("skye.models.utilities.openai_compatible.provider.rest.stream_sse_json", capture):
        list(client.stream("hi", model="gpt-4"))
    assert sent[0]["stream_options"] == {"include_usage": True}


# --- what each adapter reads from its stream ---


def test_anthropic_gives_the_prompt_at_the_start_and_the_running_output_at_the_end() -> None:
    client = skye.provider("anthropic", api_key="k")
    start = client._transform_stream_chunk(
        wrap(
            {
                "type": "message_start",
                "message": {"usage": {"input_tokens": 25, "output_tokens": 1}},
            }
        )
    )
    assert (start.usage.prompt_tokens, start.usage.completion_tokens) == (25, 0)  # type: ignore[union-attr]
    text = client._transform_stream_chunk(
        wrap(
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "Hi"},
            }
        )
    )
    assert text.usage is None
    end = client._transform_stream_chunk(
        wrap(
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn"},
                "usage": {"output_tokens": 15},
            }
        )
    )
    assert (
        end.usage is not None
        and end.usage.completion_tokens == 15
        and end.finish_reason == "end_turn"
    )


def test_bedrock_reads_the_usage_of_the_metadata_event() -> None:
    client = skye.provider(
        "bedrock", region_name="us-east-1", aws_access_key_id="a", aws_secret_access_key="b"
    )
    chunk = client._transform_stream_chunk(
        wrap(
            {
                "metadata": {
                    "usage": {"inputTokens": 5, "outputTokens": 6, "totalTokens": 11},
                    "metrics": {},
                }
            }
        )
    )
    assert (chunk.usage.prompt_tokens, chunk.usage.completion_tokens, chunk.usage.total_tokens) == (
        5,
        6,
        11,
    )  # type: ignore[union-attr]
    assert (
        client._transform_stream_chunk(wrap({"contentBlockDelta": {"delta": {"text": "x"}}})).usage
        is None
    )


def test_google_reads_the_running_usage_metadata() -> None:
    client = skye.provider("google", project_id="p", location="us-central1", credentials="token")
    chunk = client._transform_stream_chunk(
        wrap(
            {
                "candidates": [{"content": {"parts": [{"text": "Hi"}]}}],
                "usageMetadata": {
                    "promptTokenCount": 4,
                    "candidatesTokenCount": 2,
                    "totalTokenCount": 6,
                },
            }
        )
    )
    assert chunk.delta == "Hi" and (chunk.usage.prompt_tokens, chunk.usage.completion_tokens) == (
        4,
        2,
    )  # type: ignore[union-attr]
    assert (
        client._transform_stream_chunk(
            wrap({"candidates": [{"content": {"parts": [{"text": "x"}]}}]})
        ).usage
        is None
    )


def test_usage_of_ignores_what_a_provider_did_not_say() -> None:
    assert usage_of(None, None) is None and usage_of(0, 0) is None and usage_of(-1, "3") is None
    assert usage_of(4, None) == TokenUsage(prompt_tokens=4, completion_tokens=0, total_tokens=4)
    assert usage_of(4, 2, 9).total_tokens == 9  # type: ignore[union-attr]


def test_breakdown_and_pricing_for() -> None:
    usage = TokenUsage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
    assert CostCalculator.breakdown("nope", usage) is None
    assert (
        CostCalculator.breakdown("nope", usage, {"prompt": 2.0, "completion": 4.0}, exact=False)[
            "exact"
        ]
        is False
    )  # type: ignore[index]
    assert CostCalculator.pricing_for("claude-3-opus-20240229") == CostCalculator.get_pricing(
        "claude-3-opus"
    )
    assert CostCalculator.pricing_for("gpt-4-turbo-2024-04-09") == CostCalculator.get_pricing(
        "gpt-4-turbo"
    )
    # another model that starts with a known name is not priced at the shorter name's price
    assert CostCalculator.get_pricing("gpt-4o") is None
    assert CostCalculator.pricing_for("gpt-4o-2024-08-06") is None
    assert CostCalculator.pricing_for("gpt-4o") is None
    assert CostCalculator.pricing_for("gpt-4-vision-preview") is None


# --- tokenizers of your own ---


class _Words:
    def encode(self, text: str) -> list[str]:
        return text.split()


class _Chars:
    def encode(self, text: str) -> list[str]:
        return list(text)


@pytest.fixture(autouse=True)
def _clean_registry() -> Any:
    before = dict(TokenCounter._registered)
    yield
    for name in set(TokenCounter._registered) - set(before):
        TokenCounter.unregister_tokenizer(name)


def test_a_registered_tokenizer_wins_for_its_model_and_its_prefix() -> None:
    TokenCounter.register_tokenizer("claude-", _Words())
    assert TokenCounter.count_tokens("one two three", "claude-3-opus") == 3
    assert TokenCounter.count_tokens("one two three", "gpt-4") != 0  # another model is not affected
    TokenCounter.register_tokenizer("claude-3-opus", _Chars())  # the longest match wins
    assert TokenCounter.count_tokens("abc", "claude-3-opus") == 3
    assert TokenCounter.count_tokens("one two three", "claude-3-haiku") == 3


def test_a_registered_tokenizer_is_used_for_the_prompt_and_the_stream_estimate() -> None:
    TokenCounter.register_tokenizer("gpt-4", _Words())
    chunks = _stream([_delta("one two three four")])
    assert chunks[0].usage.completion_tokens == 4  # type: ignore[union-attr]
    assert (
        chunks[0].usage.prompt_tokens == 3 + 3
    )  # "tell me something", plus the 3 tokens of per-message overhead


def test_unregister_and_validation() -> None:
    TokenCounter.register_tokenizer("m", _Words())
    assert (
        TokenCounter.unregister_tokenizer("m") is True
        and TokenCounter.unregister_tokenizer("m") is False
    )
    for model, tokenizer in (("", _Words()), ("m", object()), ("m", None)):
        with pytest.raises(ValidationError):
            TokenCounter.register_tokenizer(model, tokenizer)


def test_an_empty_text_counts_zero_tokens() -> None:
    assert (
        TokenCounter.count_tokens("", "gpt-4") == 0
        and TokenCounter.count_tokens("", "some-model") == 0
    )


# --- the prices come from the profiles (plugins:6.1, Requirements 60.1, 59.3, 59.10) ---


@pytest.fixture
def private_registrar(monkeypatch):
    """A default registrar of its own, so a registration here does not reach the other tests."""
    import skye.base.plugins as plugins

    fresh = plugins.Registrar()
    monkeypatch.setattr(plugins, "_default", fresh)
    return fresh


def test_the_cost_calculator_holds_no_price_table() -> None:
    assert not hasattr(CostCalculator, "PRICING")


def test_a_third_party_profile_is_priced_with_no_edit_of_the_calculator(private_registrar) -> None:
    from skye.base.profile import ModelProfile, ProviderProfile

    private_registrar.provider(
        "acme",
        object,
        profile=ProviderProfile(
            "acme", models={"acme-large": ModelProfile(prompt_price=2.0, completion_price=8.0)}
        ), function="model",
    )
    assert CostCalculator.get_pricing("acme-large") == {"prompt": 2.0, "completion": 8.0}
    assert CostCalculator.pricing_for("acme-large-2025-01-31") == {"prompt": 2.0, "completion": 8.0}
    assert "acme-large" in CostCalculator.list_models()
    usage = TokenUsage(prompt_tokens=1_000_000, completion_tokens=500_000, total_tokens=1_500_000)
    assert CostCalculator.calculate_cost("acme-large", usage) == pytest.approx(6.0)


def test_the_user_layer_wins_over_a_profile(private_registrar) -> None:
    from skye.base.profile import ModelProfile, ProviderProfile

    private_registrar.provider(
        "acme",
        object,
        profile=ProviderProfile(
            "acme", models={"acme-win": ModelProfile(prompt_price=2.0, completion_price=8.0)}
        ), function="model",
    )
    try:
        CostCalculator.add_custom_pricing("acme-win", 1.0, 3.0)
        assert CostCalculator.get_pricing("acme-win") == {"prompt": 1.0, "completion": 3.0}
        assert CostCalculator.pricing_for("acme-win-2025-01-31") == {
            "prompt": 1.0,
            "completion": 3.0,
        }
        assert CostCalculator.list_models().count("acme-win") == 1
    finally:
        CostCalculator._custom.pop("acme-win", None)
    assert CostCalculator.get_pricing("acme-win") == {"prompt": 2.0, "completion": 8.0}


def test_a_model_with_an_unknown_price_or_no_profile_has_no_cost(private_registrar) -> None:
    from skye.base.profile import ModelProfile, ProviderProfile

    private_registrar.provider(
        "acme",
        object,
        profile=ProviderProfile(
            "acme", models={"half": ModelProfile(prompt_price=1.0), "free": ModelProfile(0.0, 0.0)}
        ), function="model",
    )
    usage = TokenUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20)
    assert CostCalculator.get_pricing("half") is None
    assert CostCalculator.breakdown("half", usage) is None
    assert "half" not in CostCalculator.list_models()
    assert CostCalculator.get_pricing("free") == {
        "prompt": 0.0,
        "completion": 0.0,
    }  # free is a price; unknown is not
    assert CostCalculator.get_pricing("no-profile-at-all") is None
    assert CostCalculator.calculate_cost("no-profile-at-all", usage) == 0.0


def test_the_longest_name_across_profiles_wins(private_registrar) -> None:
    from skye.base.profile import ModelProfile, ProviderProfile

    private_registrar.provider(
        "short", object, profile=ProviderProfile("short", models={"zz": ModelProfile(1.0, 1.0)}), function="model"
    )
    private_registrar.provider(
        "long", object, profile=ProviderProfile("long", models={"zz-pro": ModelProfile(9.0, 9.0)}), function="model"
    )
    assert CostCalculator.pricing_for("zz-pro-2025-01-01") == {"prompt": 9.0, "completion": 9.0}
    assert CostCalculator.pricing_for("zz-2025-01-01") == {"prompt": 1.0, "completion": 1.0}
    assert CostCalculator.pricing_for("zz-pro") == {"prompt": 9.0, "completion": 9.0}
