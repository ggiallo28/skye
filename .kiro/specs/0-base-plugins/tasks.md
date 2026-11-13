# Implementation Plan: plugins

## Overview
Milestones in the order of decisions D108 and D111. The first plan (tasks 1 to 11) built the registrar, the provider profile, the layout of
the built-ins, the views of the old registries and the first half of discovery against the interface of D108: a plugin object with
`register(registrar)`, eleven registrar methods, `skye.use`. D111 replaced that interface by one object, `plugins = skye.Plugins()`, with a
decorator for each of nine kinds, and added the toolkits and the agent call. Tasks 13 to 21 build the interface of D111 on what exists;
the tasks of the first plan that its code replaces carry a note that says which new task redoes them, and the open ones were rewritten.
Task 12, the final checkpoint, keeps its id because tests cite the ids of this file, and runs last. Status is judged from the code and the
tests. Each task cites the steering requirement numbers it satisfies (`Requirement N.k` of `10-requirements.md`) or the decision it honors.
Task IDs cited from other documents are `plugins:N.k`. A task that depends on an open point (O19, O63, O65, O68 to O73 of `12-decisions.md`)
says so; the tasks follow the recommended option of each, and a different answer from the owner changes only the task named.

The token-counter work of `1-adapters-models` uses the field names of Requirement 59.2; task 6.2 takes over what is left of it. What belongs
to the agent loop (`tools=`, `toolkits=`, `return_direct`, the hooks) is the work of `3-runtime-agents`, and the content of the built-in
toolkits is open in O70; tasks 18 and 19 build only the registration and the shape.

## Tasks
- [x] 1. The example, before any component changes
  - [x] 1.1 Write `examples/plugins/` against the planned API: a provider registered with `OpenAICompatibleProvider` and a
    `ProviderProfile`, a store backend, `skye.use(plugin)`, and the `[project.entry-points."skye.plugins"]` declaration in a
    `pyproject.toml` of the example; a `README.md` with the reading order. No network and no key.
    - _Requirements: 61.1, 24.4, 24.8_
    - Note: written against the interface before D111 (`Plugin`, `skye.use`); `examples/plugins/` was rewritten for D111 and task 21.1 makes it pass.
  - [x] 1.2 Add the example to `tests/examples`, marked expected-to-fail until task 4 is done, then unmarked by the task that makes it pass
    - _Requirements: 61.1, 24.11_
    - Note: task 21.1 removes the marker when the examples pass.
- [x] 2. Ports and registrar in `base`
  - [x] 2.1 `PluginInterface` as a `Protocol` with `name` and `register(registrar)`; remove `initialize`, `shutdown` and `get_metadata`;
    keep the name exported by `skye.interfaces` (depends on O61, option A)
    - _Requirements: 56.1; D37_
    - Note: built against the interface before D111; `PluginInterface` goes in task 13.4.
  - [x] 2.2 `RegistrarInterface` with the eleven methods of Requirement 56.2, each `(name, target, *, replace=False)`, and `profile=`
    on `model_provider` and `embedding_provider`; the docstring footer of a Port (error contract)
    - _Requirements: 56.2, 59.7, 16.8_
    - Note: built against the interface before D111 (eleven methods); the nine kinds are tasks 13.1 to 13.3 and the single `provider` is task 15.2.
  - [x] 2.3 `base/plugins.py`: `Registrar` with one in-memory table per kind, `get(kind, name)`, `names(kind)`, the default registrar;
    no file, no thread
    - _Requirements: 56.3; D27_
    - Note: built against the interface before D111; the handle `skye.Plugins` over this registrar is task 14.1.
  - [x] 2.4 Duplicate names and profiles: `ConfigurationError` naming the kind and the name, `replace=True` overrides; the same profile
    given twice is accepted
    - _Requirements: 56.4, 59.8_
  - [x] 2.5 `"module:attribute"` targets imported at the first use of the name, never at registration; a text that does not import
    raises `ConfigurationError` with the cause
    - _Requirements: 56.5_
  - [x] 2.6 Tests in `tests/unit/plugins/test_registrar.py`: each kind, duplicates, `replace`, lazy text targets, a private `Registrar()`
    that leaves the default untouched; the Port compliance test gains the pair `Registrar` / `RegistrarInterface`
    - _Requirements: 56.1 to 56.5, 16.7_
    - Note: the tests are updated by tasks 13.1 to 13.4 and 14.4 for the new kinds and the handle.
- [x] 3. The provider profile in `base`
  - [x] 3.1 `base/profile.py`: `ProviderProfile`, `ModelProfile`, `RegionRule` as frozen dataclasses with the fields of Requirements 59.1
    and 59.2; mappings frozen; prices and overhead validated (0 or more)
    - _Requirements: 59.1, 59.2_
  - [x] 3.2 `find_model_profile`: exact name, then the longest registered name followed by a date or version suffix; tests that
    `gpt-4o` never matches `gpt-4` and that dated and Bedrock-versioned names find their family
    - _Requirements: 59.4_
  - [x] 3.3 `resolve_region`: passed, authenticator, variables in order; `ConfigurationError` naming the variables when a required
    region is missing; no default region
    - _Requirements: 59.5, 59.6_
  - [x] 3.4 Property tests: a lookup never raises for a missing profile or model (cost `None`, the estimate for tokens)
    - _Requirements: 59.10_

- [x] 4. Discovery and control
  - [x] 4.1 `utils/plugins.py` `discover(registrar)`: `importlib.metadata.entry_points(group="skye.plugins")`, each entry point loaded and
    passed to `use`; the report (`PluginReport`) kept for the command and the errors (depends on O60, option A)
    - _Requirements: 57.1_
    - Note: built against the interface before D111: it passes each entry point to `use`; task 4.5 makes it import the module that the entry point names.
  - [x] 4.2 The registrar imports `"skye.utils.plugins:discover"` by text at the first miss, scans once per process and looks again
    once; `import skye` scans nothing (a fake entry point that raises on load proves it)
    - _Requirements: 57.1, 57.2, 57.3, 7.8, 7.9_
  - [x] 4.3 The `plugins` key of the configuration file, read with `load_config` (D91): only the listed entry points load; without the
    key, all; the key returns to the configuration schema and its documentation (D106 removed it while no code read it)
    - _Requirements: 57.5; D91, D106_
  - [x] 4.4 Failures: an entry point that fails to load or whose module raises is logged once at WARNING with `extra` (entry point,
    distribution, error) and skipped; an unknown name after the scan raises `ConfigurationError` listing the names of the kind and the
    failures
    - _Requirements: 57.6, 57.7; D105_
  - [x] 4.5 An entry point is a module (D111): `discover` loads the entry point, which imports the module it names, and the decorators in the
    module register; `use_plugin`, the `register` call on a plugin object and the lazy name `skye.use` are removed; the report keeps the names
    registered per kind; importing the module in the program registers the same way, so the entry point is a convenience
    - _Requirements: 57.1, 57.4, 57.8, 7.8; D111_
  - [x] 4.6 `skye plugins [--format json]` in `utils/cli.py`: built-in registrations and each entry point (name, distribution, version,
    loaded or failed with the error, names per kind)
    - _Requirements: 57.9_
  - [x] 4.7 Tests in `tests/unit/plugins/test_discovery.py` with a fake `entry_points`: an entry point that is a module, one scan per
    process, allowlist, failing entry point, error after the scan, the module imported by the program, the command in text and JSON
    - _Requirements: 57.1 to 57.9_
