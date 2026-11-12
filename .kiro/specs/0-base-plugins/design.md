Builds on: #[[file:.kiro/steering/11-design.md]] (sections: Layers, Allowed imports, Ports, Extension points, Plugins and provider profiles, Public API and lazy imports, Extras and budgets)

# Design Document: plugins

## Overview
`0-base-plugins` is the cross-cutting spec of decisions D107, D108 and D111: one way for a third party to add any kind of integration to Skye
without changing it, and one place for the knowledge that belongs to a provider or to the store. It has no component of its own. The
object that registers (`skye.Plugins`), the registrar, the Ports and the profile live in `base`; the scan of installed plugins lives in
`utils`; each kind keeps its owner (`models`, `store`, `auth`, `router`, `tools`, `prompts`, `agents`), which registers its built-ins with the
same calls and ships the conformance function of the kind. The layer, the allowed imports, the Port rules and the extras policy are in the
steering sections named above and are not restated here.

The work has two halves on one mechanism (Requirements 56 to 62 of steering):
1. **The plugin door.** `plugins = skye.Plugins()` is one object, created anywhere. Its methods are decorators, or direct calls, one for each of
   the nine kinds; they register at the moment they run, from any part of the program. The same word adds and builds (`plugins.agent`,
   `skye.agent`). Installed plugins are found through the entry-point group `skye.plugins`, whose entry points name a module; the scan runs
   lazily, at the first name a lookup does not know. The configuration key `plugins` limits what the scan loads; `skye plugins` lists everything.
2. **One home per kind of knowledge.** A provider registers a `ProviderProfile` with its class, and cost, token counting, the router and
   `auth` read the profile instead of their own tables. The store gains the two reads the router needs (`count`, remaining lifetime), so the
   router no longer knows how a counter is stored or how expiry works.

Two kinds are new and bring their own pieces: `toolkit` (built-in tools that an agent takes apart from its own) and `agent` (built only with
`skye.agent`). Order of work (D108, D111): the provider profile and the store first (they are in place), then the new interface over the
registrar, the kinds, the toolkits, the agent call, the derived sync methods, and last the examples, the documentation and the final
checkpoint. The examples of Requirement 61.1 are written first and already exist in `examples/plugins/`; they fail until the interface exists.

## Current state
Scan of 2026-11-11 (`docs/_notes/extension-points-scan.md`, a working note, not part of the spec). Tasks 1 to 11 of the first plan were built
against the interface of D108 (a plugin object with `register(registrar)`, eleven registrar methods, `skye.use`); D111 replaces that
interface and the tasks of the second half of `tasks.md` redo it.
- `base/interfaces/plugin.py` defines `PluginInterface` and `RegistrarInterface` with eleven methods; `base/plugins.py` defines `Registrar`.
  Nothing yet exports `skye.Plugins`.
- Six registries, each with its own shape, are views of the registrar: `ProviderRegistry` (`models/registry.py`), `register_backend`
  (`store/factory.py`), `register_credential_source` (`auth/registry.py`), `CapabilityRegistry` (`tools/registry.py`; a default set of
  capabilities is held by the registrar, which D111 removes), `TokenCounter.register_tokenizer` (`models/token_counter.py`),
  `register_agent_type` (`agents/registry.py`). Prompt filters are registered per builder instance (`prompts/messages.py`).
- Routing strategies, MCP client implementations and decision models are open kinds (task 9); the routing strategy still goes through the
  `RoutingStrategy` enum in the router (O69).
- The provider knowledge scattered outside the provider (P1 to P6 of the note) and the storage knowledge outside the store (S1 to S3) are
  partly moved: tasks 6.1, 6.2, 6.4, 8.1 are done; 6.3, 6.5 to 6.8 and 8.2 to 8.5 are open.

