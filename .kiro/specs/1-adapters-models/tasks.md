# Implementation Plan: models

## Overview

Milestones in build order for the `models` component (codename zephyr): the shared transport first, then the base providers,
then the per-provider REST adapters, embeddings, token counting and cost, the decision model, and the differential oracle.
Status is judged from the code in `src/skye/models` and the tests in `tests/`, not from the former `model-providers` checkboxes.
Each task cites the steering requirement numbers it satisfies (`Requirement N.k` of `10-requirements.md`) or the decision it
honors.

## Tasks

- [x] 1. Shared transport (stdlib only)
  - [x] 1.1 JSON REST over `base/http.py`
    - Evidence: `src/skye/models/utilities/rest.py` (`post_json`, `stream_sse_json`, `JsonObject`), `src/skye/base/http.py`; `tests/unit/test_rest_transport.py`, `tests/unit/test_transport.py`.
    - _Requirements: 9.1, 9.3_
  - [x] 1.2 SSE streaming decoder
    - Evidence: `src/skye/models/utilities/streaming.py` (`parse_sse`); `tests/unit/test_transport.py`.
    - _Requirements: 9.9, 16.5_
  - [x] 1.3 Bedrock eventstream decoder
    - Evidence: `src/skye/models/utilities/eventstream.py`; `tests/unit/test_eventstream.py`.
    - _Requirements: 9.9, 16.5_
  - [x] 1.4 Retry policy (3 after first attempt)
    - Evidence: `src/skye/models/utilities/retry.py` (`with_retry`); `tests/unit/models/test_retry_logic.py`.
    - _Requirements: 9.2_
  - [x] 1.5 Error mapping to the SkyeError hierarchy
    - Evidence: `src/skye/models/utilities/error_mapping.py`; `tests/unit/models/test_error_handling.py`.
    - _Requirements: 9.9, 18.1_

- [x] 2. Base providers and registry
  - [x] 2.1 `BaseModelProvider` / `BaseEmbeddingProvider` with retry, health and `Runnable.invoke`
    - Evidence: `src/skye/models/base.py`; `tests/unit/models/test_base_provider.py`, `test_base_embedding_provider.py`, `test_runnable_conformance.py`.
    - _Requirements: 9.1, 9.5, 9.10, 16.1_
  - [x] 2.2 Registry behind the registry Port + `provider()` factory
    - Evidence: `src/skye/models/registry.py` (`ProviderRegistry`, `provider`); `tests/unit/models/test_provider_registry.py`, `test_provider_registration.py`.
    - _Requirements: 9.9, 6.1_
  - [x]* 2.3 Health metrics unit tests
    - Evidence: `tests/unit/models/test_health_monitoring.py`.
    - _Requirements: 17.2, 18.3_

- [x] 3. REST adapters (one per provider)
  - [x] 3.1 OpenAI and Azure OpenAI (one family keyed by base URL + key)
    - Evidence: `src/skye/models/utilities/openai_compatible/` (`OpenAICompatibleProvider`), `openai.py` (`OpenAIProvider`), `azure.py` (`AzureOpenAIProvider`); `tests/unit/models/test_openai_provider.py`, `test_azure_provider.py`, `tests/unit/test_openai_shape.py`.
    - _Requirements: 9.3, 9.5, 9.6, 9.10, 22.1_
  - [x] 3.2 Anthropic (Messages API, system message separate)
    - Evidence: `src/skye/models/utilities/anthropic_compatible/` (`AnthropicCompatibleProvider`) and `anthropic.py` (`AnthropicProvider`); `tests/unit/models/test_anthropic_provider.py`.
    - _Requirements: 9.3, 9.5, 9.6, 9.10_
  - [x] 3.3 Bedrock (Converse + stream, SigV4 via auth, boto3 not required)
    - Evidence: `src/skye/models/plugins/bedrock/provider.py`; `tests/unit/models/test_bedrock_provider.py`.
    - _Requirements: 9.3, 9.5, 9.9, 7.3_
  - [x] 3.4 Google adapter (formerly "Vertex AI", renamed `google`)
    - Evidence: `src/skye/models/plugins/google/provider.py` (`GoogleProvider`), registered as `"google"` in `src/skye/models/__init__.py`; `tests/unit/models/test_google_provider.py`.
    - _Requirements: 9.3; D19_
  - [x] 3.5 Google adapter authentication through the `auth` component
    - Evidence: `src/skye/models/plugins/google/provider.py` imports `AuthenticationInterface` from `skye.base.interfaces.authentication`, resolves credentials via `skye.auth.plugins.google.source.resolve_google_auth`, has `_initialize_client` return `None` (no vendor SDK), and exposes a lazy `authenticator` property that signs requests over the shared transport; `src/skye/auth/plugins/google/source.py`.
    - _Requirements: 9.3, 11.1, 11.9_

