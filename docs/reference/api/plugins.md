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
`skye.store.backend`, `create_mcp_client`, `resolve_credential_source`) work as before.
