---
title: "skye.plugins"
status: current
---

# `skye.plugins`

The object that adds an integration (`Plugins`), the table behind it (`Registrar`), the provider profile (`ProviderProfile`,
`ModelProfile`, `RegionRule`) and the lookup functions `find_model_profile` and `resolve_region`. Generated from the docstrings.

::: skye.plugins
    options:
      show_root_heading: false
      show_submodules: false

## The nine kinds

You add every kind with a method of `Plugins`, which is also a decorator when you give it only the name. What you add is registered as soon
as the call runs; a name already taken for the kind raises `ConfigurationError` unless you pass `replace=True`.

| Kind | Add with | What it is | Checked by |
|---|---|---|---|
| `provider` | `plugins.provider(name, ..., profile=None, function=None)` | a model, an embedding or a decision provider, told apart by `function=` (`"model"`, `"embedding"`, `"decision"`) or by its methods | `skye.models.check_provider` |
| `backend` | `plugins.backend(name)` | a storage backend | `skye.store.check_backend` |
| `credential_source` | `plugins.credential_source(name)` | an authenticator, or a secret source | `skye.auth.check_credential_source` |
| `routing_strategy` | `plugins.routing_strategy(name)` | a function (or a `RouterStrategy` class) that chooses a model | `skye.router.check_routing_strategy` |
| `mcp_client` | `plugins.mcp_client(name)` | an implementation of `MCPClientInterface` | `skye.tools.check_mcp_client` |
| `tokenizer` | `plugins.tokenizer(name)` | a function that returns an object with `encode(text)` | `skye.models.check_tokenizer` |
| `template_filter` | `plugins.template_filter(name)` | a function of a value, usable in a prompt | `skye.prompts.check_template_filter` |
| `agent` | `plugins.agent(name)` | a class that is an agent | `skye.agents.check_agent` |
| `toolkit` | `plugins.toolkit(name, tools=None)` | a `skye.Toolkit`, or a list of tools | `skye.tools.check_toolkit` |

Each `check_<kind>` runs offline against fakes and returns the names of the checks that passed, or raises `AssertionError` naming the first one
that failed. The built-in registrations pass the same functions in the test suite.

What ships with Skye is registered the same way: the providers, the backends, the credential sources, the routing strategies, the two
MCP clients (`skyemcp`, the default, and `fastmcp`, in `skye.tools.engines`), one tokenizer, the agent `react` and four toolkits (`files`,
`openapi`, `human`, `shell`). `skye plugins` on the command line lists everything registered, and the plugins installed as packages with
the entry point group `skye.plugins` (which `plugins` in the [configuration file](../configuration-keys.md#which-plugins-load) can limit).

To read the table, use `plugins.names(kind)`, `plugins.has(kind, name)` and `plugins.get(kind, name)`; `plugins.unregister(kind, name)`
removes a name. The knowledge of a provider (key variable, endpoint, prices, tokenizer) is a `ProviderProfile`: pass it as `profile=`, or
change a provider that exists with `plugins.profile(provider, models=..., **fields)`, which merges and leaves the rest as it was.

## Building what you added

The word that adds a kind is the word that builds it: `plugins.agent("name")` adds an agent and `skye.agent("name")` builds it. These
functions are lazy names of `skye`: `import skye` loads none of the components, and each function imports its component when you call it.

| Add with | Build with | What you get |
|---|---|---|
| `plugins.provider` | `skye.provider(name, provider_type=...)` | a model, an embedding or a decision provider |
| `plugins.agent` | `skye.agent(name, **options)` | the agent (`REACT` is the built-in) |
| `plugins.backend` | `skye.backend(name, **config)` | a storage backend |
| `plugins.mcp_client` | `skye.mcp_client(target, impl="skyemcp")` | an MCP client |
| `plugins.credential_source` | `skye.credential_source(name, **config)` | a credential source |
| `plugins.routing_strategy` | `skye.routing_strategy(name)` | what was registered: a function, or a `RouterStrategy` class for a built-in |
| `plugins.toolkit` | `skye.toolkit(name, alias=None, **options)` | a toolkit; its tools are named `<toolkit>.<tool>`, and `alias` replaces the toolkit name when you build one toolkit twice |

An unknown name raises `ConfigurationError` and the error lists the registered names. The older functions (`create_agent`,
`skye.store.backend`, `create_mcp_client`, `resolve_credential_source`) work as before: they read the same table.

## Write an async method, not two

A Port with a sync and an async form has you write only the async one. A model provider writes `_acall_provider` and
`_acall_provider_stream`, and an embedding provider writes `aencode` and `aencode_batch`; Skye derives the sync forms (`complete`, `stream`,
`encode`, `encode_batch`) from them, so a plugin has no second code path to keep in step. A subclass that still defines the old sync hooks
(`_call_provider`, `_call_provider_stream`, `_encode_batch_impl`) does not instantiate.

## See also

- [Extend Skye](../../guides/extend/index.md): which Port to implement, and the guides for providers, backends, capabilities and
  toolkits.
- Examples: [`examples/plugins/`](https://github.com/ggiallo28/skye/tree/main/examples/plugins), one for each kind.
