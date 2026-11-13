---
title: "Streaming and async"
status: current
---

# Streaming and async

This guide shows you how to print an answer as the model writes it, with `stream` and `astream`, and how to call a model from async
code with `acomplete`.

## What you need

- A client from `skye.provider(...)`: see [Call a provider](call-a-provider.md). Every built-in model provider streams.

## The four methods

| Method | Returns | Use it |
|---|---|---|
| `complete(...)` | a `CompleteResponse` | plain code, one whole answer |
| `acomplete(...)` | an awaitable `CompleteResponse` | async code, one whole answer |
| `stream(...)` | an iterator of `StreamChunk` | plain code, the answer piece by piece |
| `astream(...)` | an async iterator of `StreamChunk` | async code, the answer piece by piece |

They take the same arguments: `messages`, `model`, `temperature`, `max_tokens` and the other options of a call, or one
`CompleteRequest`.

## Stream an answer

`stream` yields `StreamChunk` objects. Each chunk has `delta`, the new text, and `index`, its position; the last chunk has a
`finish_reason`. This example prints the text as it arrives, counts the chunks and measures the time to the first token, then
does the same with `astream`:

```python
--8<-- "examples/advanced/streaming.py:9:49"
```

The `_offline` lines pick a scripted client when `OPENAI_API_KEY` is not set, so the example runs without a network.

Under the hood each adapter reads the provider's own stream format: server-sent events for OpenAI, Azure OpenAI, Anthropic and
Google, and the AWS event stream of `converse-stream` for Bedrock.

What a stream does not give you:

- token usage: a `StreamChunk` has no `usage`. Count the tokens with [TokenCounter](tokens-and-cost.md) when you need them, or use
  `complete`;
- structured output: ask for a schema with `complete`, which validates the whole answer (see [Structured output](structured-output.md));
- a retry after the first chunk: like `complete`, a stream is tried again on a rate limit, a server error or a timeout, but only
  before its first chunk (see [Errors and retries](call-a-provider.md#errors-and-retries)). A stream that fails halfway raises the
  `ProviderError` subclass of the failure, and you decide whether to ask again: the text you already printed cannot be taken back.

## Tokens and cost while it streams

Every chunk carries `chunk.usage` (prompt and completion tokens) and `chunk.cost`: a running count of the whole call, so the
last value you saw is the total so far. A chunk with text moves it; a chunk with none repeats the one before. The count is an
estimate until the provider reports its own (`chunk.cost["exact"]` becomes `True`). See
[Tokens and cost](tokens-and-cost.md#tokens-and-cost-while-it-streams).

## Call a model from async code

`acomplete` is the async form of `complete`, and it is the form that holds the code: `complete` runs it for you. The built-in clients do
the blocking part of the request in a worker thread, so the loop keeps serving other tasks while the request is in flight:

```python
--8<-- "examples/basic/async_and_streaming.py:20:38"
```

To send several requests at once, gather them:

```python
import asyncio

from skye import UserMessage


async def ask_all(client, questions: list[str]) -> list[str]:
    calls = [client.acomplete(messages=[UserMessage(content=q)], model="gpt-4o-mini") for q in questions]
    return [response.content for response in await asyncio.gather(*calls)]
```

`astream` does not block the event loop either: the blocking read of the provider's stream runs in a worker thread, and each chunk is handed to your
`async for`, so other tasks run between two chunks. `stream` is derived from it the same way `complete` is derived from `acomplete`. Nothing is left running when the loop ends: if you stop early
(`break`), the worker stops at the next chunk and `astream` waits for it before closing.

## A router

`ModelRouter` has `complete` and `acomplete`, with the same fallback and health tracking in both. It has no `stream`: to stream
through a router, pick the model with the router and stream from the client. See [Aliases and fallbacks](../routing/aliases-and-fallbacks.md).

## See also

- [First model call](../../get-started/first-call.md).
- [`skye` API reference](../../reference/api/skye.md): `StreamChunk`, `CompleteRequest`, `CompleteResponse`.
- [`skye.models` API reference](../../reference/api/models.md).
- Examples: [`advanced/streaming.py`](https://github.com/ggiallo28/skye/blob/main/examples/advanced/streaming.py),
  [`basic/async_and_streaming.py`](https://github.com/ggiallo28/skye/blob/main/examples/basic/async_and_streaming.py).
