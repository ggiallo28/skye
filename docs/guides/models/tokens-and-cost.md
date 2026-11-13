---
title: "Tokens and cost"
status: current
---

# Tokens and cost

This guide shows you how to read the tokens a call used, count tokens before a call, and turn token counts into an estimated
price in US dollars.

## What you need

- A client from `skye.provider(...)`: see [Call a provider](call-a-provider.md).
- Optional: exact token counts for OpenAI models need `tiktoken`, from the `tokens` extra. Without it Skye estimates.

=== "pip"

    ```bash
    pip install skyeai[tokens]
    ```

=== "uv"

    ```bash
    uv add "skyeai[tokens]"
    ```

## Tokens of a call

Every `CompleteResponse` has `usage`, a `TokenUsage` with the counts the provider reported:

| Field | Meaning |
|---|---|
| `prompt_tokens` | tokens of the input: messages, system text, tools, images |
| `completion_tokens` | tokens of the answer |
| `total_tokens` | the sum |

Skye uses the provider's count as it is. Only when a provider reports none are the tokens estimated from the text: then
`response.usage` holds the estimate and `response.metadata["usage_estimated"]` is `True`.

A stream carries a running count on every chunk. See [Tokens and cost while it streams](#tokens-and-cost-while-it-streams).

## Count tokens before a call

`TokenCounter` (from `skye.models`) counts the tokens of a text, or of a list of messages with the few tokens each message adds for
its formatting. Use it to check that a prompt fits the context window, or to estimate a cost before you send it:

```python
--8<-- "examples/models/token_counting.py:13:35"
```

How exact the count is depends on the model name:

| Model name starts with | Count |
|---|---|
| a model whose profile names a tokenizer you added with `@plugins.tokenizer` | your tokenizer |
| a name you registered with `TokenCounter.register_tokenizer` | your tokenizer (the longest registered name wins) |
| `gpt-`, `o1-`, `o3-` | exact with `tiktoken` installed (the `tokens` extra); estimated without it |
| `claude-` | estimated |
| anything else | estimated |

The estimate is one token for every four characters, and an empty text counts zero. It is close for English prose and can be far off for code, numbers or other
languages: treat it as a budget, not a bill. Without `tiktoken`, Skye logs that the library is missing (once per model name) and uses the estimate.

### A tokenizer of your own

To count better than the estimate for a model, bring any object that has an `encode(text)` method (a `tiktoken` encoding, a `tokenizers`
or `transformers` tokenizer behind a small wrapper). Nothing is installed by Skye: you bring the tokenizer, and it costs no space when
you do not. As a plugin, a tokenizer is a function with the decorator `@plugins.tokenizer("name")` that receives the model and returns that
object; the profile of the model says which one it uses, and `plugins.profile(provider, models=...)` changes only that, leaving the
prices and the endpoint as they are:

```python
--8<-- "examples/plugins/tokenizer.py:16:35"
```

To count every model that starts with a name, without a profile, register the object by that name:

```python
from skye.models import TokenCounter

TokenCounter.register_tokenizer("claude-", my_tokenizer)  # every Claude model
TokenCounter.register_tokenizer("claude-3-opus", other)    # the longest name wins
TokenCounter.unregister_tokenizer("claude-")
```

It is used wherever Skye estimates: before a call, for a response with no provider count, and for the running count of a stream.

## The cost of a call

Every response carries its cost in `response.metadata["cost"]`, split in what you sent and what the model wrote, priced with the
provider's token count:

```python
response = client.complete("Hello", model="gpt-4")
response.metadata["cost"]
# {"prompt": 0.0003, "completion": 0.0006, "total": 0.0009, "currency": "USD", "exact": True}
```

`exact` is `False` when the tokens were estimated. A model with no price has `cost` `None`: Skye does not guess that a call is
free. Give your own prices, in USD per million tokens, when you create the client; they win over the table:

```python
client = skye.provider("openai", pricing={"prompt": 2.5, "completion": 10.0})
```

The model name is the one you asked for, or the one the provider reports. A dated or versioned name finds the price of its family
(`gpt-4-0613`, `claude-3-opus-20240229`). A different model that only starts with a known name (`gpt-4o` against `gpt-4`) has no
price until you add one.

## Tokens and cost while it streams

Every `StreamChunk` has `usage` and `cost`: a running count of the whole call, so the last value you saw is the total so far.
A chunk with text moves it. A chunk with none repeats the value of the one before, so the count never goes back to `None`.

| When | The count |
|---|---|
| before the first text | the prompt tokens, estimated from your messages; the completion is 0 |
| while text arrives | the prompt, and the completion estimated from the text received so far |
| when the provider reports its count | the provider's count; `cost["exact"]` is `True` once it has both |

OpenAI sends its count after the last text, and Skye asks for it on the OpenAI client (`stream_options.include_usage`); Bedrock
sends it in its last event, Anthropic reports the prompt at the start and the output at the end, and Gemini reports it along the
way. On an OpenAI-compatible endpoint other than OpenAI the count stays an estimate, because the endpoint may reject the option.
The estimate can differ from the provider's count, so the total can move a little when the count arrives. `astream` carries the
same counter.

## Estimate the cost with `CostCalculator`

`CostCalculator` (from `skye.models`) multiplies a `TokenUsage` by a price per million tokens. It has a table of prices for common
OpenAI, Anthropic, Bedrock and Gemini models, and you add your own:

```python
--8<-- "examples/models/cost_tracking.py:13:47"
```

| Method | What it does |
|---|---|
| `calculate_cost(model, usage, custom_pricing=None)` | the cost in USD; `0.0` for a model with no price |
| `breakdown(model, usage, custom_pricing=None, exact=True)` | the cost split in `prompt`, `completion` and `total`, or `None` for a model with no price |
| `pricing_for(model)` | the price of a model, also by a dated name; `None` when there is none |
| `get_pricing(model)` | `{"prompt": ..., "completion": ...}` per million tokens, or `None` |
| `add_custom_pricing(model, prompt_price, completion_price)` | sets the price of a model for this process |
| `list_models()` | the models with a price |

!!! warning
    The built-in prices are the list prices of November 2024, not updated since. `calculate_cost` returns `0.0` for a model
    missing from the table, without an error; `breakdown` and `response.metadata["cost"]` say `None` instead. Check
    `pricing_for(model)` for the models you use, and set the current price with `pricing=` on the client,
    `add_custom_pricing` or `custom_pricing={"prompt": ..., "completion": ...}`.

## Cost of a router

A router's targets can carry their own prices, `cost_per_1k_prompt_tokens` and `cost_per_1k_completion_tokens`, which the
`cost_based` strategy reads to choose the cheapest target. See [Strategies](../routing/strategies.md). To price an answer after the
call, read the model that served it from `router.last_serving["model"]` and pass it with `response.usage` to `CostCalculator`.

## See also

- [Streaming and async](streaming.md): the chunks that carry the running count.
- [Extras](../../reference/extras.md): what the `tokens` extra installs.
- [`skye.models` API reference](../../reference/api/models.md): `TokenCounter`, `CostCalculator`.
- Examples: [`models/token_counting.py`](https://github.com/ggiallo28/skye/blob/main/examples/models/token_counting.py),
  [`models/cost_tracking.py`](https://github.com/ggiallo28/skye/blob/main/examples/models/cost_tracking.py).