## Architecture
```
base/interfaces/plugin.py   RegistrarInterface (Protocol: one method per kind, and `profile`); PluginInterface goes (D111)
base/plugins.py             Registrar: the in-memory tables, one per kind, a lock on the write; lookup with one lazy scan; the default
                            registrar; Plugins: the handle on the default registrar, decorators and direct calls
base/profile.py             ProviderProfile, ModelProfile, RegionRule (frozen dataclasses); profile_from_mapping; find_model_profile;
                            resolve_region; the merge of plugins.profile
base/                       run_sync and iterate_sync (the derived sync methods, Requirement 56.13); ToolProvider (exists)
base/interfaces/storage.py  CounterStore.count; ExpiryStore (is_alive, remaining) next to KeyValueStore, CounterStore, ScanStore
utils/plugins.py            discover(registrar): scan of the entry-point group `skye.plugins`, the `plugins` allowlist, the report
utils/cli.py                `skye plugins [--format json]`
skye/__init__.py            lazy names: `Plugins`, `Toolkit`, and the builders `provider`, `backend`, `agent`, `toolkit`, `mcp_client`,
                            `credential_source`, `routing_strategy` (Requirement 7.8, D34)
skye/plugins.py             the facade of the plugin names (`Plugins`, `Registrar`, the profile classes)
<component>/plugins/__init__.py          IMPLEMENTATIONS (the folder names) and register(registrar), which calls that of each folder (D110)
<component>/plugins/<name>/__init__.py   the only door of an implementation: public names resolved lazily, register(registrar) of what it offers
<component>/plugins/<name>/*.py          provider.py, embeddings.py, multimodal_embeddings.py, decision.py: the code of the implementation
<component>/plugins/<name>/profile.toml  the ProviderProfile of a provider, as data (models)
<owner>/conformance.py      check_<kind> of the kinds it owns (store: check_backend exists, D98)
```
`base` holds data, Protocols, in-memory tables and the two sync helpers, and does no I/O (Requirement 3). The scan reads the metadata of
installed distributions, which is I/O, so it is in `utils`; the registrar holds the text `"skye.utils.plugins:discover"` and imports it at the
first miss, as `auth` and `store` already do with their built-in tables (O60, taken in D111). Owners import `base` only, as the matrix allows;
no owner imports `utils`. `agents` imports `base` and `models` only, so an agent that needs a toolkit builds it through the registrar, which is
in `base`, and never imports `tools`.

## Components and Interfaces

### The plugin door (Requirements 56.1 to 56.8)
- **`skye.Plugins`.** `plugins = skye.Plugins()` takes no argument and holds no table: it forwards to the default registrar of the process, so
  two handles created in two modules see the same registrations (56.1). There is one default table; a namespace of plugins and a scope for
  tests were weighed and dropped (D111).
- **Decorators and direct calls.** Each kind has one method of `Plugins`. With the name and the target (`plugins.provider("acme", Cls,
  profile=...)`) it registers; with the name only it returns a decorator that registers the class or function it is put on (`@plugins.agent("reverse")`).
  The decorator returns the object it decorates, so the class or function stays usable by name in the program. Every kind method takes
  `replace=False`; `provider` takes `profile=`; `toolkit` takes `tools=[...]` (Toolkits below) (56.2).
- **At once, from any thread.** The registration is made when the decorator or the call runs, wherever that is (the top of a module, a
  function, a method), and a write takes a lock, so it is safe from several threads; a read of a table needs none (56.6).
- **The registrar.** `Registrar` keeps one table per kind, in the memory of the process, with no file and nothing that survives an invocation
  (56.3, D27): `get(kind, name)`, `names(kind)`, `has`, `get_profile`, `unregister(kind, name)`. A second registration of a name for the same
  kind raises `ConfigurationError` naming the kind and the name, unless `replace=True` (56.4); two different profiles for one provider name
  raise the same way (59.8). A test builds a private `Registrar()` or removes what it registered with `unregister`; there is no scope for tests.
  `RegistrarInterface` is the Port with the nine kind methods and `profile`; whether it stays public in `skye.interfaces`, and whether `mcp_client`
  is part of it, are open in O65.
- **A target.** The object, a factory, or a `"module:attribute"` text imported at the first use of the name, never at registration (56.5). The
  built-ins register as texts, so registering them costs no import. A text target is not imported at registration, so the function of a text
  target of a `provider` (Requirement 56.12) cannot be deduced from the class then: the call that registers a text target gives the function
  (task 15.1 chooses the argument and records it here), and the call with an object or a factory deduces it.
- **The registries of today as views (56.8).** `ProviderRegistry`, `register_backend`, `register_credential_source` and `register_agent_type`
  keep their signatures and lose their tables. `CapabilityRegistry` is not a view: capabilities are not a kind and there is no default set
  (62.1). `TokenCounter.register_tokenizer` is outside the plugin interface (59.11, O72).
- **Built-ins use the same calls (56.7).** Each owner has a `plugins` package with an internal `register(registrar)`
  (`skye.<component>.plugins:register`) that makes the same calls as a third party; the default registrar calls them on the first lookup of any
  of their kinds. It knows them as a fixed tuple of texts (`BUILTIN_PLUGINS`), not by import.

