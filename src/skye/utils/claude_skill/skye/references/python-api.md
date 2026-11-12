# Using Skye from Python

```python
import skye
from skye import UserMessage

client = skye.provider("openai", api_key="sk-...")   # "anthropic", "bedrock", "azure", "google", "cohere" work the same way
response = client.complete(messages=[UserMessage(content="Hello!")], model="gpt-4")
print(response.content)
```

## Clients

- Without `api_key` a client reads its standard variable (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `COHERE_API_KEY`,
  `AZURE_OPENAI_API_KEY`); a missing one raises `ConfigurationError` naming it. Bedrock without `region` reads `AWS_REGION`, then
  `AWS_DEFAULT_REGION` (no default). Google keeps `location` (`region` is an alias). Azure takes `credentials=` (Entra ID
  authenticators of `skye.auth`) instead of a key. `skye.provider("cohere", model=...)` is the Cohere embedding client.
- Errors (`skye.exceptions`): `RateLimitError`, `ServerError`, `ProviderTimeoutError` are retried by the client (`max_retries`,
  default 3, `0` = off; backoff or `Retry-After`; a stream only before its first chunk); `AuthenticationError`, `BadRequestError`,
  `ContentPolicyError` and `UnsupportedModalityError` (an input form the provider does not accept, `.modality`) are raised at once.
- Cost: `response.metadata["cost"]` is `{"prompt", "completion", "total", "currency", "exact"}` in USD or `None` for a model with no price (never
  0); it uses the provider's token count and estimates only when none comes (`exact` false, `metadata["usage_estimated"]`).
  `skye.provider(..., pricing={"prompt": p, "completion": c})` (USD per 1M tokens) prices that client. Every `StreamChunk` has `.usage`
  and `.cost`, a running counter that a chunk without text repeats. `skye.models.TokenCounter.register_tokenizer(model_or_prefix, t)`
  takes any object with `encode(text)`; the default estimate is 1 token per 4 characters.
- `capabilities=` takes a list, a `CapabilityRegistry` or any `ToolProvider`. An `OutputSchema` reply is checked against the whole
  schema; with tools, Anthropic sends `output_config.format` and Bedrock writes the schema in the system text.
- A custom provider calls HTTP with `skye.models.post_json` / `stream_sse_json` (not `skye.base.http`).

## Routers

- From a file: `ModelRouter.from_file("router.skye", name="main")`. A `.json` file with the configuration object also works. **YAML is not read.**
  Keyword arguments of `ModelRouter` pass through (`storage=skye.store.backend("dynamodb", table_name=...)`, `strategy`,
  `cooldown_seconds`, `retry_policies`, `sleep`, ...); an unknown keyword raises `ConfigurationError`. The state is in memory unless you
  pass a `storage` (D97).