- [x] 4. Embedding adapters behind the `vector_encoder` Port
  - [x] 4.1 OpenAI, Bedrock (Titan), Cohere, Google embeddings
    - Evidence: `src/skye/models/plugins/openai/embeddings.py`, `bedrock_embeddings.py`, `cohere_embeddings.py`, `google_embeddings.py`; `tests/unit/models/test_openai_embeddings.py`, `test_bedrock_embeddings.py`, `test_cohere_embeddings.py`, `test_google_embeddings.py`.
    - _Requirements: 25.1, 25.2, 25.3_
  - [x] 4.2 Google multimodal embeddings (image inputs, text-shaped vectors)
    - Evidence: `src/skye/models/plugins/google/multimodal_embeddings.py`; `tests/unit/models/test_google_multimodal_embeddings.py`.
    - _Requirements: 25.4, 26.1, 26.3_

- [x] 5. Multimodal inputs at the boundary
  - [x] 5.1 `ImageHandler`: URL / data URL / path / bytes -> provider shape
    - Evidence: `src/skye/models/utilities/multimodal.py`.
    - _Requirements: 26.1, 26.2, 26.3_
  - [x] 5.2 Carry images in a message and convert them in each adapter
    - Evidence: `src/skye/base/messages.py` (`UserMessage.images`: URL, `data:` URI, path or bytes; `to_dict` turns them into JSON-safe text; `sniff_image_mime`), `src/skye/models/utilities/multimodal.py` (`ImageHandler.to_google_format`, MIME sniffing for bytes, `to_bedrock_format` rejects a URL because Bedrock does not fetch them), the four adapters' `_transform_messages` (OpenAI `image_url` parts, Anthropic `image` blocks before the text, Bedrock `image` blocks with base64 bytes, Google `inlineData`/`fileData` parts); `tests/unit/models/test_message_images.py` (each provider's request body over a fake network); the example `examples/advanced/multimodal.py` shows a message with an image. Decision taken on 2026-11-03: images live in a field of `UserMessage`, not in `ContentChunk` parts.
    - _Requirements: 26.1, 26.2, 26.3_

- [x] 6. Token counting and cost
  - [x] 6.1 Cost estimation and custom pricing
    - Evidence: `src/skye/models/cost.py` (`CostCalculator`); `tests/unit` cost coverage.
    - _Requirements: 19.1, 19.2_
  - [x] 6.2 Tokenizer per D25: stdlib approximate by default, lazy `tiktoken` extra
    - Evidence: `src/skye/models/token_counter.py` (stdlib estimate by default; `tiktoken` through `LazyImporter` with `install_extra="tokens"`); decision D33 renames the extra `openai` to `tokens` (option A of the former O22; `openai` stays as an empty extra), with `pyproject.toml`, `[extras.tokens]` in `budgets.toml`, the CI footprint job and `tests/budget` following; `tests/unit/models/test_token_counter_without_extra.py` (`import skye` loads no tokenizer, counting works with `tiktoken` blocked, the counter asks for the `tokens` extra). D33 was taken by the assistant on the instruction to implement every task: change it if you decide otherwise.
    - _Requirements: 28.1, 28.2, 28.3; D25_

- [x] 7. Decision model (Jev)
  - [x] 7.1 Implement `models/plugins/typesafe/decision.py` behind the `decision` Port
    - Evidence: `src/skye/models/plugins/typesafe/decision.py` (`JevDecisionModel` implements `DecisionModel`; `normalize_probabilities` checks every option has a probability in 0..1 and scales them to sum to 1; the choice is the most probable option, the first on a tie; an empty, duplicated or non-string option set raises `ValidationError` and nothing is sent; a malformed answer raises `ProviderError` and returns no choice), exported from `skye.models`; `tests/unit/models/test_jev_decision.py`. The wire format (`{"prompt", "options"}` in, `{"probabilities": {option: p} | [p, ...]}` out) is the one the spec and the gateway assume; it was not checked against a hosted Jev service, so `_build_request` and `_read_probabilities` are the two places to adapt. No environment variable is read (D18). The gateway selector stays under O8.
    - _Requirements: 9.8_
  - [x]* 7.2 Property test: probabilities are well-formed
    - Evidence: `tests/unit/models/test_jev_decision.py` (`test_probabilities_are_well_formed_for_any_non_empty_option_set`: 300 seeded random option sets, each probability in 0..1, sum 1, the chosen option has the maximum; the empty set raises and sends nothing). No property-testing library is a dev dependency, so it uses a seeded `random.Random`.
    - _Requirements: 9.8_