### The kinds and the words (Requirements 56.2, 56.11, 56.12)
| Kind | Adds | Builds | Owner | What it is |
|---|---|---|---|---|
| `provider` | `plugins.provider` | `skye.provider(name)`, `provider_type="embedding"` or `"decision"` | `models` | a class with `generate`, `encode` or `decide` |
| `backend` | `plugins.backend` | `skye.backend(name)` | `store` | a `StorageBackend` |
| `credential_source` | `plugins.credential_source` | `skye.credential_source(name, ...)` | `auth` | a source with `apply` |
| `routing_strategy` | `plugins.routing_strategy` | `skye.routing_strategy(name)` | `router` | a function from the model ids to the one to use (O69) |
| `mcp_client` | `plugins.mcp_client` | `skye.mcp_client(target, impl=name)` | `tools` | an `MCPClientInterface` (the internal implementations `builtin` and `fastmcp`) |
| `tokenizer` | `plugins.tokenizer` | by the profile of a model | `models` | a function from the model to an object with `encode` |
| `template_filter` | `plugins.template_filter` | used by name in a template | `prompts` | a function of the value and its arguments |
| `agent` | `plugins.agent` | `skye.agent(name, **options)` | `agents` | a `Runnable` (`async invoke`) |
| `toolkit` | `plugins.toolkit` | `skye.toolkit(name, **options)` | `tools` | a `skye.Toolkit`, which is a `ToolProvider` |
- **One word (56.11).** The word that adds a kind builds it; `plugins.names("agent")` lists a kind and `plugins.get("toolkit", "openapi")` returns
  what was registered, so a plugin can build on a built-in. The typed accessors that exist (`create_decision_model`, `create_embedding_provider`)
  may stay. The lazy top-level names are added under D34, and the exports count test is updated with them.
- **One provider kind (56.12).** The function of a `provider` is deduced from the method of the class (`generate`, `encode`, `decide`) and the
  table is keyed by name and function, so `acme` can have a chat class and an embedding class. A class that has the methods of two functions is
  an error. One provider name has one profile (59.7).

### Async only (Requirement 56.13)
A plugin writes the async method only: `acomplete`, `astream`, `aencode`, `aencode_batch`, `invoke`. The base classes of the owners derive the sync
ones (`complete`, `stream`, `encode`, `encode_batch`) with two helpers in `base`: `run_sync(coroutine)` runs the coroutine with `asyncio.run`, or on a
worker thread when a loop is already running; `iterate_sync(async_generator)` runs the generator on its own loop in one thread, hands the chunks
over a bounded queue, raises an error of the generator in the caller and closes the generator when the caller stops early. The parallel sync
paths of the model base classes go. Open in O68: a sync `run` for the agent base, the cost of one thread for each sync stream, and whether the
credential source `apply` stays sync.

### Layout of the built-ins (Requirements 56.9 and 56.10; D110)
Each component that can be extended keeps its built-ins in `<component>/plugins/`, one folder per implementation or provider. The folder is
the plugin of that implementation: its code, its data and its registration together, the same shape a third party ships.
```
models/
  base.py  cost.py  token_counter.py  registry.py  decision.py      the classes of the component itself
  utilities/                                                    what a plugin is written with, plain files, not registered (D110)
    openai_compatible/     provider.py  request.py  response.py  capabilities.py     a provider for the OpenAI wire format
    anthropic_compatible/  provider.py  request.py  response.py  capabilities.py     a provider for the Anthropic wire format
    rest.py  streaming.py  eventstream.py  retry.py  error_mapping.py               the calls over the network
    structured.py  schema_check.py  capability_choice.py  prompt_parts.py  multimodal.py     how a request is shaped
    credentials.py                                                                  the API key and the AWS region of a client
  plugins/
    __init__.py      IMPLEMENTATIONS = ("openai", "anthropic", ...); register(registrar) calls the register of each folder
    openai/          __init__.py  provider.py  embeddings.py  profile.toml
    anthropic/       __init__.py  provider.py  profile.toml
    bedrock/         __init__.py  provider.py  request.py  response.py  capabilities.py  embeddings.py  profile.toml
    azure/           __init__.py  provider.py  profile.toml
    google/          __init__.py  provider.py  request.py  response.py  capabilities.py  embeddings.py  multimodal_embeddings.py  profile.toml  profile_multimodal.toml
    cohere/          __init__.py  embeddings.py  profile.toml
    typesafe/        __init__.py  decision.py     (Jev, the decision model of TypeSafe AI; the name registered is "jev")
```
- **One door.** The `__init__.py` of a folder lists its public names in `_LAZY = {name: inner module}` and resolves them with `lazy_names` of
  `base/lazy_import.py`, the one helper of every component; importing the folder imports no inner file and no vendor library. Code outside the folder (the factory, the
  registrar texts such as `"skye.models.plugins.openai:OpenAIProvider"`, the docs) names the folder, never an inner file. Tests may patch
  an inner module.
