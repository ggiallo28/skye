Builds on: #[[file:.kiro/steering/11-design.md]] (sections: Transport and providers, DecisionModel (Jev), Extension points, Plugins and provider profiles, Model sizes, catalog and the single client, Public API and lazy imports, Extras and budgets)

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
Google multimodal. Each encodes one text or a list of texts through the one method `encode` (and `aencode`): one text gives one vector, a list
gives a list of vectors with one request where the provider allows it (Bedrock Titan takes one text per request, so the adapter
loops), a list of one gives a list of one, an empty list gives an empty list with no request (Requirements 25.1, 25.2, 67.4). The
Port has no batch methods; `get_vector_dimension` reads the catalog and asks the adapter only for a model the catalog does not know
(Requirement 25.3). The Google multimodal adapter accepts image inputs through `transport/multimodal.py` and returns vectors in the
text-embedding shape (Requirement 25.4). A content that a model cannot read is replaced as "Fitting and emulation" below says
(Requirement 26.3).

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

### Sizes, catalog, fitting and the single client (D121)

This section is the detailed design of Requirements 64 to 67. The system view is the steering section "Model sizes, catalog and the
single client"; the examples that fix the names are `examples/models/model_sizes.py`, `catalog_dates.py`, `fitted_parameters.py`,
`emulated_features.py` and `providers_together.py` (D89).

```
base/
  sizes.py                Size, Reasoning (enums); SizeRow; resolve_size() (pure); the two default dates of the release
  model_info.py           ModelInfo (frozen dataclass: limits, capabilities, modalities, endpoints, reasoning levels, vector size)
  lenient_json.py         the tolerant reader of JSON written by a model (standard library only)
  completion.py           CompleteResponse gains provider, adjustments, requests; Adjustment (frozen dataclass)
  profile.py              ProviderProfile gains families, sizes, parameters; ModelProfile loses the two prices
models/
  client.py               ProviderClient: the single client; providers()
base/sizes.py also holds ProviderDefaults, the TypedDict that types the common arguments of providers()
  catalog.py              reads the catalog file of one platform into ModelInfo values; plain or compressed
  utilities/fitting.py    fit(): common parameters -> native parameters and the list of adjustments
  utilities/emulation.py  capabilities and structured output through the prompt; the line of text for unreadable content
  plugins/providers/<platform>/   profile.json (hand-written), catalog.json (generated)
scripts/
  build_catalog.py        the development script that generates the catalog files
  model_corrections.json  what is corrected by hand over the source
```

**Sizes.** `Size` and `Reasoning` are plain enums in `base/sizes.py`, exported by `<pkg>`; `Reasoning` is ordered. A `SizeRow` is
`(family, kind, size, since, model)`; the rows of a platform are in its `profile.json` under `sizes` and reach `ProviderProfile.sizes`
through `profile_from_mapping`. `resolve_size(rows, family, kind, size, on)` is a pure function: it keeps the rows of that family,
kind and size, takes the one with the latest `since` on or before `on`, and raises a `ConfigurationError` that names the first date
when there is none (Requirements 64.3 to 64.5). The two default dates are constants of `base/sizes.py`, changed only by a release
(Requirement 64.7); a test compares them with the version and the changelog. Nothing else is read: no module-level setting, no
file outside the package, no network (Requirement 64.8). In a configuration file a text equal to the name of a size, in any case,
is the size (Requirement 64.10).

**Catalog.** `models/catalog.py` exposes `catalog(platform)`: it finds `catalog.json` next to the adapter of that platform (or the
compressed file the wheel holds), decodes it once and keeps the result for the process, as the profiles are kept. The file has the
lists of capability names, modalities and endpoints once, at the top, and one row of the same columns per model; a row is decoded into
a `ModelInfo` only when that model is asked for. `info(model, route, place)` applies what differs by route and by place. The reader
builds the reasoning levels from the list of the source when there is one and from its separate flags otherwise. `scripts/build_catalog.py`
writes the files from the source named in D121 and `scripts/model_corrections.json`, deterministically; `scripts/hatch_build.py`
compresses them with `zlib` when it builds the wheel, and a test decodes both forms and compares them (Requirements 65.1 to 65.4).
A model the catalog does not know gives `None`: nothing is fitted and the response says so (Requirement 65.7).