- [x] 5. Built-in providers through the registrar, with their profiles
  - [x] 5.1 `models/plugins/` (`register`): every built-in model and embedding provider registered by text with its `ProviderProfile`, read from
    a `profile.toml` (`profile_from_mapping` in `base`) (key
    variables, region rule, default endpoint, client settings, model profiles with prices, tokenizer, overhead and `info`, `map_error`)
    - _Requirements: 56.6, 59.1, 59.7_
    - Note: built against the interface before D111: it registers with `model_provider` and `embedding_provider`; task 15.2 moves them to `provider`.
  - [x] 5.2 `ProviderRegistry` becomes a view of the registrar: same methods and signatures, no table of its own; `skye.provider(name)`
    reaches third-party providers through the lookup
    - _Requirements: 56.7_
    - Note: built against the interface before D111; `ProviderRegistry` reads the single `provider` kind after task 15.2.
  - [x] 5.3 An OpenAI-compatible endpoint registered with `OpenAICompatibleProvider` and a profile, and no class; a test that calls it
    offline through a fake transport
    - _Requirements: 59.9_
    - Note: built against the interface before D111; the registration reads `plugins.provider(...)` after task 15.2.
  - [x] 5.4 The D109 list of Claude models that refuse a forced choice moves into the Anthropic and Bedrock model profiles
    (`info["supports_forced_capability_choice"]`); `refuses_forced_choice` reads `get_model_info()`; the two adapter tuples and their
    parity test go
    - _Requirements: 60.7; D109_
  - [x] 5.5 The `models/plugins/` layout (D110): one folder per provider (`openai`, `anthropic`, `bedrock`, `azure`, `google`, `cohere`,
    `typesafe`), each with an `__init__.py` that is the only door (lazy names, `register`), the code in `provider.py`, `embeddings.py`,
    `multimodal_embeddings.py` or `decision.py`, and the data in `profile.toml`; `llm/`, `embeddings/` and `decision/` removed;
    `decision.py` (`create_decision_model`) in the root of `models`; `profile_from_mapping` in `base`;
    `tests/unit/plugins/test_layout_models.py`; the name and the URL of TypeSafe AI in the docstring of Jev
    - _Requirements: 56.9, 56.10; D110_
  - [x] 5.6 Separate the call logic of each provider by responsibility, with the same file names in every folder: `provider.py` (the class:
    constructor, the calls, model info; thin), `request.py` (how the request is built), `response.py` (how a response and a stream chunk are
    read) and `capabilities.py` (capabilities out and back); applied to `bedrock`, `google` and to the two wire-format bases
    (`openai_compatible`, `anthropic_compatible`), which became packages; the class keeps its method names as thin wrappers, behaviour and
    public names unchanged
    - _Requirements: 56.9, 56.10; D110_
  - [x] 5.7 The facts of a model out of the adapters and into `profile.toml`: `info.vector_dimension` for the embedding models of `openai`,
    `bedrock`, `cohere`, `google` and the multimodal one (`MODEL_DIMENSIONS` and `VECTOR_DIMENSION` removed), `default_api_base` for the OpenAI
    embeddings and Cohere (`DEFAULT_API_BASE` and the host of `COHERE_EMBED_URL` removed); `BaseEmbeddingProvider` reads them from the profile of
    its provider; a test that the values equal the old constants and that a plugin declares its own
    - _Requirements: 59.1, 59.2, 60.3; D110_
  - [x] 5.8 `models/utilities/` (D110): `base.py`, `openai_compatible/`, `anthropic_compatible/` and `transport/` moved from the root of
    `models`, since they are what a plugin is written with and are not registered; the old paths removed, the public names unchanged, the
    budget tests (families, extras) on the new paths, no transitional code left; every path cited in steering, specs and docs updated;
    `mypy` clean on `models`
    - _Requirements: 56.9, 56.10; D110_
  - [x] 5.9 The toolkit of `models/utilities/` as plain modules and not groups: `transport/` dissolved into `rest`, `streaming`, `eventstream`,
    `retry`, `error_mapping`, `structured`, `schema_check`, `capability_choice`, `prompt_parts`, `multimodal` and `credentials`, directly in
    `utilities/`; the classes of the component itself back in the root of `models` (`base.py`, `cost.py`, `token_counter.py`); the unused
    re-export `transport/http.py` removed (the HTTP client is `base/http.py`); every import, patch target, `map_error` text and cited path
    updated, the budget tests on the new paths; the specs of finished work (`0-base-structure`, `0-base-uxui`) keep the paths of their time
    - _Requirements: 56.9, 56.10; D110_

- [x] 6. Provider knowledge in one place
  - [x] 6.1 `CostCalculator` without `PRICING`: prices from the profiles, `add_custom_pricing` as a user layer that wins,
    `get_pricing`, `pricing_for`, `list_models` unchanged for the caller
    - _Requirements: 60.1, 59.3_
  - [x] 6.2 `TokenCounter` without prefixes, tokenizers or overheads of its own: `tokenizer` and `message_overhead` from the
    `ModelProfile`; `register_tokenizer` registers a tokenizer by name through the registrar (coordinate with the token-counter work of
    `1-adapters-models`)
    - _Requirements: 60.2, 59.3_
  - [x] 6.3 One home for API-key variables: remove `STANDARD_ENV_VARS` (`auth`), `API_KEY_VARIABLES` (`router/skye_file.py`) and the
    names written in the adapters; all read `api_key_variables` of the profile; the variable names stay the provider-standard ones
    - _Requirements: 60.3, 11.6_
  - [x] 6.4 The router applies `client_settings` and `model_is_deployment` of the target's profile; the Azure branch of
    `router/model_router.py` goes; the router contains no provider name
    - _Requirements: 60.4_
  - [x] 6.5 Error handlers into their adapter modules, referenced by `map_error`; `gemini_schema` into the Google adapter;
    `models/utilities/error_mapping.py` keeps the HTTP-status mapping of D104 and calls `map_error`
    - _Requirements: 60.5; D104_
  - [x] 6.6 The AWS region through `resolve_region` in `auth/plugins/aws/source.py`, `auth/plugins/aws/sts.py`, `models/utilities/credentials.py` and the store
    backends that need one; the `us-east-1` defaults go; DynamoDB passes the region found and leaves the boto3 chain last (depends on
    O63, part 2, option A)
    - _Requirements: 60.6, 59.6_
  - [x] 6.7 Bedrock reads its native-JSON-output capability from `get_model_info()`; `_native_json_output` goes
    - _Requirements: 60.7_
  - [x] 6.8 `tests/budget/test_provider_knowledge.py`: a built-in provider name, a key variable or a price as a literal outside the
    adapter and profile of that provider fails; an allowlist that only shrinks
    - _Requirements: 60.8_

