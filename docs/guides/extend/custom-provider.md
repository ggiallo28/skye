---
title: "Custom provider"
status: current
---

# Custom provider

This guide shows you how to write a provider adapter for a model API that Skye does not cover, add it as a plugin under a name, and use
it like the built-in ones.

## Before you start

You may not need an adapter:

- **An OpenAI-compatible server** (vLLM, Ollama, LM Studio, a gateway): use the OpenAI provider with its address,
  `skye.provider("openai", api_key="...", api_base="http://localhost:8000/v1")`.
- **A function or an SDK you only want to call**: wrap it as a `Runnable`, which is lighter. See
  [`bring_your_own_adapter.py`](https://github.com/ggiallo28/skye/blob/main/examples/providers/bring_your_own_adapter.py).

Write an adapter when you want the full client: `complete`, `stream`, the async forms, capabilities, structured output, retries,
health counters and routing.

## How an adapter works

`BaseModelProvider` in [`skye.models`](../../reference/api/models.md) keeps what is common to every provider. Your subclass only
translates: Skye types to the wire format of the service, and back. All the provider-specific logic stays in your class; nothing else
in Skye changes.

```mermaid
flowchart LR
    req["CompleteRequest"] --> tr["_transform_request<br/>(_transform_messages, _transform_capabilities)"]
    tr --> call["_acall_provider"]
    call --> resp["_transform_response<br/>(_extract_capability_calls)"]
    resp --> out["CompleteResponse"]
```

## 1. Subclass `BaseModelProvider`

Implement the eleven abstract methods. The two calls are `async`: you write only the async side, and Skye derives `complete` and `stream`
from `acomplete` and `astream`. This toy provider answers by shouting the last message; the "service" is a local function, so
nothing leaves the process. The decorator `@plugins.provider("shout")` on the class is what adds it (step 3).

```python
--8<-- "examples/advanced/custom_providers.py:10:70"
```

What each method does:

| Method | Turns | Into |
|---|---|---|
| `_initialize_client()` | nothing | the client of the service, created on first use (`self.client`); return `None` for plain HTTP |
| `_transform_messages(messages)` | Skye messages | the message list of the service (roles, system text, images, tool results) |
| `_transform_capabilities(capabilities)` | capabilities (`get_schema()` of each) | the tool definitions of the service |
| `_transform_request(request)` | a `CompleteRequest` | the request body of the service |
| `async _acall_provider(request)` | the request body | the raw answer |
| `async _acall_provider_stream(request)` | the request body | an async generator of raw chunks |
| `_transform_response(response)` | the raw answer | a `CompleteResponse` (content, finish reason, `TokenUsage`, `capability_calls`) |
| `_transform_stream_chunk(chunk)` | a raw chunk | a `StreamChunk` |
| `_extract_capability_calls(response)` | the raw answer | a list of `CapabilityCall` (`skye.completion`), or `None` |
| `format_capability_results(results)` | capability results | the messages the service expects for them |
| `get_model_info()` | nothing | a dictionary describing the model (see below) |

The keyword arguments given to `skye.provider(name, **config)` arrive in your constructor and are kept in `self.config`. Read keys and
endpoints from there, and import an SDK only inside `_initialize_client`, so importing your module stays cheap. A blocking call
(an SDK, `urllib`) goes behind `await asyncio.to_thread(...)` in `_acall_provider`, so it does not hold the event loop.

## 2. Describe the model

`get_model_info()` tells Skye what the model can do. The keys it reads:

| Key | Effect |
|---|---|
| `provider` | the provider name in errors |
| `supports_system_messages` | `False` puts the system text of a rendered prompt in the first user message (default `True`) |
| `supports_structured_output`, `supports_function_calling` | either one lets an output schema travel natively; without both, the schema is written as instructions in the prompt |
| `supports_streaming` | whether `stream` makes sense for this model |

## 3. Add it and use it

You create the handle once, `plugins = skye.Plugins()`, and put the decorator on the class (the two lines are in the code above):

```python
plugins = skye.Plugins()


@plugins.provider("shout")
class ShoutProvider(BaseModelProvider): ...
```

What you add is there as soon as the decorator runs. `skye.provider(name, **config)` then builds it, as it builds `"openai"`, and a
router can balance it with the others (`"shout/shout-1"` in a route):

```python
--8<-- "examples/advanced/custom_providers.py:73:76"
```

The decorator needs no other call. Without it, `plugins.provider("shout", ShoutProvider)` does the same, and a name that is already
taken raises `ConfigurationError` unless you pass `replace=True`. `plugins.names("provider")` lists what is registered.

`@plugins.provider` is the one decorator for the three kinds of provider. Skye reads the kind from the class: a model provider (this
guide), an embedding provider (`aencode`, see [Embeddings](../models/embeddings.md#an-embedding-provider-of-your-own)) or a decision
model (`decide`). When one class could be two, say which with `function="model"`, `"embedding"` or `"decision"`.

Pass `profile=` when the provider has a key variable, an endpoint, prices or its own tokenizer: that knowledge lives in the
`ProviderProfile`, not in the adapter. The example
[`model_provider.py`](https://github.com/ggiallo28/skye/blob/main/examples/plugins/model_provider.py) also shows how to ship the
provider as a package that `pip install` adds with no line of yours (an entry point of the group `skye.plugins`).

To check an adapter against the rules every provider keeps, run `check_provider` (`from skye.models import check_provider`), as the built-in
providers do in the test suite.

## What you get for free

- **Entry points**: `complete`, `stream`, `acomplete` and `astream`. You write the async side; `complete` and `stream` are derived from
  `acomplete` and `astream`, so there is no second path to keep in step. A sync call made from inside a running event loop (a
  notebook, a server) works, on a loop of its own in a worker thread; from async code prefer `acomplete` and `astream`.
- **Retries** (decision D104): a `RateLimitError`, `ServerError` or `ProviderTimeoutError` raised by the transform or the call is
  retried up to `max_retries` times (3 by default, `0` turns them off), with exponential backoff (1, 2, 4 ... seconds, at most 20)
  or the error's `retry_after`; a stream only before its first chunk. Any other `ProviderError` is raised at once, unchanged. Any
  other exception is wrapped in a `ProviderError` (a `ProviderTimeoutError` for a timeout or a dropped connection). A
  `ValidationError` (bad input) is not retried. Raise the subclass that matches the failure, so the client and the router read it.
- **HTTP**: `skye.models.post_json(url, body, headers=..., authenticator=..., provider=...)` and `skye.models.stream_sse_json` are
  the standard-library transport of the built-in adapters; they return the decoded JSON (`JsonObject`, attribute access) and raise
  the `ProviderError` subclass of the response. `authenticator` takes any authenticator of `skye.auth` (SigV4, Entra ID, Google).
- **Structured output**: when the request has a `response_schema`, the text of the answer is validated against it once, for every
  provider; a mismatch raises `ValidationError`.
- **Capabilities**: the capabilities of the request are attached to the response, so `response.execute_capability_calls()` works.
- **Health**: success, failure and latency counters (`get_health_metrics()`), which the router reads.

## See also

- [Call a provider](../models/call-a-provider.md): how the built-in providers are used.
- [Which Port to implement](index.md): `ModelInterface` and `VectorEncoderInterface` are the Ports behind the base classes.
- Reference: [`skye.models`](../../reference/api/models.md), [`skye.plugins`](../../reference/api/plugins.md).
- Example: [`custom_providers.py`](https://github.com/ggiallo28/skye/blob/main/examples/advanced/custom_providers.py).