- **The other components, the same shape.** `store/plugins/{memory,file,dynamodb,redis,postgres,durable_function}/` with `backend.py` (`valkey`
  is a second name registered by the `redis` door); `auth/plugins/{aws,google,azure,oauth2,openai_compatible,secrets}/` with `source.py` and the
  helpers that only that family uses (`aws` also holds `aws_profile.py`, `sts.py` and `sigv4.py`); `tools/plugins/{builtin,fastmcp}/` with
  `client.py`, and next to the two MCP clients the folders of the built-in toolkits (`files`, `openapi`, `mcp`, `a2a`; see Toolkits below); `agents/plugins/react/` with `agent.py` (a built-in registered by text, so that `import skye.agents` loads no built-in). What several folders use stays in the root: `store/_common.py`, `conformance.py`, `factory.py`; `auth/cache.py`, `refresh.py`,
  `errors.py`, `rsa_signing.py`, `registry.py`; `tools/mcp_client.py` (the interface, `create_mcp_client`) and the rest.
- **A missing file.** A missing inner file breaks only access to the name that lives in it (an `ImportError` that the registrar turns into a
  `ConfigurationError` naming the kind, the name and the cause); the folder and the others keep working. A missing `profile.toml` is a broken
  installation and the `register` of that folder raises a `ConfigurationError` naming the folder and the file. A test per component
  (`tests/unit/plugins/test_layout_<component>.py`) fails first: every `IMPLEMENTATIONS` name has a package, every `_LAZY` name resolves, every
  registered text resolves, and importing a folder imports no inner module.
- **Same names everywhere.** `provider.py` is the language model class (constructor, calls, model info; thin), `request.py` how the request is
  built, `response.py` how a response and a stream chunk are read, `capabilities.py` the capabilities out and back, `embeddings.py` the embedding
  model, `multimodal_embeddings.py` the multimodal one, `decision.py` the decision model, `profile.toml` the profile; later `errors.py` and
  `schema.py` (Requirement 60.5). A folder has only the files it needs, and the class keeps its method names as thin wrappers over the module
  functions, so a subclass can still override one.
- **Utilities.** What more than one provider uses, and what a third-party plugin is written with, is in `models/utilities/` and is not
  registered: the two wire-format providers (a complete provider for an endpoint that speaks the OpenAI or the Anthropic format, with the same file
  names as a provider folder) and plain modules, not groups: the network, the shaping of a request and `credentials.py`. The classes of the
  component itself (`BaseModelProvider`, `CostCalculator`, `TokenCounter`) stay in the root of `models`. An adapter imports no other adapter (D109); the family rule of
  `tests/budget/test_provider_agnostic_core.py` lets `openai` and `azure` use `utilities/openai_compatible`, and nothing else across providers.
- **Facts of a model are data too.** The vector dimension of an embedding model is `info.vector_dimension` in its entry of the profile, and the
  default endpoint is `default_api_base`; `BaseEmbeddingProvider` reads them from the profile registered for its provider, so no adapter keeps a
  table of models or a host name.
- **Not a component.** A dedicated `plugins` component would have to know the internal paths of every other component, so adding one would
  edit it (the opposite of Requirement 60); `base` does no file I/O (Requirement 3.2, D91) and the plugins are not a utility. The scan stays in
  `utils` (O60) and the registrar and the profile in `base`.

### Discovery and control (Requirement 57)
- **Lookup.** `registrar.get(kind, name)` looks in the table; on a miss, and only the first time in the process, it imports
  `skye.utils.plugins:discover`, calls it with itself, and looks once more (57.1, 57.2). `import skye` scans nothing and loads no plugin
  (57.3); the lazy names of `skye/__init__.py` do not change.
- **Scan.** `discover` reads `importlib.metadata.entry_points(group="skye.plugins")`. The value of an entry point is a module (57.4): the scan
  loads it, which imports the module, and the decorators in it register. A failure is logged once at WARNING with
  `extra={"entry_point", "distribution", "error"}` and the scan goes on (57.6, D105). The scan keeps a report (name, distribution, version,
  loaded or the error, the names registered per kind) for `skye plugins` and for the error of 57.7.