- [x] 8. Structured output on dataclasses (D24)
  - [x] 8.1 Move `response_schema` / `structured_output` off pydantic
    - Evidence: `src/skye/models/utilities/structured.py` (`schema_of`, `strict_schema`, `parse_structured`, `schema_instruction`, `STRUCTURED_TOOL`), used by `models/base.py` and the adapters; a `@validated` or plain `@dataclass` is the declared shape, a user's pydantic model still works through `model_json_schema` / `model_validate_json`, and a reply that does not conform raises `ValidationError` naming the field (not retried: `_complete_with_retry` no longer wraps it). OpenAI: `json_schema` response format, `strict` only when every property is required. Anthropic and Bedrock had no structured path: they now force one tool (`skye_structured_output`) and read its input (function calling, Requirement 27.1); Google asks for `application/json` with the schema in the system instruction. `src/skye/base/validated.py` gained enum fields (validation, schema, serialization). `tests/unit/models/test_structured_output_dataclass.py`, `tests/unit/test_validated.py`; the request shapes are tested over a fake network, not against the live services.
    - _Requirements: 27.1, 27.2; D24_
  - [x] 8.2 Rewrite the structured-output examples off pydantic
    - Evidence: `examples/advanced/structured_output.py`, `examples/providers/structured_output_example.py`, `examples/basic/simple_completion.py` and `examples/providers/multimodal_example.py` use `@validated` dataclasses and no pydantic import; the docs (`docs/models/structured-outputs.md`, `docs/getting-started.md`, `docs/models/provider-guide.md`, the examples READMEs) follow. `tests/examples` runs them.
    - _Requirements: 24.2, 24.3; D24_