- A target built in Python takes `options={...}`: keyword arguments for the provider client that the target has no field for (Google's
  `project_id` and `location`, Azure's `azure_endpoint`). A `.skye` target has no `options` field yet.
- A route that sets no `strategy` uses the router's (`ModelRouter(strategy=...)`, `round_robin` by default).
- From Python: `ModelRouter({"fast": ["openai/gpt-4o-mini", "anthropic/claude-haiku"]})`.
- Back to a file: `router.to_skye("main")` returns the `router` block as `.skye` text and `router.to_config()` the configuration dictionary
  (`ModelRouter.from_config_dict` rebuilds the router from it). Use them to move a router built in Python to a file. **Secrets are not
  exported:** a key written as `env.NAME` comes back as `env.NAME`; a key written in clear is left out unless `include_secrets=True`.
  The text has no comments, and extra fields of a target are not exported.

## Reading and writing a `.skye` text

The parser lives in `skye.base.dsl` and takes text, not a path: `parse`, `build`, `check_text`, `block_schema`, `build_cached`, and the
skeleton functions `new_router`, `new_flow`, `new_prompt`, `skeleton`. `to_text(spec)` is the opposite of `build`: it writes a router, flow or
prompt spec (or a whole document) back as `.skye` text that passes `skye check` and builds an equal spec (comments are not kept);
`format_duration(seconds)` gives `"30s"`, `"5m"` or `"24h"` for a number of seconds. The front matter of a file is in
`build(text).metadata` (a dict); `split_metadata(text, filename)` returns `(metadata, text_without_it, diagnostics)` and
`format_metadata(metadata)` writes it back (`to_text(document)` keeps it). `format_text(text)` is `skye fmt` (comments kept; raises
`FormatError` with `.diagnostics` for a text with mistakes). `load_document(path)` reads a file
and skips the parse when the file did not change; the documents it returns are shared and read-only.

In examples and application code import the public path `skye.dsl` (D78), not `skye.base.dsl` or `skye.utils`: `build`, `build_cached`,
`clear_cache`, `load_document`, `check_text`, `format_text`, `to_text`, `Diagnostic`, `FormatError`, `SkyeSyntaxError` (raised by
`document.raise_for_errors()`, with `.diagnostics`) and `to_mermaid(spec, direction=None)`, which draws a flow or a router as a Mermaid
`flowchart` (the code behind `skye render`). `describe(spec, metadata=None)` tells what any block takes and gives back: a `PromptInfo`
for a prompt, a `RouterInfo` (routes with targets and fallbacks) for a router, a `FlowInfo` (context fields, start, nodes) for a flow.

## Prompt help

`from skye.prompts import describe_prompt, prompt_help, PromptInfo`: `describe_prompt(document.prompt("chat"), document.metadata)`
returns a `PromptInfo` (inputs with type, default and description; placeholders; roles; output fields) and `prompt_help(spec, metadata)`
the same as plain text (what `skye prompt info` prints). `BasePromptBuilder().help("planner_agent")` / `.describe(name)` work on a
registered template, bundled ones included. Import these from `skye.prompts`, not from `skye.base.dsl.info`. The specs are public
there too: `PromptSpec`, `PromptPartSpec`, `OutputSpec`; and `render_parts`, `output_json_schema`, `PromptParts`, `OutputSchema`
(prompt.md).

## MCP resources

`from skye.tools import ResourceProviderInterface, Resource`: the Port that lists resources and reads one by URI (`Resource` has `uri`,
`mime_type`, and `text` or `data`); the MCP clients of `skye.tools` implement it.

## Loading a file

- `skye.load("app.skye")` reads, parses and checks a file and returns the `Document` (`routers`, `flows`, `prompts`; `document.flow("name")`,
  `document.router()`, `document.prompt()`). A file with mistakes raises `ConfigurationError` whose message lists every one as
  `file:line:column reason fix`. Pass `registry_names=[...]` to check `registry.NAME` references. An unchanged file is not parsed again.
- `Flow.from_file("app.skye", name="research", registry={"planner": planner})` (also `skye.Flow`, or `from skye.flows import Flow`) loads one
  flow. `name` is optional when the file has one flow; `registry` is a dictionary of name to step, and `registry.NAME` must be one of its keys.
  `Flow.from_text(text, name=..., registry=..., filename=...)` does the same for a text. A `Flow` has `.spec`, `.name`, `.registry`,
  `.check()` (the mistakes now, with the registry keys) and `.to_text()`.
- `skye.load_config("skye.json", overrides={...})` reads the library settings (`log_level`, `component_log_levels`,
  `correlation_id_header`, `plugins` (the installed plugins that may load): no other key; an unknown key raises `ConfigurationError` naming it) from a JSON file, or from the file
  `SKYE_CONFIG` names when no path is given, and applies the log levels; precedence is code > environment > file. The
  settings file is JSON, not `.skye`. `skye.config.ConfigLoader` takes text (`from_text`, `from_dict`) and opens no file.

## Not built yet

Running a flow: `Flow.run(...)` raises `NotImplementedError` (the flow runtime belongs to the spec `3-runtime-flows`). `skye.load` and
`Flow.from_file` exist and validate, so a flow file is checked and built into specs, but it does not run. Say so when asked to run one, and
offer to check it and to write the steps as registry functions.