- **An import registers.** A module that registers does it as an effect of its import, whether the scan or the program imports it, so the entry
  point is a convenience and not a condition (57.4, 57.8). The tests of a plugin remove what they registered with `unregister` or register with
  `replace=True`.
- **Allowlist.** When the configuration file has `plugins = [...]`, only those entry-point names are loaded; without the key, all are
  (57.5). The key is read with `skye.utils.config_files.load_config`, the reader of D91.
- **Unknown name.** After the scan, a miss raises `ConfigurationError` listing the names of that kind and the failures of the scan (57.7).
- **Command.** `skye plugins` prints the built-in registrations and each entry point with its distribution, version, status and names
  per kind; `--format json` prints the same as one JSON object (57.9). It runs the scan, so it also shows what a lookup would load.

### The provider profile (Requirement 59)
```python
@dataclass(frozen=True)
class ModelProfile:
    prompt_price: float | None = None        # USD per 1M tokens
    completion_price: float | None = None
    tokenizer: str | None = None             # a name registered with registrar.tokenizer
    message_overhead: int = 0                # tokens added per message
    info: Mapping[str, Any] = {}             # merged into get_model_info(), e.g. supports_structured_output

@dataclass(frozen=True)
class RegionRule:
    variables: tuple[str, ...]               # e.g. ("AWS_REGION", "AWS_DEFAULT_REGION")
    required: bool = True

@dataclass(frozen=True)
class ProviderProfile:
    name: str
    api_key_variables: tuple[str, ...] = ()  # read in order; the provider-standard names (Requirement 11.6)
    region: RegionRule | None = None
    default_api_base: str | None = None
    client_settings: Mapping[str, str] = {}  # generic setting -> provider name, e.g. {"api_base": "azure_endpoint"}
    model_is_deployment: bool = False        # Azure: the model name is the deployment
    models: Mapping[str, ModelProfile] = {}
    map_error: Callable[..., ProviderError] | str | None = None  # or "module:attribute"
```
(Mappings are given with `field(default_factory=...)` and frozen as `MappingProxyType`.)
- **The profile as data (56.10).** The profile of a built-in provider is the file `profile.toml` of its folder: the fields of `ProviderProfile` as
  keys, a `[region]` table, a `[client_settings]` table and one `[models."model-id"]` table per model (`prompt_price`, `completion_price`,
  `tokenizer`, `message_overhead`, an `info` table). The owner (`models`) reads the file with `tomllib` and `importlib.resources`, so it works from
  a wheel and from a zip; `profile_from_mapping(data, source)` in `base` builds the dataclass and raises a `ConfigurationError` for a key the
  format does not know, so a typo is not ignored. Updating a price or adding a model edits a data file and no code.
- **Jev (D111).** TypeSafe AI publishes the price of Jev: 0.042 USD per million input tokens, output free. It is `typesafe/profile.toml`, and the
  decision model registers through `provider` with that profile, which is kept under its own name `typesafe` (59.7, 59.12) while the registered
  name stays `"jev"` (D110); the `CostCalculator` reads the price like any other.
- `find_model_profile(profile, model)`: the exact name first, then the longest registered name followed by a date or version suffix
  (`-2024-08-06`, `-20240620`, `-v1:0`, `@001`); `gpt-4o` never matches `gpt-4` (59.4). One function, in `base/profile.py`.
- `resolve_region(rule, passed=None, authenticator=None)`: the region passed, then the authenticator's, then the variables in order; a
  required rule with no region raises `ConfigurationError` naming the variables; there is no default region (59.5, 59.6).
- A provider with no profile, or a model missing from it, is not an error: the cost is unknown (`None`), the token count is the
  standard-library estimate, and `get_model_info()` returns what the adapter knows (59.10).
- An OpenAI-compatible endpoint is a plugin with no class: `plugins.provider("acme", OpenAICompatibleProvider,
  profile=ProviderProfile("acme", api_key_variables=("ACME_API_KEY",), default_api_base="https://api.acme.example/v1"))` (59.9).
