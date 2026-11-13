# Changelog

All notable changes to Skye are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.3.0] - 2026-11-13

### Added

- Plugins: `skye.Plugins()` is one handle with a decorator for each of nine kinds (`provider`, `backend`, `credential_source`, `routing_strategy`, `mcp_client`, `tokenizer`, `template_filter`, `agent`, `toolkit`), a builder for each (`skye.provider`, `skye.backend`, `skye.toolkit`, ...), entry points in the group `skye.plugins`, the command `skye plugins` and the `plugins` key of the configuration. A provider is declared once, in its profile (`profile.toml` or `plugins.profile`): name, key variables, endpoint, prices, tokenizer, region rule and the facts of each model.
- Offline checks for what you write: `check_provider`, `check_tokenizer`, `check_credential_source`, `check_routing_strategy`, `check_template_filter`, `check_agent`, `check_backend`, `check_mcp_client` and `check_toolkit`, importable from `skye.models`, `skye.auth`, `skye.router`, `skye.prompts`, `skye.agents`, `skye.store` and `skye.tools`.
- Toolkits: `skye.Toolkit` and `skye.toolkit(name, ...)`, with the built-in toolkits `files` (read-only, one or several folders), `openapi`, `human` and `shell`. An agent given `skills=[...]` gets one `files` toolkit over the folders of its skills.
- The `.skye` language, version 1.1: partial files (`partial = true`), `include "path" as name`, `from "path" import a, b`, `use` where the content goes, and `override` to change what a `use` brought. `skye check` and `skye fmt` follow the includes, and a diagnostic inside a shared file carries the chain of use sites (`via`). `BasePromptBuilder.register_template` resolves the includes of a file registered from a path.
- The `text` format of the `output` block, next to `json`, `table` and `xml`, for a free-form answer.
- Prompts: six bundled prompts (`agent_react`, `extraction_generic`, `generation_code`, `text_explanation`, `text_question_answering`, `text_summarization`) and a gallery of 26 more to copy in `examples/prompts/catalogue/`. `skye prompt export DIR` writes the bundled prompts and the files they include.
- Stores: `store.namespaced(store, prefix)` gives each component its own keys over one store; the router keeps its state under `router:`.
- `@capability` functions stay callable (`__call__`).
- Examples: an Ollama provider example, plugin and hooks examples, a gallery of prompts and a two-file prompt that shares a part and overrides it.

### Changed

- A provider written as a plugin implements only the async methods (`_acall_provider`, `_acall_provider_stream`, and `aencode`, `aencode_batch` for embeddings); `complete`, `stream`, `encode` and `encode_batch` are derived from them. A subclass that still defines `_call_provider`, `_call_provider_stream` or `_encode_batch_impl` no longer instantiates.
- The AWS region has no default: it comes from the argument, the authenticator, the variables named in the Bedrock profile, and boto3's own chain last. `CredentialProvider` with a role and no region raises instead of using `us-east-1`.
- The name of a tool that reaches a provider has letters, digits, `_` and `-`, at most 64 characters, and a dot is refused with a clear error. The tools of a toolkit are named `<toolkit>_<name>` (`files_read`, `human_ask`), and an MCP tool name that a provider would refuse is cleaned for the model while the call to the server keeps the original.
- The bundled prompts are six, written with `scope_detail` names. The other 26 moved to the gallery, `structured_output_json`, `_table` and `_xml` are gone (`extraction_generic` takes `format`), and `generation_sql` is a case of `generation_code`.
- The wheel is smaller: comments are stripped at build and the bundled prompts are one archive. The installed core is 1.9 MB, `import skye` takes about 20 ms and `BasePromptBuilder()` about 1 ms.
- The MCP clients live in `skye.tools.engines`.
- The package is typed: the names that `skye` loads on first use are explicit re-exports for type checkers.
- Examples use a current Claude Sonnet model id in place of the retired Claude 3 Sonnet one.
- The documentation covers plugins, toolkits, the `.skye` sharing words and the store interface.

### Removed

- The lifecycle methods of the plugin object (`initialize`, `shutdown`, `get_metadata`) are replaced by `skye.Plugins()`.

## [0.2.0] - 2026-11-11

### Added

- `skye render` and `to_mermaid`: draw a router or a flow as a diagram.
- The `skye.dsl` facade for the public functions of the `.skye` language.
- Forced capability choice emulation for providers that do not support it natively.
- An example that packages Skye as a zip for AWS Lambda.

### Changed

- The config file is read outside the `base` component.
- The documentation is reorganized into get started, concepts, guides, reference and project sections.
- Prompts, router and tools are aligned with the updated base and adapters components, and the models and store adapters follow their updated specs.
- Size budgets in `budgets.toml` are updated.

## [0.1.1] - 2026-11-08

### Added

- A Code of Conduct.

### Changed

- PyPI metadata: more classifiers and the documentation URL.
- README: badge order, Python 3.11+, MIT and install size badges, and documentation links that point to Read the Docs.

## [0.1.0] - 2026-11-08

First release after the 0.0.1 preview on PyPI.

### Added

- Prompts and routers written in `.skye` files, with the language tools (`skye check`, `fmt`, `new`).
- The documentation site on Read the Docs (MkDocs Material) and the project URLs.

### Changed

- The core has zero third-party dependencies and uses the standard library only.

### Removed

- YAML configuration. A `.yaml` or `.yml` file is now rejected with an error; use `.skye` or JSON.

### Fixed

- Router fixes.

[Unreleased]: https://github.com/ggiallo28/skye/compare/v0.3.0...main
[0.3.0]: https://github.com/ggiallo28/skye/releases/tag/v0.3.0
[0.2.0]: https://github.com/ggiallo28/skye/releases/tag/v0.2.0
[0.1.1]: https://pypi.org/project/skyeai/0.1.1/
[0.1.0]: https://pypi.org/project/skyeai/0.1.0/