- [x] 7. The other registries as views
  - [x] 7.1 `store/plugins/` (`register`) and `register_backend` as a view (the `_BUILTIN` table becomes registrations by text)
    - _Requirements: 56.6, 56.7_
    - Note: built against the interface before D111; the kind `store_backend` is `backend` after task 13.1.
  - [x] 7.2 `auth/plugins/` (`register`) and `register_credential_source` as a view (`BUILTIN_SOURCES` becomes registrations by text)
    - _Requirements: 56.6, 56.7_
  - [x] 7.3 `CapabilityRegistry`, `register_agent_type` and `TokenCounter.register_tokenizer` as views; the registrar holds the default
    set of capabilities and prompt filters, and a registration on a builder or registry instance stays local;
    the built-in agent type `react` lives in `agents/plugins/react/`
    - _Requirements: 56.7, 56.8_
    - Note: built against the interface before D111: the registrar default set of capabilities goes in task 13.2 and the kind `agent_type` is `agent` after task 13.1; the default set of template filters stays.
  - [x] 7.4 A test that every call to a registry of today works as before (one case per registry)
    - _Requirements: 56.7_
  - [x] 7.5 The `store/plugins/` layout (D110): one folder per backend (`memory`, `file`, `dynamodb`, `redis` with the name `valkey`,
    `postgres`, `durable_function`), each with its `__init__.py` as the only door and `backend.py`; `_common.py`, `conformance.py` and
    `factory.py` stay in the root; `tests/unit/plugins/test_layout_store.py`; no driver imported before the backend is used
    - _Requirements: 56.9, 56.10; D110_
  - [x] 7.6 The `auth/plugins/` layout (D110): one folder per family of credential sources (`aws` with `aws_profile`, `sts` and `sigv4`,
    `google`, `azure`, `oauth2`, `openai_compatible`, `secrets`), each with its `__init__.py` as the only door and `source.py`; what several
    families use (`cache`, `refresh`, `errors`, `rsa_signing`) stays in the root; `registry.py` stays a view;
    `tests/unit/plugins/test_layout_auth.py`
    - _Requirements: 56.9, 56.10; D110_
  - [x] 7.7 The `tools/plugins/` layout (D110): the MCP clients `builtin` and `fastmcp`, each with its `__init__.py` as the only door and
    `client.py`, `fastmcp` imported only when chosen; `MCPClientInterface`, `MCPToolCapability` and `create_mcp_client` stay in the root;
    `tests/unit/plugins/test_layout_tools.py`
    - _Requirements: 56.9, 56.10; D110_

- [x] 8. Storage knowledge in one place
  - [x] 8.1 `CounterStore.count(key)` on the Port and in all six backends; `check_backend` checks it
    - _Requirements: 60.9; D98_
  - [x] 8.2 `ExpiryStore` (`is_alive`, `remaining`) beside the Protocols of D98, in every backend that stores an expiry; the
    conformance suite checks it with `FakeClock`
    - _Requirements: 60.10; D95, D98_
  - [x] 8.3 The router: counters through `count`, cooldown as a key with a `ttl` read through `ExpiryStore`, no `time.time()`
    comparison, default store from `skye.store.backend("memory")`; router tests driven by `FakeClock`
    - _Requirements: 60.9, 60.10, 60.11; D97_
  - [x] 8.4 `store.namespaced(store, prefix)` and the router on the namespace `router` (depends on O63, part 1, option A)
    - _Requirements: 60.10_
  - [x] 8.5 `tests/budget/test_storage_knowledge.py`: the import of a concrete backend class outside `store` and its tests fails, and so
    does reading the key `"count"` of a stored value outside `store`
    - _Requirements: 60.12_

- [x] 9. The closed kinds
  - [x] 9.1 Routing strategies by name through the registrar; the eight built-ins registered in `router/plugins/`; every
    `RoutingStrategy` member still works; the `if`/`elif` chain goes; the `.skye` checker accepts a registered name in `strategy`
    - _Requirements: 58.1_
  - [x] 9.2 MCP clients by `impl` name through the registrar; `"builtin"` the default; `"fastmcp"` registered by text and imported only
    when chosen
    - _Requirements: 58.2, 10.7; D16_
  - [x] 9.3 Decision models by name through the registrar; Jev registered as a built-in
    - _Requirements: 58.3, 9.8_
    - Note: built against the interface before D111; the decision model is a provider with the function `decide` after task 15.2.
  - [x] 9.4 A test with a third-party strategy, MCP client and decision provider registered with `plugins` decorators
    - _Requirements: 58.1, 58.2, 58.3_
- [x] 10. Conformance per kind
  - [x] 10.1 One public `check_<kind>` per kind, next to its owner, offline against fakes, returning the names of the checks passed and
    raising on the first failure: `check_provider` (the checks of the function the class has: model, embedding or decision), `check_credential_source`,
    `check_routing_strategy`, `check_mcp_client`, `check_tokenizer`, `check_template_filter`, `check_agent`, `check_toolkit` (store: `check_backend`
    exists)
    - _Requirements: 58.4; D98, D111_
  - [x] 10.2 One parametrized test runs every built-in registration of every kind through its function
    - _Requirements: 58.5_

- [x] 11. Documentation, skill and budgets
  - [x] 11.1 The guide "Write a plugin" and a reference of `ProviderProfile` in the wiki, with snippets from `examples/plugins/`; the extension
    page (`docs/guides/extend/index.md`) lists the decorator of each kind (the pages written before D111 are redone by task 21.3)
    - _Requirements: 61.2, 15.10_
  - [x] 11.2 The Claude skill that ships with the package: `skye plugins`, `skye.Plugins`, the `plugins` key, the registrar and the profile;
    an eval for the rule that a provider is declared once, in its profile
    - _Requirements: 61.3_
  - [x] 11.3 No third-party dependency and no extra added; size, import time and cold start of `budgets.toml` not higher
    - _Requirements: 61.4, 7.9; D27_

- [x] 13. The nine kinds (D111)
  - [x] 13.1 Rename `store_backend` to `backend`, `agent_type` to `agent` and `prompt_filter` to `template_filter` in `KINDS`,
    `RegistrarInterface`, `Registrar` and the views (`register_backend`, `register_agent_type`, the prompt builders); the tests of the old
    names are updated
    - _Requirements: 56.2, 56.8, 56.11; D111_
  - [x] 13.2 Remove the kind `capability` and the default set of capabilities of the registrar (`default_set("capability")`, and what
    `CapabilityRegistry` reads from it); `CapabilityRegistry` keeps its name, its place and its namespaces and is no view of the registrar; the
    default set of template filters stays; tests that a registry starts empty
    - _Requirements: 62.1, 56.8; D111_
  - [x] 13.3 Add the kind `toolkit` to the registrar (the table and the method, no built-in yet); tests in `test_registrar.py` for the nine
    kinds, and the Port compliance test for `Registrar` and the nine-method `RegistrarInterface`
    - _Requirements: 56.2, 62.5; D111_
  - [x] 13.4 Remove `PluginInterface` (the Protocol, its export from `skye.interfaces`, its docstring and tests) and the register-on-a-plugin
    path of `utils/plugins.py` that used it; the module docstring of `base/interfaces/plugin.py` describes `RegistrarInterface` only
    - _Requirements: 56.1; D111, D37_

