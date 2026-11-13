# Plugins: add a provider, a backend, a tool set or an agent to Skye

Skye is extended without changing it. Create one handle and add to it; what you add is there as soon as the line runs.

```python
import skye

plugins = skye.Plugins()


@plugins.template_filter("shout")
def shout(value):
    return str(value).upper() + "!"
```

## The nine kinds

| Kind | Add it with | Build it by name |
|---|---|---|
| `provider` (model, embedding, decision) | `@plugins.provider("name", profile=...)` | `skye.provider("name")` |
| `backend` (store) | `@plugins.backend("name")` | `skye.backend("name")` |
| `credential_source` | `@plugins.credential_source("name")` | `skye.credential_source("name")` |
| `routing_strategy` | `@plugins.routing_strategy("name")` | `skye.routing_strategy("name")` |
| `mcp_client` | `@plugins.mcp_client("name")` | `skye.mcp_client(target)` |
| `tokenizer` | `@plugins.tokenizer("name")` | by the `tokenizer` of a model profile |
| `template_filter` | `@plugins.template_filter("name")` | `{{ x \| name }}` in a prompt |
| `agent` | `@plugins.agent("name")` | `skye.agent("name", ...)` |
| `toolkit` | `@plugins.toolkit("name")` | `skye.toolkit("name", **options)` |

A name that is already registered raises `ConfigurationError`; pass `replace=True` to replace it on purpose. The kind `provider` is told
apart by `function="model"|"embedding"|"decision"`, or by the methods of the class (`generate`, `aencode`, `decide`).

## A provider is declared once, in its profile

The name, the key variables, the endpoint and the prices of a provider live in its profile and nowhere else. Never write
`"OPENAI_API_KEY"`, a base URL or a price as a literal in code: read it from the profile.

```python
from skye.models import OpenAICompatibleProvider
from skye.plugins import ModelProfile, ProviderProfile

plugins.provider(
    "acme",
    OpenAICompatibleProvider,  # an OpenAI-format API needs no class of your own
    profile=ProviderProfile(
        "acme",
        api_key_variables=("ACME_API_KEY",),
        default_api_base="https://api.acme.example/v1",
        models={"acme-small": ModelProfile(prompt_price=0.10, completion_price=0.40)},
    ),
)
client = skye.provider("acme")  # the key is read from ACME_API_KEY
```

Built-in profiles are `profile.toml` files in `models/plugins/<provider>/`. To change one that exists, merge instead of replacing it:
`plugins.profile("openai", models={"gpt-4o-mini": {"prompt_price": 0.2}})` changes only the fields given.

## Write the async form only

- A model provider writes `async def _acall_provider(request)` and the async generator `_acall_provider_stream(request)`;
  `complete` and `stream` are derived from `acomplete` and `astream`. Blocking I/O goes in `asyncio.to_thread`.
- An embedding provider writes `aencode` and `aencode_batch`; `encode` and `encode_batch` are derived.
- A subclass that still defines `_call_provider`, `_call_provider_stream` or `_encode_batch_impl` does not instantiate.

## Toolkits: tools an agent takes apart from its own

- `skye.Toolkit` is the base class: each method with `@capability` becomes a tool named `<toolkit>.<name>`; `alias=` renames the prefix.
- Built-in toolkits: `files` (read only, `root=` or `roots=[...]`, hidden names excluded), `openapi` (`spec=`, GET only unless `allow`),
  `human` (`channel` `console` or `file`, to ask or hand a case over), `shell` (an `allow` list of executables is required, no shell,
  not a sandbox).
- `skills=[...]` on an agent adds one `files` toolkit over the folders of its skills.

## Check a plugin offline, find it from the command line

- One function per kind returns the names of the checks that passed or raises `AssertionError` naming the first that failed:
  `check_provider`, `check_backend`, `check_credential_source`, `check_routing_strategy`, `check_mcp_client`, `check_tokenizer`,
  `check_template_filter`, `check_agent`, `check_toolkit` (each imported from its owner package: `skye.models`, `skye.store`, `skye.auth`, `skye.router`, `skye.tools`, `skye.prompts`, `skye.agents`).
- `skye plugins` lists what is registered per kind and each installed plugin: loaded, failed (with the error) or skipped.
- A package ships a plugin with an entry point in the group `skye.plugins` that names a module; Skye imports it at the first unknown
  name. The `plugins` key of the configuration file lists the installed plugins that may load.
