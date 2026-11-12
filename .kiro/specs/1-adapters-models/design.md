Builds on: #[[file:.kiro/steering/11-design.md]] (sections: Transport and providers, DecisionModel (Jev), Extension points, Public API and lazy imports, Extras and budgets)

# Design Document: models

## Overview

`models` is the adapters layer-1 component (codename zephyr). It holds the adapters for language, embedding and decision
models behind the Ports in `base`, over one shared standard-library transport. There is exactly one implementation per
provider, a thin REST adapter; no vendor SDK is shipped or on the runtime path (Requirement 9.3, D13). The SDKs are
development-only differential oracles (Requirement 9.4, D14). This document describes only the internals of `models`; the
layer, the allowed imports (`base`, `auth`), the Ports and the extras policy are in the steering sections named above and are
not restated here.

Ports implemented by this component: `model`, `decision`, `vector_encoder`, `registry`, `cost_calculator`,
`error_handler`, `token_counter` and `runnable`. Credentials are obtained through `auth` (the authentication Port), never
read here (Requirement 11).

## Architecture

`models` sits in layer 1 (adapters) and may import only `base` and `auth` (design "Layers", enforced by the import matrix). The
shape is: one shared transport does all network I/O and streaming; one template-method base holds retry, error wrapping, health
and the `Runnable` entry point; one thin REST adapter per provider implements only the provider-specific transformation; a
registry maps names to adapter classes behind the registry Port. The detailed internals follow.

## Package layout

```
models/
  base.py                 BaseModelProvider, BaseEmbeddingProvider (template method, retry, health, Runnable.invoke)
  registry.py             ProviderRegistry + provider() factory; implements the registry Port
  lazy_import.py          LazyImporter: first-use import, MissingExtraError on absence
  llm/
    openai_compatible.py  OpenAICompatibleProvider (the OpenAI wire format, keyed by base URL + key)
    openai.py             OpenAIProvider (OpenAI's endpoint, organization header, fingerprint)
    azure.py              AzureOpenAIProvider (endpoint, api version, deployment)
    anthropic_compatible.py  AnthropicCompatibleProvider (Messages wire format, keyed by base URL + key)
    anthropic.py          AnthropicProvider (Anthropic endpoint and label)
    bedrock.py            BedrockProvider (Converse + Converse stream, SigV4 via auth; boto3 not required)
    google.py             GoogleProvider (Google dialect)
  embeddings/
    openai_embeddings.py  OpenAIEmbeddingProvider
    bedrock_embeddings.py BedrockEmbeddingProvider (Titan)
    cohere_embeddings.py  CohereEmbeddingProvider
    google_embeddings.py  GoogleEmbeddingProvider
    google_multimodal_embeddings.py  GoogleMultimodalEmbeddingProvider
  transport/
    http.py               thin wrapper over base/http.py
    rest.py               post_json / stream_sse_json; JsonObject read-only view over decoded JSON
    streaming.py          stdlib text/event-stream (SSE) parsing
    eventstream.py        stdlib application/vnd.amazon.eventstream framing (Bedrock streams)
    retry.py              with_retry decorator (3 retries after the first attempt)
    error_mapping.py      HTTP status / payload -> SkyeError hierarchy by category
    token_counter.py      stdlib approximate counter; lazy tiktoken for exact counts
    cost.py               CostCalculator, pricing table, custom pricing
    multimodal.py         ImageHandler: URL / data URL / path / bytes -> provider shape
```

## Shared transport

All network I/O goes through one place. `transport/rest.py` builds a JSON request and calls `transport/http.py`, which is a
thin wrapper over the single network module `base/http.py` (the one I/O module allowed in `base`). `rest.post_json` returns a
`JsonObject`, a read-only attribute view over decoded JSON, so response transformers read `response.choices[0].message.content`
without a vendor SDK type. No adapter opens its own socket or imports a third-party HTTP client (Requirement 9.1, 9.3; design
"Transport and providers").