- **A change to one model (59.11).** `plugins.profile("openai", models={"gpt-4o": ModelProfile(tokenizer="words")})` merges the given model
  entries into the profile of an existing provider and changes nothing else, so a plugin changes one fact of a model without registering the
  provider again. A new provider names its tokenizer in its own profile. The tokenizer functions are registered by name (`plugins.tokenizer`) and a
  model uses one only through `ModelProfile(tokenizer=...)`; `TokenCounter.register_tokenizer`, which matches by prefix, is outside the plugin
  interface. What exactly merges, the error for an unknown provider or model and the fate of `register_tokenizer` are open in O72.
- The model facts of D109 (which Claude models refuse a forced choice) become `ModelProfile.info["supports_forced_capability_choice"]`
  in the Anthropic and Bedrock profiles, and `refuses_forced_choice` reads `get_model_info()`; the two adapter tuples go.

### Provider knowledge in one place (Requirement 60.1 to 60.8)
| Today | After |
|---|---|
| `CostCalculator.PRICING` | prices in each built-in `ModelProfile`; `add_custom_pricing` writes a user layer that wins; `get_pricing`, `pricing_for`, `list_models` read profiles then the layer (60.1) |
| prefixes, tokenizers and overheads in `TokenCounter` | `tokenizer` and `message_overhead` of the `ModelProfile`; `register_tokenizer` registers a tokenizer by name (60.2, 59.3) |
| `STANDARD_ENV_VARS`, `API_KEY_VARIABLES`, names in adapters | `ProviderProfile.api_key_variables`, read by `auth`, the router's `.skye` reader and the adapters (60.3) |
| `if target.provider == "azure"` in the router | `client_settings` and `model_is_deployment` of the target's profile; the router names no provider (60.4) |
| handlers per provider in `error_mapping.py`; `gemini_schema` in `structured.py` | each in its adapter module, referenced by `map_error`; `error_mapping.py` keeps the HTTP-status mapping of D104 and calls `map_error` (60.5) |
| region in `auth/plugins/aws/source.py`, `auth/plugins/aws/sts.py`, `models/utilities/credentials.py`, the boto3 chain | `resolve_region` everywhere (60.6); the store passes the region it finds and leaves boto3's chain as the last step (O63.2, option A) |
| `_native_json_output` in Bedrock | `get_model_info()["supports_structured_output"]` from the profile (60.7) |

`tests/budget/test_provider_knowledge.py` fails on a built-in provider name, a key variable or a price used as a literal outside the
adapter and profile of that provider, with an allowlist that only shrinks, in the style of `test_provider_agnostic_core.py` (60.8).

### Storage knowledge in one place (Requirement 60.9 to 60.12)
- `CounterStore.count(key) -> int`: the count, 0 when absent or expired. Every backend implements it; `check_backend` checks it (60.9).
- `ExpiryStore` (a capability Protocol beside those of D98): `is_alive(key) -> bool` and `remaining(key) -> float | None` (seconds, `None`
  for no expiry or absent). Each backend computes it from the expiry it already stores and its clock (60.10).
- The router keeps a cooldown as `set(key, {}, ttl=seconds)` and asks `is_alive`; it never compares a stored time with `time.time()`,
  so `FakeClock` drives its tests (closes S2). It reads counters with `count` (closes S1) and creates its default store with
  `skye.store.backend("memory")` (60.11, closes S3).
- Namespaces (O63.1, option A, recommended): `store.namespaced(store, "router")` prefixes every key, and each component uses its own.
- `tests/budget/test_storage_knowledge.py` fails on the import of a concrete backend class outside `store` and its tests, and on reading
  the key `"count"` of a stored value outside `store` (60.12).

### Toolkits and the agent call (Requirement 62)
- **A toolkit.** `skye.Toolkit` lives in `tools`; it is a `ToolProvider` (the Port in `base`) that collects the methods of its class marked with
  `@capability` and runs them (62.5). A class is registered with `@plugins.toolkit("name")` and built with `skye.toolkit("name", **options)` (62.6).
- **The prefix.** The name of a tool is `<toolkit name>.<name>`, added by `skye.Toolkit`, where the name is the name of the method or the `name=`
  of the decorator. Two instances of one toolkit take an `alias` (`skye.toolkit("jira", alias="jira-eu", ...)`), which replaces the toolkit
  name in the prefix.
- **The shape.** Methods carry the same `@capability` as a free function; for that `LocalFunctionCapability` becomes a descriptor (`__get__` binds
  it to the instance) and its schema skips `self`. A function written outside the class is added with `tools=[...]` in the decorator
  (`@plugins.toolkit("jira", tools=[slugify])`), also with no class (`plugins.toolkit("text", tools=[...])`); a toolkit with no state may be a
  function that returns a `CapabilityRegistry`. `@capability` is required for now and takes `name`, `description` and `return_direct` (62.2).