- [x] 14. `skye.Plugins` (D111)
  - [x] 14.1 The class `Plugins` in `base/plugins.py`: a handle on the default registrar with no table of its own; one method for each kind that
    registers when it has the name and the target, and returns a decorator when it has the name only; the decorator returns the object it
    decorates; `replace=False`, `profile=` on `provider` and `tools=` on `toolkit` are taken
    - _Requirements: 56.1, 56.2, 62.5; D111_
  - [x] 14.2 Registration at once, from any part of the program: a write to a table takes a lock and a read does not; a test that registers from
    a function, a method and several threads and finds the names at once
    - _Requirements: 56.6_
  - [x] 14.3 `Plugins` as a lazy name of `skye/__init__.py` and in the `skye.plugins` facade; the exports count test and the public-imports test
    are updated (D34)
    - _Requirements: 56.1, 7.8; D34_
  - [x] 14.4 Tests in `tests/unit/plugins/test_plugins_handle.py`: a decorator and a direct call for each kind, two handles see one table, a
    duplicate raises and `replace=True` overrides, `unregister` removes, the decorated class stays usable
    - _Requirements: 56.1, 56.2, 56.3, 56.4, 56.6_

- [x] 15. One `provider` kind (D111)
  - [x] 15.1 The function of a `provider` from the method of the class (`generate`, `encode`, `decide`); the table keyed by name and function; a
    class with the methods of two functions raises `ConfigurationError`; the call that registers a text target gives the function, and the
    argument is chosen here and written in `design.md` (the text is not imported at registration)
    - _Requirements: 56.12_
  - [x] 15.2 The tables `model_provider`, `embedding_provider` and `decision_model` become the kind `provider`; `ProviderRegistry`,
    `create_decision_model` and `create_embedding_provider` read it; every built-in registration of `models/plugins/` uses `provider`; the
    layout tests of `models` are updated
    - _Requirements: 56.12, 56.8, 58.3; D111_
  - [x] 15.3 `skye.provider(name)` builds a model provider, and `provider_type="embedding"` and `provider_type="decision"` the others, from the
    single kind
    - _Requirements: 56.11, 56.12_
  - [x] 15.4 One profile for one provider name, kept under its own `name`, whatever the functions registered; the price of Jev in
    `typesafe/profile.toml`, registered with the decision provider and read by the `CostCalculator`; a test that a chat class and an embedding class
    of one name share one profile and that a different second profile raises
    - _Requirements: 59.7, 59.8, 59.12, 58.3; D110, D111_
  - [x] 15.5 Tests: a class of two functions is an error, one name with two classes, a text target with its function, a decision provider
    built through `skye.provider(name, provider_type="decision")` and through `create_decision_model`
    - _Requirements: 56.12, 58.3_

- [x] 16. One word to add and to build (D111)
  - [x] 16.1 The builders as lazy names of `skye/__init__.py`: `skye.agent` (a view of `create_agent`; `REACT` stays in `skye.agents`),
    `skye.backend`, `skye.mcp_client`, `skye.credential_source`, `skye.routing_strategy`, each reading the table of its kind; the exports count test
    is updated (D34)
    - _Requirements: 56.11, 62.9; D34, D111_
  - [x] 16.2 `plugins.names(kind_word)` and `plugins.get(kind_word, name)` on `Plugins`, with the word of the kind (`plugins.names("agent")`,
    `plugins.get("toolkit", "openapi")`); an unknown word raises `ConfigurationError` listing the kinds
    - _Requirements: 56.11_
  - [x] 16.3 Tests: for each kind the word of the decorator is the word of the builder, and what a decorator registers is found by the builder and
    by `names`
    - _Requirements: 56.11, 62.9_

- [x] 17. The profile of an existing provider and the tokenizer by name (D111)
  - [x] 17.1 `plugins.profile(provider, models={model: ModelProfile(...)})` merges the given model entries into the profile of an existing
    provider and changes nothing else (depends on O72: what merges, the error for an unknown provider or model)
    - _Requirements: 59.11; D111_
  - [x] 17.2 A tokenizer is registered by name (`plugins.tokenizer`) and a model uses one only through `ModelProfile(tokenizer=...)`;
    `TokenCounter.register_tokenizer` by prefix is a lower-level call outside the plugin interface (its fate is open in O72)
    - _Requirements: 59.11, 59.3; D111_
  - [x] 17.3 Tests: a change of the tokenizer of `gpt-4o` leaves `gpt-4o-mini`, the prices and the endpoint as they are; a new provider names its
    tokenizer in its profile; a model with no tokenizer gets the estimate
    - _Requirements: 59.11, 59.10_

- [x] 18. Toolkits (D111; the loop and the content are other specs and O70)
  - [x] 18.1 `LocalFunctionCapability` as a descriptor (`__get__` binds it to the instance) and a schema that skips `self`, so that
    `@capability` works on a method (open in O70: `__call__` and the early check of the schema)
    - _Requirements: 62.2, 62.5_
  - [x] 18.2 `skye.Toolkit` in `tools`: a `ToolProvider` that collects the methods of its class marked with `@capability`, adds the prefix
    `<toolkit name>.<name>`, and takes an `alias` when one toolkit is built twice
    - _Requirements: 62.5_
  - [x] 18.3 `tools=[...]` in the `toolkit` decorator and in the call with no class (`plugins.toolkit("text", tools=[...])`), and a function that
    returns a `CapabilityRegistry`; a clash of two prefixed names raises `ConfigurationError` naming both
    - _Requirements: 62.5_
  - [x] 18.4 `skye.toolkit(name, **options)` builds a toolkit; `replace=True` replaces a built-in one; `plugins.get("toolkit", name)` returns its class so
    that a plugin builds on it
    - _Requirements: 62.6, 56.11_
  - [x] 18.5 `@capability` takes `name`, `description` and `return_direct` (the name defaults to the function name and the description to its
    docstring); the flag is kept on the capability and the loop that uses it is the agents spec (Requirement 62.3, O70)
    - _Requirements: 62.2_
  - [x] 18.6 Tests in `tests/unit/tools/test_toolkit.py`: methods with `@capability`, the prefix, `alias`, `tools=[...]`, the function that returns a
    registry, `self` out of the schema, a toolkit that is built by name and replaced
    - _Requirements: 62.5, 62.6_