Streaming has two stdlib decoders so every adapter reuses one path (Requirement 16.5):
- `transport/streaming.py` parses `text/event-stream` (SSE) used by OpenAI-compatible, Anthropic and Google; `rest.stream_sse_json`
  yields one `JsonObject` per event.
- `transport/eventstream.py` decodes the `application/vnd.amazon.eventstream` binary framing used by Bedrock Converse streams.

Authentication is never done here: adapters receive an `AuthenticationInterface` from `auth` and pass it to the transport,
which adds headers or signs the request. Bedrock reuses the SigV4 signer that lives in `auth` (design "Transport and
providers"; Requirement 11).

### Retry

`transport/retry.py` exposes the `with_retry` decorator used by `BaseModelProvider._complete_with_retry` and
`_stream_with_retry`: at most 3 retries after the first attempt on a transient error, then the failure is mapped and raised
(Requirement 9.2; design "Transport and providers"). Retries are internal and do not count as separate health failures.

### Error mapping

`transport/error_mapping.py` maps an HTTP status and payload to the `SkyeError` hierarchy by category (authentication,
rate-limit, validation, provider), wrapping the original and keeping its context. The base providers re-wrap any adapter
exception in `ProviderError` with provider name, original error and error type (Requirement 9.9, 18.1).

## Components and Interfaces

### Provider adapters (REST)

`base.py` holds `BaseModelProvider`, a template-method base: `complete`/`stream` accept either a `CompleteRequest` or
boto3-style arguments, delegate to the retried internals, and record health. Each concrete adapter implements the
provider-specific steps only — `_initialize_client`, `_transform_request`, `_transform_response`, `_transform_stream_chunk`,
`_transform_messages`, `_transform_capabilities`, `_extract_capability_calls`, `format_capability_results`,
`_call_provider`, `_call_provider_stream`. All provider-specific transformation of requests, messages and capabilities lives
inside the adapter; the router, tools and completion models stay provider-agnostic, and adding a provider changes nothing
outside its adapter (Requirement 9.5, 9.10, 6.1). Where an external shape exists it is converted once, at the adapter
boundary (Requirement 9.5).

Adapter families (design "Transport and providers"):
- `llm/openai_compatible.py` — `OpenAICompatibleProvider` is the family keyed by base URL and key; `openai.py` and `azure.py` hold only what is specific to OpenAI and to Azure. Together they cover
  OpenAI, Azure OpenAI and the OpenAI-compatible ecosystem.
- `llm/anthropic_compatible.py` — `AnthropicCompatibleProvider` (the Messages wire format, keyed by base URL and key) and `llm/anthropic.py` — `AnthropicProvider`, only the Anthropic endpoint and label, over the Messages API, with the system message carried separately.
- `llm/bedrock.py` — `BedrockProvider` over Converse and Converse stream, signed with SigV4 from `auth`; boto3 is not required.
- `llm/google.py` — `GoogleProvider`, the Google dialect (formerly "Vertex AI", renamed `google` per D19; Requirement 9.3).

Each adapter exposes `invoke` (the `Runnable` Port), which delegates to `acomplete`, so a model is a step in a flow or a team
member (design "Composition").

### Function calling and the OpenAI data shape

Adapters accept capabilities and messages in the OpenAI data shape and return library types, without mirroring, subclassing or
re-exporting any SDK class (Requirement 9.6). Capability calls are extracted by `_extract_capability_calls` into library
`CapabilityCall` objects and results are formatted back by `format_capability_results`; the term is "Capability", not "Tool"
(Requirement 22.1).

### Embeddings

`embeddings/` holds the REST adapters behind the `vector_encoder` Port: OpenAI, Bedrock (Titan), Cohere and Google, plus
Google multimodal. Each supports single and batch encoding and sync/async forms (`aencode`, `aencode_batch`), and reports its
vector dimension (Requirement 25.1–25.3). The Google multimodal adapter accepts image inputs through `transport/multimodal.py`
and returns vectors in the text-embedding shape; an adapter that does not support a modality rejects the input naming the
limitation (Requirement 25.4, 26.3).

### Multimodal inputs

`transport/multimodal.py` (`ImageHandler`) accepts a URL, a base64 data URL, a file path or raw bytes and converts to each
provider's documented shape at the adapter boundary; audio and video ride the same boundary; an unsupported modality raises a
`ProviderError` naming the modality (Requirement 26.1–26.3).

### Structured output

When a request declares an output shape, the adapter uses the provider's native structured-output mechanism where available
and otherwise function calling, then validates the result against the shape (Requirement 27.1). The declared shape is a
dataclass, not a pydantic model (Requirement 27.2, D24); a non-conforming result raises `ValidationError` naming the field.
Note: the current `base/completion.py` still types `response_schema`/`structured_output` as pydantic models; moving them to
dataclasses is open work tracked in tasks.md (D24, O4).

Decided (D81, 2026-11-09; nothing built yet): a rendered prompt is a set of provider-agnostic parts, a type of the `prompt` Port in
`base`, and the adapter translates it. Today `prompts` returns messages and appends the output instructions as text, while providers
take the system prompt, images and an output schema as separate API fields (Anthropic `system`, Gemini `systemInstruction` /
`responseSchema`, OpenAI `response_format: json_schema`, Bedrock Converse `system` and output configuration). The adapter chooses the native field or the text from the capabilities of the model,
which stay in `models` (D17, the import matrix), and `CompleteRequest.response_schema` may have to accept a JSON-Schema `dict`; table
and XML have no native form. The adapter design is task 11.

### Token counting and cost

`transport/token_counter.py` provides an approximate counter using only the standard library (~4 chars per token with a
per-model message overhead), present in the core install. Exact counts for OpenAI-family models use `tiktoken`, imported
lazily through `LazyImporter`; if the extra is absent the counter falls back to the approximation. `import skye` never imports
a tokenizer (Requirement 28.1–28.3, 19.1; D25). `transport/cost.py` (`CostCalculator`) estimates cost from a pricing table and
accepts custom pricing for private models (Requirement 19.2).

### Decision model (Jev)

The `decision` Port in `base/interfaces/decision.py` takes a finite option set and returns one choice with a probability per
option (each in 0..1, summing to 1; an empty set is rejected). The implementation, Jev, belongs at `models/plugins/typesafe/decision.py`
and is consumed by `gateway`, `router` and `guard` (design "DecisionModel (Jev)"; Requirement 9.8). It is built
(`models/plugins/typesafe/decision.py`, `JevDecisionModel`); its selector in the gateway moves with open decision O19 (D89).

### Lazy loading and packaging

`lazy_import.py` (`LazyImporter`) imports an optional library at first use and raises `MissingExtraError` naming the extra when
it is absent (design "Public API and lazy imports"). The top-level package re-exports only `messages`, `completion`,
`exceptions` and `config` from `base`, so `import skye` reaches no provider or optional library (Requirement 7.1, 7.3). The
`models` extra is empty — the REST adapters are standard library — except that `google` declares only its SDK, and exact token
counting declares only the `tiktoken` extra (design "Extras and budgets"; D25).

### Health and observability

`BaseModelProvider` records success, latency and failure in `HealthMetrics` on each final call (after retries), exposed for the
router's health tracking and for observability exporters through the observer Port (Requirement 17.2, 18.3).

## Data Models

`models` defines no new wire schema; it consumes and produces the `base` contracts (design "Base contracts"): a request is a
`CompleteRequest`, a response a `CompleteResponse` (content, role, metadata, token usage, model identifier, provider), a
stream yields `StreamChunk`; messages are the `SkyeMessage` role variants; a capability call is a library `CapabilityCall`. The
only `models`-local structure is `JsonObject` in `transport/rest.py`, a read-only attribute view over decoded provider JSON used
inside the adapter boundary and never exposed through a Port. New structures are dataclasses, not pydantic (Requirement 21.2,
D24); the declared structured-output shape is likewise a dataclass (Requirement 27.2). Normalizing provider fields to the one
standard response schema satisfies Requirement 16.4.

## Error Handling

Transient failures are retried up to 3 times after the first attempt, then `transport/error_mapping.py` maps the HTTP status and
payload to the `SkyeError` hierarchy by category (authentication, rate-limit, validation, provider). `BaseModelProvider` wraps the
mapped error in a `ProviderError` carrying provider name, original error and error type, keeping the original message and stack
(Requirement 9.2, 9.9, 18.1). A malformed or unsupported input (bad modality, non-conforming structured output) is rejected at the
boundary naming the field or modality and the input is left unchanged (Requirement 9.6, 26.3, 27.2).

## Testing Strategy

Unit tests in `tests/unit/models` cover each adapter's transformation, capability extraction, streaming, retry, error mapping,
health and `Runnable` conformance against mocked transport, with no network. Differential tests in
`tests/differential/test_models_differential.py` use the vendor SDKs (dev group) as the oracle, comparing the fields and
behaviours the library consumes — structured fields by subset, numbers within an epsilon, errors by category — and skip when
credentials or network are missing (Requirement 9.4, 23.1, D14). The comparison is scaffolding today (see tasks.md).

## Correctness Properties

*A property is a characteristic that should hold across all valid executions; it bridges the user stories and the tests.*

### Property 1: One Port shape whatever the provider

For any provider adapter and any valid `CompleteRequest`, a completion returns a `CompleteResponse` carrying content, role,
token usage, model identifier and provider, and a streamed completion yields `StreamChunk` values, regardless of which adapter
served it.

**Validates: Requirements 1.1, 1.3, 1.4, 1.5**

### Property 2: Transport and adapters import no provider SDK or third-party HTTP client

For any module under `models`, a static import scan finds no vendor SDK and no third-party HTTP client on the runtime path, and
`import skye` imports no provider library and no tokenizer.

**Validates: Requirements 2.1, 2.2, 10.6, 12.1, 12.2**

### Property 3: Retry bound

For any adapter call that keeps failing with a transient error, the number of attempts is at most 4 (the first attempt plus 3
retries) before the mapped error is raised.

**Validates: Requirements 4.1, 4.2**

### Property 4: Adding a provider is local

For any added provider adapter, the change touches only its module under `models/llm` (or `models/embeddings`) and its
registration; no router, tools or completion module changes, and the import matrix still holds.

**Validates: Requirements 5.1, 5.2, 5.3**

### Property 5: Token count never raises on missing extra

For any text and any model, the token counter returns a non-negative integer whether or not `tiktoken` is installed, falling back
to the standard-library approximation when the extra is absent.

**Validates: Requirements 10.1, 10.2, 10.3**

## Superseded (history)

The former `model-providers` spec is replaced, not deleted; its text is in the git history. The changes:
- The selecting `ProviderRegistry` with SDK discovery and fallback is gone: one REST adapter per provider, no selector, no
  `impl` setting, no SDK fallback (D13; Requirement 9.3). `ProviderRegistry` survives only as a name-to-class map behind the
  registry Port.
- The vendor SDKs (openai, anthropic, boto3, google SDK, cohere) are no longer optional runtime extras; they are a dev group
  and differential oracles only (D14; Requirement 9.4).
- `tenacity` is replaced by the standard-library `transport/retry.py` (D2, D13).
- Pydantic structured-output schemas are replaced by dataclasses (D24; Requirement 27.2); the completion models still carry the
  pydantic types and are migrated under O4.
- "Vertex AI" is renamed `google` (D19; Requirement 9.3).