- **Built-ins.** `files` (a required `root`; nothing outside it), `openapi` (one tool for each operation of a document), `mcp` (the tools of an
  MCP server, by its address) and `a2a`, registered as plugins in `tools/plugins/` next to the two MCP clients; none is active unless the user
  asks for it or a feature of the agent needs it (62.7). A `SKILL.md` in `skills=[...]` makes the agent build `files` through the registrar,
  limited to the folder of the skill (62.8). The content of each toolkit, the read-only rule of `files` and the rules of `return_direct` are open
  in O70; the wire name of a tool with a dot is open in O70 as well.
- **Not a plugin kind.** `CapabilityRegistry` keeps its name and stays in `tools` with its namespaces; capabilities are not registered in the
  registrar and no default set exists, so a tool belongs to the agent that is given it (62.1). Whether `tools` and the gateway merge is O19.
- **The agent call.** An agent is built only with `skye.agent(name, **options)`, a view of `create_agent`; there is no `Agent` class, and `REACT`
  from `skye.agents` is the built-in (62.9). `react` is a placeholder until the agents spec; `tools=`, `toolkits=` and `return_direct` are the work
  of that spec. Open in O71: the default name, the base class `skye.BaseAgent` and the options of a custom type.

### The closed kinds (Requirement 58)
- **Routing strategies.** `RoutingStrategySelector` asks the registrar for the strategy by name; the eight built-ins register in
  `router/plugins/`; every `RoutingStrategy` member stays valid as a name; the `if`/`elif` chain goes (58.1). A registered name is valid in the
  `strategy` of a router, of a route and of a `.skye` file; `ModelRouter.from_config_dict` and the `.skye` checker look the name up in the
  registrar when it is not a built-in value (O69 keeps open what state the strategy receives).
- **MCP clients.** `impl` is a registrar name; `"builtin"` stays the default (D16); `"fastmcp"` registers as text and imports `fastmcp`
  only when chosen (58.2, Requirement 10.7).
- **Decision models.** They are providers with the function `decide`: `skye.provider(name, provider_type="decision")` and `create_decision_model`
  build one through the registrar; Jev registers as a built-in with the profile of TypeSafe (58.3, 59.12).
- A Port of a planned component (content reader, observer, safety filter, authorizer, memory) gets its registrar method in the change that
  gives it a registry (58.6).

### Conformance (Requirement 58.4, 58.5)
Each owner ships `check_<kind>` next to the kind: offline, against fakes, returning the names of the checks passed and raising an error
that names the first that fails. `skye.store.check_backend` is the model. Kinds and owners: `check_provider` (`models`; a fake transport, the Port
shape of the function the class has, the profile valid, and for a decision the rule of Requirement 9.8), `check_backend` (`store`, exists),
`check_credential_source` (`auth`), `check_routing_strategy` (`router`), `check_mcp_client` (`tools`), `check_tokenizer` (`models`),
`check_template_filter` (`prompts`), `check_agent` (`agents`), `check_toolkit` (`tools`). One parametrized test runs every built-in registration
of every kind through its function.

## Data Models
`ProviderProfile`, `ModelProfile`, `RegionRule` above; the scan report is a list of dataclasses `PluginReport(name, distribution,
version, loaded, error, registered: dict[kind, list[name]])`, printed by `skye plugins`. Nothing is persisted.

## Error Handling
All registration and lookup errors are `ConfigurationError` with `details` (kind, name, the names known, the scan failures). A plugin that
fails to load is logged once and skipped (57.6). A class registered as a `provider` that has the methods of two functions raises
`ConfigurationError` at registration. `resolve_region` raises `ConfigurationError` naming the variables. A `map_error` given as text that does
not import raises `ConfigurationError` at the first error it should map, with the cause kept. A toolkit prefix that clashes with another tool
raises `ConfigurationError` naming both when an agent composes them.

## Testing Strategy
- `tests/unit/plugins/`: `Plugins` (a decorator and a direct call for each kind, registration at once and from several threads, two handles see
  one table), the registrar (each kind, duplicates, `replace`, `unregister`, lazy text targets, views of the old registries), the deduction of the
  function of a `provider` and its error, discovery with a fake `entry_points` (one scan per process, the allowlist, a failing entry point,
  the error after the scan, an entry point that is a module), `skye plugins` text and JSON, `find_model_profile`, `resolve_region` and the merge of
  `plugins.profile`.