- [ ] 19. The built-in toolkits as plugins (D111; the content of each is open in O70)
  - [x] 19.1 `tools/plugins/files/`: registered by text as the toolkit `files`; the option `root` is required and nothing outside it can be read
    - _Requirements: 62.7_
  - [x] 19.2 `tools/plugins/openapi/`: registered as the toolkit `openapi` with the option `spec`
    - _Requirements: 62.7_
  - [ ] 19.3 `tools/plugins/mcp/`: registered as the toolkit `mcp` with the option `target`, on top of an MCP client ON HOLD until O80 is decided; the code is parked outside the repository.
    - _Requirements: 62.7_
  - [ ] 19.4 The toolkits `skyea2a` (the agent-to-agent protocol on the standard library, as `skyemcp` is for MCP) and `a2a` (on the official SDK, imported ON HOLD until O80 is decided; the code is parked outside the repository.
    only when used): the base only (the door, the class, the four tools `describe_agent`, `send_message`, `get_task`, `cancel_task`, the options `url`,
    `headers`, `timeout`); what is not done is listed as issues for contributors (`docs/_notes/toolkit-issues.md`); none of the toolkits is active unless the
    user asks for it or a feature of the agent needs it; `IMPLEMENTATIONS` of `tools/plugins/` lists the MCP clients and the toolkits; `test_layout_tools.py`
    is updated
    - _Requirements: 62.7, 56.9_
  - [x] 19.6 The toolkit `shell`, the base only (opt-in: an allow list of executables is required, no shell, a time limit, a cut of the output, a Restored and registered after the O80 parking (it is not part of O80).
    working folder, a minimal environment); the rest is listed as issues for contributors
    - _Requirements: 62.7_
  - [x] 19.7 The toolkit `human` for escalations, the base only (the agent asks a person a question, or hands a case over; the way to reach the person is
    a pluggable channel: `console`, `file` (JSON files in a folder, polled) and the Protocol for the others); the rest is listed as issues for contributors
    - _Requirements: 62.7_
  - [x] 19.5 The seam for the skills: an agent that is given a `SKILL.md` asks the registrar for the toolkit `files`, limited to the folder of the
    skill, and never imports `tools`; the skill itself and the loop are the agents spec
    - _Requirements: 62.8_

- [x] 20. Async only for the plugin author (D111)
  - [x] 20.1 `run_sync(coroutine)` and `iterate_sync(async_generator)` in `base`: the first runs on a worker thread when a loop is already
    running; the second runs the generator on its own loop in one thread, with a bounded queue, raises the error in the caller and closes the
    generator when the caller stops; tests for a running loop, an error in the middle and an early stop
    - _Requirements: 56.13_
  - [x] 20.2 The model base classes derive `complete` and `stream` from `acomplete` and `astream`; the parallel sync paths go and the adapters
    write only the async methods (depends on O68)
    - _Requirements: 56.13_
  - [x] 20.3 The embedding base class derives `encode` and `encode_batch` from `aencode` and `aencode_batch`; the example embedding provider writes
    two methods; tests
    - _Requirements: 56.13_

- [x] 22. The name of the built-in MCP client (D112)
  - [x] 22.1 The built-in MCP client is called `skyemcp` and no longer `builtin`: the registered name, the default `impl` of
    `create_mcp_client`, the folder `tools/plugins/builtin` (now `tools/plugins/skyemcp`, with its door and `client.py`), the class
    `BuiltinMCPClient` (now `SkyeMCPClient`, exported by `skye.tools`), `IMPLEMENTATIONS` in `tools/plugins/__init__.py`, the tests, the examples
    and the docs and specs that name it; the old name is not kept as an alias
    - _Requirements: 58.2; D16, D110, D112_

- [x] 23. Strategies that read the request (D113)
  - [x] 23.1 `StrategyContext` in `router`: a frozen, read-only dataclass with the models, the alias, the token estimate, the request and the
    snapshot of the metrics; `RouterStrategy.select(context)` for the built-ins, a plain function keeps `(models)` and one that wants the context is
    marked with `with_context`; the two call sites of `ModelRouter` pass the request; the eight built-ins and their tests move to the context
    - _Requirements: 58.1, 58.7; D113_
  - [x] 23.2 The built-in strategy `lazy_complex`, deliberately naive: the models of a route are ordered from the cheap one to the strong one, a
    long prompt, a tool or a response schema raise the level, and the level picks the model; registered in `router/plugins/`; the `.skye` checker
    and the docs accept it
    - _Requirements: 58.1, 58.7; D113_

