---
title: "Extras"
status: current
---

# Extras

This page lists every optional extra of the `skyeai` package: what it enables, the library it installs, whether that library is
compiled and its size budget, so you install only what your function needs.

The standard install has no third-party dependency and works with no extra. Every provider (OpenAI, Anthropic, Bedrock, Azure OpenAI,
Google, Cohere) is called through a built-in REST adapter, so you never need an extra to call a model.

=== "pip"

    ```bash
    pip install skyeai
    pip install "skyeai[valkey,tokens]"
    ```

=== "uv"

    ```bash
    uv add skyeai
    uv add "skyeai[valkey,tokens]"
    ```

## Extras that install a library

| Extra | What it enables | Library installed | Compiled | Budget over the core |
|---|---|---|---|---|
| `auth` | RS256 signing for service-account authentication (Google service-account JWT, Azure certificate assertion) | `rsa` | no | 1 MB |
| `valkey` | the Valkey/Redis store backend with the valkey-py driver, preferred when installed | `valkey` | no | 13 MB |
| `redis` | the same backend with the redis-py driver | `redis` | no | 13 MB |
| `postgres` | the PostgreSQL store backend with the pg8000 driver | `pg8000` | no | 4 MB |
| `postgres-asyncpg` | the PostgreSQL store backend with the asyncpg driver, faster | `asyncpg` | yes | 15 MB |
| `aws` | DynamoDB and the PostgreSQL RDS Data API outside AWS Lambda | `boto3` | no | not gated: preinstalled in Lambda |
| `tokens` | exact token counts for `gpt-*`, `o1-*` and `o3-*` models; without it a standard-library estimate is used | `tiktoken` | yes | 20 MB |
| `mcp` | the optional `fastmcp` MCP client, chosen with `skye.mcp_client(target, impl="fastmcp")` (or `create_mcp_client`); the built-in client needs nothing | `fastmcp-slim[client]` | yes, among its dependencies | not gated |

Each budget is the most megabytes the extra may add over the core on Linux x86_64. `tests/budget` measures it in a clean environment
on every pull request; see [Size and load budgets](../project/budgets.md). `mcp` and `aws` are not gated because they install a
library Skye does not need for its own features.

The in-memory, file and durable-function store backends need no extra. In AWS Lambda, DynamoDB and the RDS Data API need none either,
because `boto3` is already there.

## Extras that install nothing

These extras exist so that older install commands keep working. They add no library.

| Extra | Why it is empty |
|---|---|
| `openai`, `anthropic`, `bedrock`, `google`, `cohere` | each provider has a built-in REST adapter; Bedrock is signed with SigV4 in the standard library, so `boto3` is not needed |
| `agents`, `prompts`, `tools`, `guard`, `teams`, `flows`, `observe`, `memory` | these components are part of the core, or install the extra of the backend they use (`memory` uses a store backend's extra) |

## Bundles

| Extra | Libraries installed |
|---|---|
| `llm-providers`, `embedding-providers`, `all-providers`, `providers` | `tiktoken` |
| `all` | `tiktoken`, `redis`, `pg8000`, `fastmcp-slim[client]`, `rsa` |

`all` is not meant for a serverless function: it carries the heavy `mcp` dependencies. It does not include `valkey`,
`postgres-asyncpg` or `aws`; add them by name if you need them.

## When an extra is missing

Optional libraries are imported inside the function that first needs them, never when you `import skye`. If you use a feature whose
extra is not installed, Skye raises `MissingExtraError`, which names the extra to install.

## See also

- [Serverless first](../concepts/serverless-first.md): why extras are split by need.
- [Size and load budgets](../project/budgets.md): how the size of each extra is measured.
- [Choose a store backend](../guides/state/choose-a-backend.md): which store extra to pick.