**Fitting and emulation.** `BaseModelProvider` calls `fit(parameters, info, table, strict)` after the model is resolved and before
the adapter builds its request, so every adapter gets it and none repeats it. `fit` walks the common parameters once: it scales an
interval to the native one of the parameter table, clamps `max_tokens` to the output ceiling (and uses the ceiling when it is not
given), adds the room for reasoning on top and reduces reasoning first when the two do not fit, snaps `reasoning` to the nearest
level the model has, and drops what the model or the platform does not accept. It returns the native names and values and a list of
`Adjustment(parameter, asked, sent, reason)`; with `strict=True` it raises a `ValidationError` at the first one and nothing is sent
(Requirements 66.1 to 66.6, 66.11, 66.12). The table is data of the profile and the exceptions are data of the catalog, so `fit`
contains no provider name (Requirement 9.10). `utilities/emulation.py` holds the second step: when capabilities or an output schema
are given and the catalog says the model has no native way, it adds their description and the expected JSON form to the prompt,
reads the answer with `base/lenient_json.py`, returns the usual `CapabilityCall` or validated dataclass, and asks again at most twice
before a `ProviderError`; a streamed answer is held until it is known whether it is a call (Requirements 66.7, 66.8, 27.1). The same
module replaces an image, a document or an audio the model cannot read with one line of text (Requirements 66.9, 26.3). `complete`
makes one request; with `continue_on_limit=True` the base loops while `finish_reason` is `length`, with the native continuation the
catalog names or a follow-up message, and writes the count in `requests` (Requirement 66.10).

**The single client.** `provider(name, **config)` returns a `ProviderClient`. It splits the name on the slash, keeps the family, the
`place`, the defaults (`models`, `language_model`, `embedding_model`, `decision_model`), the two dates and `strict`, and holds three
slots, one per kind, each empty until the first call of that kind: the slot then asks the registrar for the class of that platform
and kind and builds it with the configuration, so a user of `complete` never imports the embedding adapter (Requirement 67.1). A
missing kind raises a `ConfigurationError` at that call. For each call the client picks the model (the call, the default of the kind,
`models`), resolves a size with `resolve_size`, adds the geography prefix for `place` from the places the catalog lists
(Requirement 67.3), and delegates. `resolve(size, kind)` and `info(model)` answer without a request. `providers(language=..., embedding=..., decision=..., **defaults: Unpack[ProviderDefaults])` returns
the same class with the three slots filled from its three arguments (`ProviderDefaults` is a `TypedDict` of `base`, every key optional, exported by `<pkg>`): a name is built with `provider`, a client is taken as it is and
its slot of that kind is used; it gives each default to the providers that have that setting (the value written on a client wins, a
key outside `ProviderDefaults` raises), refuses a secret as a common argument, and reads `catalog`
for the language and decision slots and `embedding_catalog` for the embedding slot (Requirements 67.6 to 67.9). A router is not accepted in any slot and `models` imports nothing of it
(Requirement 67.10). `assignments` shows the provider of each kind, and every response carries `provider` (Requirement 67.11).

**Checked against the documentation of the providers (2026-11-14).** A first reading, made to settle this design; task 15.3 repeats
it when the data files are written and keeps the page next to each value.

| Platform | Native names | Intervals and limits | What the models of the tables refuse |
|---|---|---|---|
| Anthropic (Messages) | `max_tokens` (required), `stop_sequences`, `output_config.effort` | effort `low` to `max` on the four models; 128K output; thinking counts inside `max_tokens` | `temperature`, `top_p`, `top_k`: 400 on every Claude 5 model; no `seed`, no penalties; no prefill |
| OpenAI (Chat Completions) | `max_completion_tokens`, `temperature`, `top_p`, `frequency_penalty`, `presence_penalty`, `seed`, `stop`, `reasoning_effort` | temperature 0 to 2, top_p 0 to 1, penalties -2 to 2, at most 4 stops; 128K output, reasoning included | no `top_k`; sampling parameters removed while reasoning is on; capability calling needs the Responses API (D122) |
| Azure OpenAI | as OpenAI | as OpenAI; `max` only on the Responses API | as OpenAI |
| Google Vertex AI (`generationConfig`) | `maxOutputTokens`, `temperature`, `topP`, `topK`, `seed`, `stopSequences`, `presencePenalty`, `frequencyPenalty`, `thinkingConfig.thinkingLevel` | temperature 0 to 2, topP 0 to 1, penalties -2 to under 2, at most 5 stops; 65,536 output (Gemini 4: 65,536 streamed, 32,768 not) | from Gemini 3.6 Flash on, sampling parameters ignored and penalties refused; no way to switch thinking off |
| Bedrock (Converse `inferenceConfig`) | `maxTokens`, `temperature`, `topP`, `stopSequences`; the rest in `additionalModelRequestFields` per family | temperature and topP 0 to 1; up to 2500 stops; an absent `maxTokens` is the maximum of the model | what the family behind the model refuses |
| Cohere (embeddings only in this library) | `output_dimension`, `input_type` | `embed-v5.0`: 256 to 2048; at most 96 texts per request | (chat: `p` 0.01 to 0.99, `k` 0 to 500, penalties 0 to 1, at most 5 stops, a token budget for thinking) |