- [x] 9. Differential oracle (SDK vs REST)
  - [x] 9.1 Resolve the 4 skipped differential tests
    - Evidence: `tests/differential/test_models_differential.py` and `tests/differential/fake_model_server.py`: the same request goes through the built-in REST adapter and the vendor SDK (`openai`, `anthropic`, `boto3`, each pointed at a local fake server speaking the provider's wire format), and the text, finish reason and token usage (epsilon 0) must match, as must the error category (401, 429) and the user text sent. OpenAI, Anthropic and Bedrock are covered; Google is not, because the Vertex SDK cannot be redirected to a local server (the file says so). It needs no credentials, so no case skips on a missing key. It found a real defect, fixed: `ProviderError` lost the HTTP status when the adapter wrapped the transport's error (`models/base.py`; unit test in `tests/unit/models/test_message_images.py`). Run with `make differential`.
    - _Requirements: 9.4; D14_

- [x] 10. Checkpoint
  - Evidence: full `models` suite green — `uv run pytest tests/unit/models tests/differential -q` → 426 passed (2026-11-03). Open follow-ups noted elsewhere in this plan: D33 (extra `tokens`) and the Jev wire format were assistant decisions pending owner ratification, the Google differential case is uncovered, and O8 (gateway selector for Jev) remains open.

- [x] 11. Native structured output and system prompt from prompt parts (D81, D101)
  - [x] 11.1 `PromptParts` and `OutputSchema` in `base`, and the model side of D81
    - Evidence: `src/skye/base/prompt_parts.py` (frozen dataclasses: `messages`, `system`, `output`, `fallback_text`; `OutputSchema(name, schema, strict)`), re-exported by `skye.base.interfaces` and `skye.interfaces`; `CompleteRequest.response_schema` accepts an `OutputSchema` (its reply is a `dict`, checked for the top-level `required` keys). `src/skye/models/utilities/prompt_parts.py` (`request_from_parts(parts, model=, info=)`): the system text becomes a `SystemMessage` (prefixed to the first user message when the model reports `supports_system_messages=False`); the schema goes to `response_schema` when the model reports `supports_structured_output` or `supports_function_calling`, otherwise the fallback text (or a sentence written from the schema) joins the instructions. `BaseModelProvider.request_from_parts` and `complete(parts, model=...)` (also `acomplete` and `stream`) use the capabilities from `get_model_info()`. `models` imports nothing from `prompts`.
    - _Requirements: 27.1, 9.10, 33.9; D81, D101_
  - [x] 11.2 Native fields per provider
    - Evidence: OpenAI `response_format` json_schema with the `OutputSchema` name and `strict` as set; Anthropic `system` and one forced tool; Bedrock Converse top-level `system` (system messages are no longer sent as a `system` role inside `messages`, which Converse rejects) and one forced tool; Gemini `systemInstruction` and a native `responseSchema` (`gemini_schema` in `transport/structured.py`: upper-case types, `nullable`, no `additionalProperties`), with the JSON-mode instruction kept as the fallback for a schema outside Gemini's subset (`$ref`, `$defs`); the Google adapter now reports `supports_structured_output`. Tests: `tests/unit/models/test_prompt_parts.py` (15 tests: each provider native, Gemini fallback, no schema, no system, fallback text, no system messages, parts unchanged, reply checks, router rejected), `tests/unit/models/test_structured_output_dataclass.py::test_google_sends_the_schema_natively_as_response_schema`, `tests/unit/models/test_bedrock_provider.py::test_transform_request_with_system_message`. Shapes checked against a fake network, not the live services.
    - _Requirements: 27.1, 33.9; D101_

- [x] 12. Fixes found by the documentation review (2026-11-11)
  - [x] 12.1 Provider errors and who retries (D104; findings 3 and 10 of the review)
    - Evidence: `src/skye/models/utilities/error_mapping.py` builds the `ProviderError` subclass of the failure (`error_class`: a known status follows the one rule of `skye.base.http._status_class`, otherwise the classification); `src/skye/models/utilities/retry.py` (`RETRYABLE_ERRORS`, `is_retryable`, `retry_wait`, `call_with_retry`; `with_retry` retries only the transient errors and honours `retry_after`); `src/skye/models/base.py` keeps the class of a transport error (it no longer rewraps it as a plain `ProviderError`), retries only `RateLimitError`, `ServerError` and `ProviderTimeoutError` with backoff or `Retry-After`, never a 4xx, reads `self.max_retries` at call time (constructor argument and attribute, 3 by default after Requirement 9.2, `0` turns retries off; the router sets it to 0 on its targets) and an injectable `retry_sleep`; a stream is retried only before its first chunk. Tests: `tests/unit/models/test_review_fixes.py` (transient errors retried, 401/403/400/404/content filter raised at once with their class, `Retry-After`, backoff, `max_retries`, the stream before and after its first chunk, the error mapping), `tests/unit/models/test_retry_logic.py`, `tests/unit/models/test_retry_stdlib.py`, `tests/unit/test_transport.py`; the example `examples/models/retry_and_errors.py`.
    - _Requirements: 9.2, 18.1; D104_
  - [x] 12.2 Google keeps its location; Google embeddings through `provider` (finding 9)
    - Evidence: `src/skye/models/registry.py` (`_normalize_location`: `region` and `location` name the parameter the class takes, so an AWS client gets `region_name` and a Google client keeps `location`); `src/skye/models/plugins/google/multimodal_embeddings.py` accepts `model`. Tests: `test_review_fixes.py::test_google_keeps_location`, `test_google_embeddings_through_provider`, `test_bedrock_still_takes_region`; the example `examples/providers/google_example.py` builds the embedding client with the same `location`.
    - _Requirements: 9.11, 25.1; D19_
  - [x] 12.3 Output schema together with tools on Anthropic and Bedrock (finding 11)
    - Evidence: `src/skye/models/utilities/anthropic_compatible/` sends `output_config.format` (`json_schema`, the schema closed by `closed_schema` in `transport/structured.py`) next to the tools; `src/skye/models/plugins/bedrock/provider.py` writes `schema_instruction` in the Converse `system` (Converse cannot force the answer tool and offer the others in one turn); `models/base.py` checks the reply only on a turn without capability calls. Tests: `test_review_fixes.py::test_anthropic_sends_the_schema_with_tools`, `test_bedrock_sends_the_schema_with_tools_as_text`. Shapes checked against a fake network, not the live services.
    - _Requirements: 27.1, 9.10; D24, D101_
  - [x] 12.4 `astream` and `acomplete` do not block the event loop (finding 12)
    - Evidence: `src/skye/models/base.py`: `astream` reads the synchronous stream in a worker of the loop's executor and hands each chunk over through an `asyncio.Queue`; it waits for the worker before closing, so nothing outlives the call; the base `acomplete` runs `complete` in the executor. Tests: `test_review_fixes.py::test_astream_does_not_block_the_event_loop`, `test_astream_raises_the_stream_error`.
    - _Requirements: 9.1_
  - [x] 12.5 The Bedrock region (finding 13)
    - Evidence: `src/skye/models/utilities/credentials.py` (`resolve_aws_region`: the argument, the authenticator's `region`, `AWS_REGION`, `AWS_DEFAULT_REGION`, else `ConfigurationError` naming them; no silent `us-east-1`), used by `BedrockProvider` (new `authenticator=` argument) and `BedrockEmbeddingProvider`; `src/skye/auth/plugins/aws/source.py` `bedrock_authenticator` passes its region to `BedrockApiKeyAuthenticator(region=...)`. Tests: `test_review_fixes.py::test_bedrock_reads_aws_region`, `test_bedrock_without_a_region_says_so`, `test_bedrock_takes_the_region_of_its_authenticator`; `tests/unit/models/test_bedrock_provider.py` sets `AWS_REGION`.
    - _Requirements: 9.3; D18_
  - [x] 12.6 Standard key variables (finding 14, D18)
    - Evidence: `src/skye/models/utilities/credentials.py` (`resolve_api_key`); `OpenAIProvider` reads `OPENAI_API_KEY`, `AnthropicProvider` `ANTHROPIC_API_KEY`, `AzureOpenAIProvider` `AZURE_OPENAI_API_KEY`, `OpenAIEmbeddingProvider` `OPENAI_API_KEY`, `CohereEmbeddingProvider` `COHERE_API_KEY` (the names `skye.auth` fixes); a missing key raises `ConfigurationError` naming the variable, and `ProviderRegistry` lets it through unchanged. Tests: `test_review_fixes.py::test_keys_come_from_the_standard_variable`, `test_embedding_keys_come_from_the_standard_variable`, `test_azure_reads_its_standard_key`, `test_the_key_variables_are_the_ones_auth_fixes` (the adapters name the variables literally, because an adapter may not import `skye.auth.plugins.openai_compatible.source`; the test ties them to the table of `auth`).
    - _Requirements: 11.6, 9.11; D18_
  - [x] 12.7 Cohere through `provider` (finding 15)
    - Evidence: `src/skye/models/registry.py`: a name registered only as an embedding provider gives it without `provider_type`; an unknown name lists the providers and no longer suggests an extra; a model-provider lookup of an embedding-only name says to pass `provider_type="embedding"`. Tests: `test_review_fixes.py::test_cohere_without_provider_type_is_the_embedding_client`, `test_unknown_provider_does_not_suggest_an_extra`, `tests/unit/models/test_provider_registry.py`; the example `examples/models/cohere.py`.
    - _Requirements: 9.11, 25.1; D28_
  - [x] 12.8 Azure Entra ID (finding 16)
    - Evidence: `src/skye/models/plugins/azure/provider.py` takes `credentials=` (an authenticator of `skye.auth.plugins.azure.source` or a key) or, with neither, `resolve_azure_auth` (the key variable, then the Entra ID modes); `OpenAICompatibleProvider._authenticator` passes it to `rest.post_json` and `stream_sse_json`. Tests: `test_review_fixes.py::test_azure_accepts_a_token_credential`, `test_azure_without_credentials_names_the_variable`, `tests/unit/models/test_azure_provider.py`.
    - _Requirements: 9.3; D18_
  - [x] 12.9 A registry or a `ToolProvider` as `capabilities`; `CompleteRequest.mcp_servers` removed (finding 17)
    - Evidence: `src/skye/models/base.py` (`capability_list`, `_resolved`): a `CapabilityRegistry` or any object with `list_schemas` gives its schemas to the adapter, and the response keeps the registry to run the calls; `src/skye/base/completion.py` loses `mcp_servers`, which nothing read. Tests: `test_review_fixes.py::test_complete_accepts_a_capability_registry`, `test_complete_accepts_any_tool_provider`, `test_complete_request_has_no_mcp_servers`, `tests/unit/test_completion_models.py::test_completion_request_has_no_mcp_servers`.
    - _Requirements: 9.10, 22.1_
  - [x] 12.10 `OutputSchema` replies checked against the whole schema (finding 18)
    - Evidence: `src/skye/models/utilities/schema_check.py` (`check_json`, standard library: types, nested objects, arrays and items, `enum`, `const`, `required`, `additionalProperties`, `anyOf`/`oneOf`/`allOf`/`not`, `$ref`, length and number limits; `field` is the path of the value), used by `parse_structured`; `base` had no validator to reuse. Tests: `test_review_fixes.py::test_output_schema_replies_are_checked_against_the_whole_schema` (7 cases), `test_a_conforming_output_schema_reply_is_returned`, `tests/unit/models/test_prompt_parts.py`.
    - _Requirements: 27.2; D101_
  - [x] 12.11 Examples, public transport, skeleton model id and prices (finding 30, models part)
    - Evidence: `examples/models/token_counting.py` (the `tokens` extra), `examples/basic/quickstart.py` (keys from the standard variables), `examples/advanced/multimodal.py`, `examples/models/cohere.py` (now a live Cohere embedding example), `examples/advanced/custom_providers.py` points to `skye.models.post_json`, re-exported from `skye.models` with `stream_sse_json` and `JsonObject` (documented in the package docstring and `docs/guides/extend/custom-provider.md`), `examples/auth/credential_sources.py` imports from `skye.auth`; `src/skye/base/dsl/skeletons.py` writes `claude-haiku-5-5` for `skye new router`; `CostCalculator` docstring dates its prices (November 2024). Docs: `docs/guides/models/{call-a-provider,structured-output,streaming,embeddings,tokens-and-cost}.md`, `docs/get-started/{first-call,first-router,lambda}.md`, `docs/guides/security/credentials.md` lose the warnings of the fixed bugs; the skill reference `references/python-api.md` gains a "Clients" section. `tests/examples` runs every example offline.
    - _Requirements: 24.4, 28.2, 19.1; D33_
  - [x] 12.12 Run the checks
    - Evidence (2026-11-11): `uv run pytest tests/unit/models tests/differential tests/budget tests/docs tests/examples -q` → 1017 passed; `uv run pytest tests/unit -q` → 3242 passed, 3 skipped; `make budget-fast` → 318 passed; `uv run mkdocs build --strict` → built, no warning; `uv run mypy` on the 23 changed source files → one error, the earlier `_transform_messages` override of `anthropic_compatible.py`; `ruff` and `black` clean on the new files (`schema_check.py`, `credentials.py`, `retry.py`, `error_mapping.py`, the new tests); the older files they touch keep their earlier line-length findings.
    - _Requirements: 9.2, 27.2; D104_

  - [x] 12.13 Anthropic structured output always through `output_config.format`, never a forced tool (owner decision of 2026-11-11: `tool_choice` `tool`/`any` is a 400 on Claude Opus 5.5, Sonnet 5.5 and Fable 5.1)
    - Evidence: `src/skye/models/utilities/anthropic_compatible/` (`_transform_request` sends `output_config.format` of type `json_schema` with the closed schema for every `response_schema`, with or without capabilities; `get_model_info` reports `supports_structured_output: True`); `tests/unit/models/test_structured_output_dataclass.py::test_anthropic_uses_the_native_output_format_and_reads_the_text`, `tests/unit/models/test_prompt_parts.py::test_anthropic_gets_the_system_field_and_the_native_output_format` (both failed on the old code); `docs/guides/models/structured-output.md`.
    - _Requirements: 33.9; D81, D101_
  - [x] 12.14 The cost of a call and the running count of a stream (owner decisions of 2026-11-11)
    - Evidence: `src/skye/models/base.py` (`_account`: `response.metadata["cost"]` from the provider's token count, estimated only when the provider reports none, then `response.usage` takes the estimate, `metadata["usage_estimated"]` is true and `cost["exact"]` false; `_with_running_cost`: every `StreamChunk` gets `usage` and `cost`, a chunk with text moves the counter and any other chunk repeats the one before; `pricing=` of the client, checked by `check_pricing`); `src/skye/base/completion.py` (`StreamChunk.usage`, `StreamChunk.cost`); `src/skye/models/cost.py` (`usage_of`, `check_pricing`, `CostCalculator.breakdown` split in `prompt`, `completion`, `total` with `None` for a model with no price, `CostCalculator.pricing_for`: a dated or versioned name finds its family, another model that only starts with a known name does not, so `gpt-4o` is never priced as `gpt-4`); `src/skye/models/token_counter.py` (`TokenCounter.register_tokenizer` and `unregister_tokenizer`: any object with `encode(text)`, by model or name prefix, the longest wins; an empty text counts 0); the adapters read the provider's count in a stream: OpenAI (`stream_options.include_usage`, asked only by `OpenAIProvider` through `streams_usage`, other OpenAI-compatible endpoints keep the estimate), Anthropic (`message_start` gives the prompt, `message_delta` the output), Bedrock (the `metadata` event), Google (`usageMetadata`). Checked against the docs: OpenAI `include_usage` (an extra last chunk with no choices), Bedrock `ConverseStreamMetadataEvent.usage`, Gemini `usageMetadata`; Anthropic's event fields come from secondary sources only (the official page was not extractable), so the adapter reads them defensively. Tests: `tests/unit/models/test_cost_and_usage.py` (24 tests: split cost and `exact`, dated name, no price gives `None`, `pricing=`, estimate when the provider reports none, the counter on every chunk and the repeat on a free chunk, chunks do not share their counter, the four adapters, `usage_of`, `breakdown`, `pricing_for`, tokenizers). Docs: `docs/guides/models/tokens-and-cost.md`, `streaming.md`, `call-a-provider.md`; the skill reference `references/python-api.md`. Known limits: Gemini thinking tokens (`thoughtsTokenCount`) are not in the completion count, as in `complete()` before this change; the prices of the table are those of November 2024.
    - _Requirements: 19.1, 19.2, 28.1, 28.2; D25, D33_

  - [x] 12.15 One structured log event per phase of a model invocation (Requirement 18.3; owner decision of 2026-11-11)
    - Evidence: `src/skye/models/base.py` (`complete` and `stream` log a start (DEBUG), an end (INFO) and, on failure, one error (WARNING) with `logger.log(..., extra=event.log_extra())`, never an f-string; one correlation id per call; one error event after the retries, not one per retry; a stream the caller abandons still logs its end, with `finish_reason` `interrupted` and the count so far; a failure to build or log an event is noted at DEBUG and never breaks the call; `acomplete` and `astream` go through the same two methods); `src/skye/base/log_event.py` (`model_invocation_summary`, so a stream, which has no `CompleteResponse`, builds the end event; the end event now carries the `cost`). No message content is logged. Tests: `tests/unit/models/test_invocation_log.py` (8 tests: start and end with one id, no content in the log, one error after 3 retries, the end of a stream with the last running count, an abandoned stream, a stream that fails, a logging failure, the provider name), `tests/unit/test_log_event.py`. Not touched: the telemetry hooks of Requirement 18.4.
    - _Requirements: 18.3; D105_

  - [x] 12.16 A forced capability choice, emulated for the models that refuse one (decision D109)
    - Evidence: `src/skye/models/utilities/capability_choice.py` (`forced_choice`, `emulated_request`: `capability_choice` becomes `auto`, one instruction is appended as a new last message, the tool list is unchanged unless `force_choice=True`, which keeps only the named capability and is refused with `ValidationError` once the conversation holds an `AssistantMessage`; a name not offered is a `ValidationError`; `complete_emulated`: two attempts, the failed one dropped, then `CapabilityChoiceError`); `src/skye/models/base.py` (`refuses_forced_choice`, `False` by default; `_complete_with_retry` emulates, the stream sends the emulated request with no check); `src/skye/models/utilities/anthropic_compatible/` and `bedrock.py` (`CLAUDE_REFUSING_FORCED_CHOICE`: Opus 5.5, Sonnet 5.5, Fable 5.1, Mythos 5.1; Bedrock merges consecutive messages of one role, as Converse wants them alternating); `src/skye/base/completion.py` (`CompleteRequest.force_choice`, `CompleteResponse.added_messages`); `src/skye/base/exceptions.py` (`CapabilityChoiceError`, exported by `skye.exceptions`). Tests: `tests/unit/models/test_capability_choice_emulation.py` (13 tests). Docs: `docs/guides/tools/local-functions.md`.
    - _Requirements: 9.2; D109_

- [ ] 13. Audio and video inputs (Requirement 26.2; deferred by the owner on 2026-11-11: no adapter needs them today)
  - [ ] 13.1 Carry audio and video in a user message, next to `UserMessage.images`: a URL, a data URI, a path or bytes, with the MIME type sniffed or given
    - _Requirements: 26.2_
  - [ ] 13.2 Convert them at the boundary of each adapter whose models accept them, in the shape that provider documents (taken from its documentation when the task starts, not from memory), and raise `UnsupportedModalityError` naming the modality in every adapter that does not
    - _Requirements: 26.2, 26.3_
  - [ ] 13.3 Tests over a fake network for each adapter (accepted and refused), a runnable example in `examples/`, the page `docs/guides/models/images.md` extended or a sibling page, and the Claude skill reference updated in the same change
    - _Requirements: 26.2, 24.2_

- [ ] 14. Final checkpoint
  - [ ] 14.1 Validate the code against every criterion this spec points to (`requirements.md`: the Requirements of `10-requirements.md` and decisions D13, D14, D19, D24, D25, D28, D81, D101). For each criterion, write one evidence line: the file or function that realizes it and the test that checks it. A criterion with no code or no test is a finding.
    - Evidence (2026-11-11, by reading code and tests; no test was run; left open because code and requirement disagree): the per-criterion table is in `.agents/tasks/1-adapters-final-checkpoint-2026-11-11.md`. R9.2 was a disagreement and is fixed (owner choice A, 2026-11-11): after the D104 rewrite the provider default was 2 retries (`call_with_retry`, `DEFAULT_MAX_RETRIES`); it is now 3, as in the requirement, and `tests/unit/models/test_review_fixes.py::test_the_default_is_three_retries_after_the_first_attempt` asserts 4 calls and waits 1, 2, 4 (706 passed in `tests/unit/models`, `router`, `differential` and `test_docstrings.py`; mypy clean on `retry.py` and `base.py`). The old `with_retry` decorator is unchanged and unused by the providers. R26.3 was a disagreement and is fixed (owner choice B, 2026-11-11): new `UnsupportedModalityError(ProviderError)` in `base/exceptions.py` (`.modality`, no `status_code`, not retryable), exported by `skye.exceptions`; `ImageHandler.to_bedrock_format` raises it for an image URL with a message that names the modality; `tests/unit/models/test_message_images.py::test_bedrock_rejects_an_image_url` asserts the class, `modality == "image"`, the input unchanged and `is_retryable` false; docs (`docs/guides/models/call-a-provider.md`) and the Claude skill (`references/rules.md`, `references/python-api.md`) follow. `uv run pytest tests/unit tests/budget tests/differential -q` → 3587 passed, 3 skipped, 11 deselected; mypy clean on the three changed modules. R19.1 was missing code and is done (task 12.14); R18.3 was missing code and is done (task 12.15). R26.2 (no audio or video) is moved to task 13 by the owner. Still missing a test or a check: R9.3, R22.1, R7.8. Steering inconsistencies: `tiktoken` against `tokens` (R28.2, D25, D33) and the R17.2 pointer.
  - [x] 14.2 Run `uv run pytest tests/unit/models tests/differential -q`, the doctests of `src/skye/base/prompt_parts.py` and `src/skye/models/utilities/prompt_parts.py`, `make budget`, and `uv run mypy` on the changed files.
    - Evidence (2026-11-11): `uv run pytest tests/unit/models tests/differential -q` → 445 passed; doctests of `src/skye/base/prompt_parts.py` (4 examples) and `src/skye/models/utilities/prompt_parts.py` (5), 0 failed (run with the flags of `tests/unit/test_docstrings.py`); `make budget` → 11 passed; `uv run mypy` on `base/prompt_parts.py`, `models/utilities/{payload/{prompt_parts,structured},accounting/cost}.py`, `base/interfaces/storage.py` and `store` → no issues in 15 files. One fix: the example of `models/cost.py` printed `$0.0045`, while `gpt-4` at 30 and 60 per million gives `$0.0060` (the value the unit tests assert); the docstring is corrected.
  - [ ] 14.3 Check the request shapes of task 11 against the provider documentation: Gemini `responseSchema` (upper-case types), OpenAI `response_format` json_schema with `strict`, Anthropic `system`, and Bedrock Converse top-level `system`.
    - _Requirements: 9, 27.1, 33.9; D81, D101_

## Notes

- Tasks marked with `*` are optional (tests) and can be skipped for a faster path.
- Status reflects the code in `src/skye/models` and `tests/` at migration time, not the former `model-providers` checkboxes.
- The `models` extra is empty (stdlib REST); `google` declares only its SDK and exact token counting declares only `tiktoken` (design "Extras and budgets"; D25).
- Done on 2026-11-03: every task except the final checkpoint (10), left for the final verification. Decisions taken on the instruction to implement everything: D33 (extra `tokens`), images as a `UserMessage` field, the Jev wire format as an assumption (7.1). Still open: O8 (gateway selector for Jev), the Google differential case, a live check of the request shapes against the real services.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3", "1.4", "1.5"] },
    { "id": 1, "tasks": ["2.1", "2.2", "5.1", "6.1"] },
    { "id": 2, "tasks": ["2.3", "3.1", "3.2", "3.3", "3.4", "5.2", "6.2", "7.1"] },
    { "id": 3, "tasks": ["3.5", "4.1", "7.2", "8.1"] },
    { "id": 4, "tasks": ["4.2", "8.2", "9.1"] },
    { "id": 5, "tasks": ["10"] }
  ]
}
```
