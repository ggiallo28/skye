---
inclusion: fileMatch
fileMatchPattern: 'src/skye/models/**|src/skye/tools/**|src/skye/gateway/**|src/skye/auth/**'
---

# Component code rules: models, tools, gateway, auth (Skye)

## Provider adapters (`models`)
All provider-specific transformation is **encapsulated inside the adapter class**; the router, the tools and the contracts stay
provider-agnostic.
- The adapter turns Skye requests into the provider format and provider responses back into Skye types, including message and
  capability formats and tool-call extraction.
- Prefer a thin **stdlib REST** adapter over a vendor SDK. A provider extra exists only where no stdlib path exists, and it declares
  exactly that one SDK (see `00-rules.md` and `budgets.toml`). No vendor SDK is on the core import path.
- A model provider has **one implementation at a time and no selector**.
- To add a provider, create a new adapter class and implement its transformation methods; change nothing in core code.

## MCP (`tools`)
MCP is **client-only**: Skye consumes MCP tools, resources and prompts; the server-side role belongs to `gateway`.
- The built-in stdlib client is the **default**: `create_mcp_client(target, impl="skyemcp")`. `fastmcp` is an optional substitute chosen
  only by `impl="fastmcp"` (extra `mcp`, its own budget). There is **no** environment variable, config entry or fallback for it.
- The **tools** facet reuses the interfaces in `tools`. The **prompts** facet reuses the `PromptBuilderInterface` Port and the message
  types in `base`. **`tools` never imports the `prompts` component.**
- Conversion from official MCP types to Skye types happens in the single boundary module.
- Where MCP **resources** live is open (O7): do not add a rule for it.

## Security (`models`, `gateway`, `auth`)
- **Never hardcode secrets.** Read credentials from environment variables or a secret manager (AWS Secrets Manager, SSM, Key Vault,
  Google Secret Manager). Support `${VAR}` substitution in configuration; never commit a key.
- `auth` is **authentication and credentials**; `policy` is **authorization**. Keep them apart: no authorization logic in `auth`, no
  credential handling in `policy`.
- Validate external input at the boundary. Never log secret values; refer to them by key name.