Reasoning levels of the models of the tables: Claude Haiku, Sonnet, Opus 5.5 and Fable 5.2 `low` to `max` (thinking can be switched
off only on Haiku 5.5); GPT-6 Luna and GPT-6.1 Terra `none`, `low` to `max`; GPT-6.1 Sol and GPT-6 Astra `low` to `max`; Gemini 3.5
Flash-Lite `minimal` to `high`; Gemini 3.8 Flash, 3.1 Pro and 4 Argon `low` to `high`; Nova 2 Lite `low` to `high`, off by default.
Two consequences for `fit`: a parameter can be accepted only with a value of another one, so reasoning is fitted first and the
sampling parameters after it (Requirement 66.6); and the output ceiling can depend on whether the answer is streamed
(Requirement 66.3), so `ModelInfo` carries the two ceilings where they differ. `gemini-embedding-001` and Titan take one text per
request, so `encode` with a list loops for them.

**The Responses API of OpenAI (D122).** The OpenAI adapter gains a second request and response pair beside the one of Chat
Completions (`plugins/providers/openai/responses.py`): it builds the body of `/v1/responses` from the same `CompleteRequest` and maps its output
items (text, reasoning, function calls) to the same `CompleteResponse`, `StreamChunk` and `CapabilityCall`. The choice of the endpoint
is data: the catalog says, for a model, which endpoints it has and which capability needs which one, and the adapter calls
`/v1/responses` when the request carries capabilities (or another feature the catalog ties to that endpoint) and Chat Completions
otherwise. `OpenAICompatibleProvider` is not touched, so the compatible providers keep Chat Completions. `fit` runs before the choice,
with the parameter names of the endpoint that will be called. Nothing is emulated where the platform has the native way
(Requirement 66.13).

**Left open for the tasks.** `decide` is asynchronous in the Port of today and the client exposes it as it is; giving it the two
forms of the project rule touches `gateway`, `router` and `guard`. The router and the sizes are open decision O83, outside this
spec. A kind `clouds` beside `plugins`, with the maker as the provider and the place as the cloud, is open decision O86: this design
holds as written until it is taken. How a plugin adds rows for a family on a platform it does not own (`plugins.profile` of Requirement 59.11 merges
models today, not rows).

### Token counting and cost

`transport/token_counter.py` provides an approximate counter using only the standard library (~4 chars per token with a
per-model message overhead), present in the core install. Exact counts for OpenAI-family models use `tiktoken`, imported
lazily through `LazyImporter`; if the extra is absent the counter falls back to the approximation. `import skye` never imports
a tokenizer (Requirement 28.1–28.3, 19.1; D25). `CostCalculator` holds no prices and reads no profile: it estimates a cost only from prices the user
gave (`add_custom_pricing`, or the prices of a router target), and reports the cost as unknown, never 0, when none was given
(Requirements 19.2, 59.12, 60.1; D121).

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

`base` gains, for D121: the enums `Size` and `Reasoning`; `SizeRow`; `ModelInfo`; `Adjustment`; the fields `provider`, `adjustments`
and `requests` of `CompleteResponse`; the fields `families`, `sizes` and `parameters` of `ProviderProfile`. `ModelProfile` loses
`prompt_price` and `completion_price`. All are frozen dataclasses or enums of the standard library.

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

### Property 6: A size resolves the same way everywhere

For any platform, family, kind, size and date, `resolve_size` returns the same model on every machine that has the same version of
the library, with no network call and no file outside the package; a later row never changes the answer for an earlier date.

**Validates: Requirements 17.3, 17.4, 17.5, 17.8**

### Property 7: A fit keeps the model and stays inside what it allows

For any parameters and any model of the catalog, what `fit` sends is inside the native interval and the limits of that model, the
model and the provider are the ones resolved, every difference between what was asked and what is sent is in `adjustments`, and
fitting the result again changes nothing.

**Validates: Requirements 19.2, 19.3, 19.5, 19.6, 19.11, 19.12**

### Property 8: Strict sends nothing

For any call with `strict=True` whose parameters would be fitted, a `ValidationError` is raised and no request reaches the transport.

**Validates: Requirements 19.11**

### Property 9: The tolerant reader agrees with the strict one

For any valid JSON text the tolerant reader returns what `json.loads` returns, and for any text it returns a value or raises a
library error, never another exception.

**Validates: Requirements 19.8**

### Property 10: The catalog is the same in the source tree and in the wheel

For any platform, the plain catalog file and the compressed one decode to the same data, and two runs of the script on the same
inputs write the same bytes.

**Validates: Requirements 18.3, 18.4**

### Property 11: The shape of `encode` follows its input

For any text `encode` returns one vector, and for any list of n texts a list of n vectors, n = 0 and n = 1 included.

**Validates: Requirements 20.4**

### Property 12: A secret is never common

For any composition, a secret given as a common argument raises a `ConfigurationError` and no provider receives it.

**Validates: Requirements 20.9**

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