- [ ] 24. Size and load time of the installed package (O77, O78; the owner approved the proposal on 2026-11-12)
  - [x] 24.1 A script that reports the size of the installed package by component and by kind (code, docstrings, comments, data files) against
    `[core]` of `budgets.toml`, and the rule that every wave ends with it (written in the Notes of this file): `make size`, with a test that
    the figures add up to the measured install
    - _Requirements: 61.4; O77_
  - [ ] 24.2 ON HOLD until the owner decides O77 (installing the skill and the extension from the public repository may replace it): `utils/claude_skill` and `utils/vscode_extension` stay plain files in the repository; the build puts one `zipfile` archive of each in
    the wheel (the built `.vsix` for the extension, which is a zip); `skye skill` and `skye vscode` read the archive in an installed package and the
    folder in a source checkout; a test of the round trip and one that runs the commands against the wheel
    - _Requirements: 61.4; O77_
  - [x] 24.3 The comments are removed from the wheel at build (a hook of the build backend, stdlib only): from the Python files with the standard-library
    `tokenize` (the line numbers stay, a shebang and a coding line stay) and from the bundled `.skye` templates with the lexer of the language (the `#`
    and `/* ... */` comments, 40 KB in 87 blocks that hold usage examples; a string that holds `/*` is kept; the front matter is kept); the sdist and
    the repository keep the comments; a test that the wheel has no comment and that every bundled template builds to the same objects with and without
    its comments
    - _Requirements: 61.4; O77_
  - [x] 24.4 The references to requirements, decisions and tasks move from the docstrings to comments (docstrings only say what the library does);
    a budget test that forbids the patterns in docstrings, with a list of exceptions that only shrinks; no cap of docstring bytes
    - _Requirements: 61.4; O77_
  - [ ] 24.5 The `include` of the `.skye` language is implemented and documented (D116, `docs/_notes/include-design.md`): the work is the tasks 25.1 to 25.6; this task
    is closed when they are and when the bundled templates are migrated (24.6)
    - _Requirements: 63.1 to 63.17; D116_
  - [x] 24.6 The bundled `.skye` templates use `include` and `from ... import` for what 2 or more files repeat (five partials: `system_prompt`, `tools`, the memories and two small groups, 93% of the gain; 33% of their bytes are in repeated lines); the output of
    each template does not change (a test renders every template before and after)
    - _Requirements: 63.14, 63.16, 61.4; D116_
  - [x] 24.7 The bundled templates are one `zipfile` archive made at build and read by name (opened at the first read, never at `import skye`); a
    source checkout reads the folder; `skye prompt export` writes them out; a test of both paths
    - _Requirements: 61.4; O77_
  - [x] 24.8 A bundled template is compiled at its first use (the builder registers the names and the versions only): `BasePromptBuilder()` costs
    under 10 ms; a cache of the compiled bundled templates for the process (immutable entries); the build of a bundled template skips the validation
    of the objects (a context that `validate_instance` reads), guarded by a test that the build with and without validation gives equal objects for
    all the bundled templates; a template of the user is validated when it is registered; a row in `budgets.toml` for the construction of a builder
    - _Requirements: 61.4; O78_
  - [x] 24.9 The comments inside the bundled `.skye` templates go: the examples (the `/** Example: builder.render(...) **/` blocks, 87 in 40 files) move to `examples/prompts/bundled/` as one data file per template with its sample variables, with one example `examples/prompts/bundled_templates.py` that renders each bundled template from them; the explanatory comments (block and `#` lines) are removed and not moved (a copy of what was removed is kept in `docs/_notes/skye-comments-removed.md`, which git ignores); the front matter (`title`, `description`, `version`, `tags`) stays; the sample files are the single source of the render checks of 24.6; the output of every template does not change
    - _Requirements: 61.4, 63.16; O77_
  - [x] 24.10 The catalogue of bundled templates is reduced (owner, 2026-11-13): `structured_output_json`, `structured_output_table` and `structured_output_xml` go (`structured_output` already takes `format`); the pairs `main_agent` and `memory_agent` (the second takes a subset of the variables of the first), `code_agent` and `code_generation`, and `chain_of_thought_agent` and `reasoning_agent` are each evaluated as one template with options and variables, and merged when the render of the options that replace the old template equals the old render (a test per merged template); tests and pages that name a removed template are updated; the renames are decided by the owner (2026-11-13): `ner` to `entity_extraction`, `tabular_extraction` to `table_extraction`, `main_agent` and `memory_agent` to one `memory_assistant`, `memory_update_agent`/`memory_consolidation_agent`/`working_memory_agent` to `memory_update`/`memory_consolidation`/`memory_working`, `tree_of_thoughts_agent` and `self_reflection_agent` to `reasoning_tree_of_thoughts` and `reasoning_self_reflection`, `smol_planning` to `smol_planning_agent`; the three merges (`main_agent`/`memory_agent`, `code_agent`/`code_generation`, `chain_of_thought_agent`/`reasoning_agent`) are approved when the render with the options equals the old render; no other merge is planned: two templates are merged only when they are the same job with options, never to force a `mode` on different jobs (owner, 2026-11-13: the families supervisor, groupchat, smol, reasoning beyond the approved pair, tool and procedure, extraction and text stay as they are); the memory agents end as two templates (owner, 2026-11-13): `agent_memory_assistant` (conversational, absorbs `agent_memory_recall`) and `agent_memory_maintenance` with a `mode` (`update`, `consolidate`, `working`) that replaces `agent_memory_update`, `agent_memory_consolidation` and `agent_memory_working`; the parts activate by `mode` and the JSON answer is a conditional `output` block per mode, with the renders of each old template reproduced by its mode (intended changes listed); the variables of the templates are unified (one name per idea, `docs/_notes/template-variables-unification.md`) and the answer format of every template is written with the `output` block of the language through one shared partial (`output_format` and `output_schema`) instead of a hand-written format text in 16 templates (owner, 2026-11-13: `chat` still has a free-form format while the structured one exists); the free-form style of an answer stays a separate text variable; the parts the agent templates share besides the memories, the tools block and the system prompt (the `## Constraints` section, the `## Tools` listing in its three variants, the task block `## Task` and its variable, the examples as user and assistant turns, the transcript and progress sections of the supervisor and group chat families) are unified to one wording and moved to the shared partials of step 2 (`common/io.skye` and, for the agents, `common/agent.skye`) where the pairing rule allows it; the one-off context variables become generic reusable ones (owner, 2026-11-13: no code-specific optional variables such as `database_schema` and `database_type`): `context` (background text, for `code_context`, `additional_context`, `domain_knowledge`), `references` (a list of named items with an optional description and a content, for `database_schema`, `table_schema`, `documents` and the files of `code_context`) and `environment` (the dialect, runtime or version, for `database_type` and the runtime of a language); `generation_sql` becomes a case of `generation_code` through them, with a thin template over a shared partial and an `override` of the language, or no template of its own (the owner chooses) DONE as step 1: the three `structured_output_*` removed and the templates renamed to `scope_detail` (every agent `agent_*`); the three merges were refused because no merge reproduces the old render; the steps 1b, 2 and 3 are not planned (D118: 26 templates left the bundle) and are done on the gallery only if the owner asks
    - _Requirements: 61.4; O77_
  - [x] 24.11 The bundled prompts are reduced (D118, owner 2026-11-13): the 26 templates other than `generation_*`, `extraction_*`, `text_*` and the ReAct agent prompt (`agent_smol_tool_calling` renamed `agent_react`) move to `examples/prompts/catalogue/` with their sample variables (a gallery with one runner example that lists and renders them offline, and a test that every file passes `skye check` and renders; the files that use a shared partial carry their own copy of `common/`); `src/skye/prompts/templates/` keeps `common/` and the 11 kept templates; the comments inside the templates go (the examples already moved to `examples/prompts/bundled/` in 24.9; the explanations are removed and kept in a local note); every test, page, example and the skill that uses a moved template by name uses the gallery; Requirement 30.14 and the specification `2-services-prompts` are amended; the steps 1b, 2 and 3 of 24.10 are done only if the owner asks; the gallery also holds `extraction_generic` (one prompt for entity, relation and table extraction, with three sample files), 27 files in all
    - _Requirements: 61.4; D118_
  - [ ] 24.12 `generation_code` and `generation_sql` become one bundled template `generation_code` (owner, 2026-11-13): SQL is a case of code generation through generic variables and not through variables of its own: `language` (`"SQL"` for SQL), `input` (what to generate), `description`, `requirements` and `constraints` (one list), `references` (a list of named items with an optional description and a content, for the tables of a schema, files or documents), `environment` (the dialect, runtime or version, for the SQL dialect or the runtime), `examples` (`input` and `output`), `input_format`, the answer through the `output` block (`format` json, table, xml or text) and `include_tests` and `include_comments`; the renders of the two old templates are reproduced by their options except the intended changes (the system sentence follows the language, the sections follow one layout), listed in a test with the old and the new text; the tests, pages, examples and the skill that name `generation_sql` use `generation_code` with `language` set; done after 24.11
    - _Requirements: 61.4; D118_