- `tests/unit/plugins/test_layout_<component>.py` (models, store, auth, tools, agents): the layout rules of D110, one test file per component;
  `test_profile_files.py`: every `profile.toml` loads and `profile_from_mapping` refuses unknown keys.
- `tests/unit/tools/`: `skye.Toolkit` (methods with `@capability`, the prefix, `alias`, `tools=[...]`, the registry function form, `self` out of the
  schema), the built-in toolkits by name.
- `tests/unit/` for `run_sync` and `iterate_sync`: a loop already running, an error in the middle of a stream, an early stop closes the generator.
- `tests/unit/store/`: `count` and `ExpiryStore` in the conformance suite, for all six backends.
- `tests/unit/router/`: cooldown and counters with `FakeClock`, no `time.time()`; strategies by name; a registered custom strategy.
- `tests/budget/`: `test_provider_knowledge.py`, `test_storage_knowledge.py`; import time and cold start unchanged; `import skye` loads no
  entry point (a fake entry point that raises on load proves it).
- `tests/examples`: `examples/plugins/` runs offline (61.1); its entry in `EXPECTED_TO_FAIL` is removed when it passes.

## Correctness Properties

### Property 1: One door
Every kind is registered through `Plugins` over the registrar; built-ins and third-party plugins make the same calls.

**Validates: Requirements 1.2, 1.7**

### Property 2: Lazy
`import skye` scans nothing and imports no plugin or built-in target; a text target is imported only at its first use.

**Validates: Requirements 1.5, 2.3**

### Property 3: One scan
The entry-point group is read at most once per process, whatever the number of misses.

**Validates: Requirements 2.2**

### Property 4: No silent override
A second registration of a name, or a second different profile for a provider, fails unless `replace=True`.

**Validates: Requirements 1.4, 4.8**

### Property 5: One home
No provider name, key variable or price appears as a literal outside its adapter and profile; no backend class or stored shape is read outside `store` (the two budget tests).

**Validates: Requirements 5.8, 5.12**

### Property 6: Profile lookup is total
For any provider and model, the cost is a number or `None`, the token count is a number, and neither raises for a missing profile.

**Validates: Requirements 4.10**

### Property 7: Time is the store's
No router behaviour depends on `time.time()`; every time-dependent path is driven by the store's clock.

**Validates: Requirements 5.10**

### Property 8: Compatible
Every call to the registries of today, and every `RoutingStrategy` name, works as before.

**Validates: Requirements 1.8, 3.1**

### Property 9: Immediate and shared
A registration made by a decorator or a call is visible at once to every `Plugins` handle and to every thread, wherever it was made.

**Validates: Requirements 1.1, 1.6**

### Property 10: One word
For each kind, the word of the decorator is the word of the builder, and `plugins.names(kind)` lists what a builder finds.

**Validates: Requirements 7.1, 7.2**

### Property 11: A tool belongs to its agent
No capability is held by the registrar; a tool of a toolkit has the prefix of its toolkit, so it never clashes with a tool of the agent.

**Validates: Requirements 8.1, 8.3**

## Open points (not decided here)
The interface is decided in D111; what follows is what D111 left open, each in `.kiro/steering/12-decisions.md`. The tasks follow the decided part
and name the open point they wait for.
- O19: whether a separate `gateway` stays or its work becomes the job of the tools registry. This spec keeps `CapabilityRegistry` in `tools`.
- O62: `base/openai_shape.py` stays in `base` (option A); no change in this spec.
- O63: namespaces with `store.namespaced` (1, option A) and the store region through `resolve_region` with boto3's chain last (2, option A).
- O65: whether `RegistrarInterface` stays a public Protocol, whether `mcp_client` is part of it, and whether a scope for tests is reconsidered.
- O68: the sync `run` of the agent base, the cost of one thread for each sync stream, the credential source `apply`.
- O69: how a custom routing strategy is used in a router, and what state it receives.
- O70: the rules of `return_direct`, plain functions without `@capability`, the early schema check and `__call__`, the wire name of a tool with a
  dot, and the content of the built-in toolkits.
- O71: the default name `react`, `skye.BaseAgent`, and the options of a custom agent type.
- O72: the details of `plugins.profile`, and the fate of `TokenCounter.register_tokenizer`.
- O73: how a user finds the hooks of an agent and what each hook point receives (`list_hooks`, `describe_hook`); it belongs to `3-runtime-agents`.