- [ ] 25. The `include` of the `.skye` language (D116)
  - [x] 25.1 Lexer, parser and syntax tree (`src/skye/base/dsl`): `include "path" as alias`, `from "path" import a, b as c`, `use name` and `use alias`
    in a `variables` body, a prompt body and a message body; the words `from`, `import`, `use` and `partial` (the front matter key); the expansion
    in `build` before the validation with a resolver given to `build` and `check_text`, the kind taken from the place, the pairing of a name with
    its text, the limits (64 includes, 1 MB) and the cycle; the origin (file, line, column) kept on every node that comes from a partial; `base`
    does no file I/O (the budget test passes); tests for each rule of Requirements 63.1 to 63.10 and 63.13
    - _Requirements: 63.1, 63.2, 63.3, 63.4, 63.5, 63.6, 63.7, 63.8, 63.9, 63.10, 63.13; D116_
  - [x] 25.2 Errors and diagnostics: the messages of the table of errors of the note (a name that does not exist with the names that do, a name not imported,
    a kind that does not fit the place, a name imported twice, an alias used twice, an `include` without `as`, a duplicate with both origins, a name with an
    entry and no text, a `use` inside a partial); `via` in `Diagnostic` and in the JSON of `skye check` (optional, the keys that exist do not change); the
    check of the variables of the expanded tree (an undeclared variable read by brought text is reported with its origin)
    - _Requirements: 63.2, 63.3, 63.6, 63.7, 63.11; D116_
  - [x] 25.3 The tools: the resolver that reads the file system in `utils` (`skye.load`, `skye check` with `--stdin-filename`), the path rules and the symbolic
    link out of the root; `skye fmt` keeps the lines and formats partials and refuses a result that builds differently; `skye.dsl.to_text` writes
    expanded text; `skye prompt list` and `skye prompt info` skip `partial = true`; the facade `skye.dsl` re-exports only what exists
    - _Requirements: 63.1, 63.8, 63.9, 63.11, 63.12; D116_
  - [x] 25.4 The bundled catalogue: the resolver for the folder and for the archive (a member by its normalized path, one above the root refused), the
    fingerprint of the catalogue in the key of the compiled bundled templates (`_BUNDLED_ENTRIES`) and the fingerprint of a resolver in `build_cached`,
    `discover_templates` and the loader skip partials in subfolders, and the hook of tasks 24.3 and 24.7 walks the subfolders and keeps `partial = true`;
    a test that a changed partial does not give a stale document and that the builder of the bundled templates stays under `max_builder_ms`
    - _Requirements: 63.14, 63.15, 63.16; D116_
  - [x] 25.5 Documents and editors: `docs/reference/skye-language.md` (the grammar table and the table of the versions), `docs/concepts/skye-language.md`
    (the sentence that says there is no include in version 1), the language reference of the Claude skill (`utils/claude_skill/skye/references/language.md`) and
    its test, the grammar of the VS Code extension (`include`, `from`, `import`, `use`, `partial` and the path string), with the examples checked by
    `tests/unit/dsl/test_docs_examples.py` through a resolver on a temporary folder
    - _Requirements: 63.17; D116_
  - [ ] 25.6 The check of the feature: `make size`, the footprint test and the load budgets (the code of tasks 25.1 to 25.4 and 26.1 to 26.3 adds a few KB to the core; the
    limit is not changed), the construction of the builder under `max_builder_ms`, the whole suite, `mypy src`, and the strict docs build
    - _Requirements: 61.4, 63.15; D116, D117_

- [x] 26. The override of the include (D117)
  - [x] 26.1 The language core of `override` (`src/skye/base/dsl`: parser, syntax tree, expansion): `override name = <definition>` in the `variables` map and
    `override when name { ... }` / `override when not name { ... }` in a prompt or message body; the expansion marks every entry and block with the `use` that
    brought it, an `override` replaces the marked target and is accepted only after that `use`, an `override` of something that was not brought (or written
    before its `use`) is an error that lists what was brought, the word is not accepted in a partial or in a file without a `use`, the overriding definition is
    validated like any other, and the check of duplicates runs last on the result; the word `override` is added to the language (version 1.1); tests in
    `tests/unit/dsl/test_include_override*.py` with the `memories` and `show_ids` case of the design note
    - _Requirements: 63.18, 63.19, 63.20; D117_
  - [x] 26.2 Diagnostics, `skye fmt` and `skye check` for `override`: the messages (what was brought, the `use` must come first, an override and a definition of the same
    name with both lines), the diagnostic of an overriding entry or block pointing to the `override` line and the `via` of what the partial still brings kept,
    `skye fmt` keeping the `override` lines and refusing a result that would build differently, and the tests of each message
    - _Requirements: 63.20, 63.21; D117_
  - [x] 26.3 Documents, the Claude skill language reference, the grammar of the VS Code extension (the keyword `override` in its positions) and the doc-example
    test: one example with an `override` that `skye check` accepts, in `docs/reference/skye-language.md`, `docs/concepts/skye-language.md`, the skill reference
    and the strict docs build; the added bytes of the skill and the extension are reported
    - _Requirements: 63.21; D117_
  - [x] 26.4 The `text` format of the `output` block (D70, amended 2026-11-13; the code, the tests in `tests/unit/dsl/test_output_text.py` and the documents are written, the bundled templates do not use it yet: task 24.10): `output "text" { style = "..." }` is a plain answer with no fields; with the format from a variable, the value `text` leaves the fields and `schema = VAR` unread; `set_output_schema` refuses it
    - _Requirements: 33.5, 33.7; D70_
  - [x] 26.5 `register_template` resolves includes from a path: a `.skye` file registered with `from_string=False` reads its `include`, `from ... import`, `use` and `override` from its folder (the file resolver, read again at each registration), a text takes an optional `resolver=`, a text without one keeps the 'no resolver' error that names the argument, the folder loader registers such files and skips the files with `partial = true`, and `validate_template` rebuilds them; the code is in `src/skye/prompts/messages.py` and `loaders.py`, the tests in `tests/unit/prompts/test_register_template_include.py`
    - _Requirements: 63.11, 63.14; D116_

- [x] 21. The examples, the lint scope and the pages written before D111
  - [x] 21.1 `examples/plugins/` runs offline: remove the entry `plugins` of `EXPECTED_TO_FAIL` in `tests/examples/test_examples.py` and
    `test_examples_offline.py` (the two `agents/hooks` entries stay for the agents spec); every example passes `ruff` and `black`
    - _Requirements: 61.1, 24.11_
  - [x] 21.2 The scope of `.github/workflows/lint.yml` (`LINTED`) grows to the code written by tasks 13 to 20 once it is clean
    - _Requirements: 61.1_
  - [x] 21.3 The pages written before D111 are redone for the new interface: `docs/guides/extend/*`, `docs/reference/api/plugins.md`,
    `docs/reference/configuration-keys.md`, and the strict docs build passes
    - _Requirements: 61.2, 15.10_

- [x] 12. Final checkpoint (it runs after tasks 13 to 21; its id does not move because tests cite this file)
  - [x] 12.0 Validate the code against every criterion this spec points to (`requirements.md`: Requirements 56 to 62 of
    `10-requirements.md`, and decisions D27, D97, D98, D104, D107, D108, D110 and D111). For each criterion, write one evidence line: the
    file or function that realizes it and the test that checks it. A criterion with no code or no test is a finding.
  - [x] 12.1 Run `uv run pytest tests -q`, `make budget`, the doctests of the new modules and the strict docs build; record the numbers
  - [x] 12.2 Close in steering what the work settled: the open decisions of `12-decisions.md` that the code answered (O63, O65, O68 to O73)
    marked as taken with the options used, the "Extension points" table of `11-design.md` updated, and the scan note
    `docs/_notes/extension-points-scan.md` marked as done
## Notes

- Exit rule of every wave (owner, 2026-11-12): a wave ends with the size check, the default suite and the footprint test; the figure by component comes from task 24.1 when it exists, and until then from `uv run pytest tests/budget/test_footprint_budget.py -m budget`.

- Budget of the core size (2026-11-12): `test_core_footprint` measured 2.02 MB against `[core] max_installed_mb = 2` from task 9.1 until task 24.3, which strips the comments from the wheel; it measures 1.980 MB after 24.3 and passes. The limit is not changed; the work still to come (the built-in toolkits, the tasks 24.x) is checked at the end of every wave with `make size`.
- Tasks are deliverables in build order (D108). Each cites the requirement numbers of `10-requirements.md` it satisfies, or the decision it honors.
- Task IDs cited from other documents are `plugins:N.k`.
- Task 6.2 coordinates with the token-counter work of `1-adapters-models`, which uses the field names of Requirement 59.2.
- Tasks 8.x are independent of 6.x, except that 6.6 also touches store backends, so it runs in a later wave than 8.1 and 8.2.
- Tasks that depend on an open point (O63, O65, O68 to O73) follow its recommended option; a different answer from the owner changes only the task named. O59 to O61, O64, O66 and O67 were taken in D111.
- Tasks 12.0 to 12.2 are the final checkpoint: evidence per criterion, the full test and budget run, and the closing of steering.
- Tasks 5.5 and 7.5 to 7.7 (the layout of D110) run before the tasks that edit the adapters, the store, `auth` and `tools`, so that those
  edit the files where they will stay.
- The dependency graph below puts tasks that write the same file in different waves: `base/plugins.py` (2.3, 2.4, 2.5, 4.2),
  `base/profile.py` (3.1 to 3.3), `utils/plugins.py` (4.1, 4.3, 4.4, 4.5), the adapters (5.5, 5.4, 6.3, 6.5, 6.7), the router (6.4, 8.3,
  8.4, 9.1) and the store package (7.1, 7.5, 8.1, 8.2, 6.6, 8.4).

- Tasks 13 to 21 build the interface of D111 and run before task 12. The id of 12 did not move because tests and comments cite the ids of this file.
- Tasks that the interface of D111 made obsolete in text were rewritten (4.4, 4.5, 4.7, 9.4, 10.1, 11.1, 11.2, 12.0, 12.2); a finished task is never
  rewritten: it carries a note that names the task that redoes it. The conformance functions of Requirement 58.4 and the command `skye plugins`
  stay in tasks 10.1 and 4.6, now for the nine kinds.
- Tasks 18 and 19 build the registration and the shape of toolkits only. The loop that reads `return_direct`, `tools=` and `toolkits=` of an
  agent belongs to `3-runtime-agents`, and the content of each built-in toolkit and the wire name of a tool belong to the decision O70.
- The dependency graph keeps same-file writers in different waves: `base/plugins.py` (13.1 to 13.3, 14.1, 14.2, 15.1, 16.2, 17.1, 18.3),
  `skye/__init__.py` (14.3, 16.1, 18.4), `models/plugins/` and the adapters (15.2, 15.4, 17.2, 6.3, 6.5, 6.7, 20.2, 20.3) and `tools/` (13.2,
  18.1 to 18.5, 19.1 to 19.4).

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1", "3.1"] },
    { "id": 1, "tasks": ["1.2", "2.2", "3.2"] },
    { "id": 2, "tasks": ["2.3", "3.3"] },
    { "id": 3, "tasks": ["2.4", "3.4"] },
    { "id": 4, "tasks": ["2.5"] },
    { "id": 5, "tasks": ["2.6", "4.1", "5.1"] },
    { "id": 6, "tasks": ["4.2", "6.1", "6.2", "7.1", "7.2", "9.2", "9.3"] },
    { "id": 7, "tasks": ["5.5", "7.5", "7.6", "7.7"] },
    { "id": 8, "tasks": ["5.6", "5.7", "5.8"] },
    { "id": 9, "tasks": ["5.9"] },
    { "id": 10, "tasks": ["4.3", "5.2", "5.3", "5.4", "6.4", "7.3", "8.1"] },
    { "id": 11, "tasks": ["13.1", "20.1"] },
    { "id": 12, "tasks": ["8.2", "13.2"] },
    { "id": 13, "tasks": ["8.3", "13.3", "18.1", "22.1"] },
    { "id": 14, "tasks": ["8.4", "13.4", "18.2", "18.5"] },
    { "id": 15, "tasks": ["8.5", "14.1"] },
    { "id": 16, "tasks": ["4.5", "9.1", "14.2", "14.3"] },
    { "id": 17, "tasks": ["4.4", "14.4", "15.1"] },
    { "id": 18, "tasks": ["4.6", "15.2", "16.2", "23.1"] },
    { "id": 19, "tasks": ["4.7", "15.3", "15.4", "23.2", "24.1", "24.8"] },
    { "id": 20, "tasks": ["15.5", "16.1", "17.1", "24.2"] },
    { "id": 21, "tasks": ["9.4", "16.3", "17.2", "18.3", "24.3"] },
    { "id": 22, "tasks": ["6.3", "7.4", "17.3", "18.4"] },
    { "id": 23, "tasks": ["6.5", "18.6", "19.1"] },
    { "id": 24, "tasks": ["6.6", "6.7", "19.2", "19.5", "24.7"] },
    { "id": 25, "tasks": ["6.8", "10.1", "19.3", "20.2"] },
    { "id": 26, "tasks": ["10.2", "19.4", "20.3", "19.6", "19.7"] },
    { "id": 27, "tasks": ["21.1"] },
    { "id": 28, "tasks": ["21.2", "21.3", "24.4"] },
    { "id": 29, "tasks": ["11.1", "11.2"] },
    { "id": 30, "tasks": ["11.3"] },
    { "id": 31, "tasks": ["12.0"] },
    { "id": 32, "tasks": ["12.1"] },
    { "id": 33, "tasks": ["12.2"] },
    { "id": 34, "tasks": ["25.1"] },
    { "id": 35, "tasks": ["25.2", "25.4"] },
    { "id": 36, "tasks": ["25.3"] },
    { "id": 37, "tasks": ["24.6", "25.5"] },
    { "id": 38, "tasks": ["24.9"] },
    { "id": 39, "tasks": ["26.1"] },
    { "id": 40, "tasks": ["26.2", "24.10", "24.11"] },
    { "id": 41, "tasks": ["24.12"] },
    { "id": 42, "tasks": ["26.3", "26.4", "26.5"] },
    { "id": 43, "tasks": ["25.6"] },
    { "id": 44, "tasks": ["24.5"] }
  ]
}
```
