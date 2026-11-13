---
title: "Skye"
status: current
---

# Skye

**A Python library for LLM applications, built for serverless.** Skye calls every major model provider through built-in
adapters written on the standard library, routes requests across models with fallbacks, and describes routers and prompts in one
small language, `.skye`. `pip install skyeai` installs no third-party package, so a Lambda function starts fast and stays small.

[Get started](get-started/index.md){ .md-button .md-button--primary }
[See the guides](guides/index.md){ .md-button }

<div class="grid cards" markdown>

-   **Standard library only**

    ---

    Every provider adapter, the router, prompts and the `.skye` tools run on the Python standard library. Extras add a library
    only where you need one, such as a store driver. [Serverless first](concepts/serverless-first.md)

-   **Every provider, one call**

    ---

    `skye.provider("openai" | "anthropic" | "bedrock" | "azure" | "google", ...)` returns a client with the same `complete`,
    `stream` and async methods. [Call a provider](guides/models/call-a-provider.md)

-   **Routing and fallbacks**

    ---

    Aliases over several models, strategies, retries, health tracking and cooldown, with state kept in DynamoDB, Valkey or
    PostgreSQL across invocations. [Routing](guides/routing/aliases-and-fallbacks.md)

-   **One language for configuration**

    ---

    Routers and prompts written in `.skye`, checked by `skye check`, formatted by `skye fmt`, drawn by `skye render`, with a
    VS Code extension. [The .skye language](concepts/skye-language.md)

</div>

## Ten lines

```python
import skye
from skye import UserMessage

client = skye.provider("openai", api_key="sk-...")
response = client.complete(messages=[UserMessage(content="Hello!")], model="gpt-4o-mini")
print(response.content)
```

The same router, in `.skye`:

```skye
router "app" {
  route "chat" = ["openai/gpt-4o-mini", "anthropic/claude-haiku"]   # the first is primary, the rest are fallbacks
}
```

## What is in the box

| Area | Status | Start here |
|---|---|---|
| Model providers (LLMs, embeddings, structured output, streaming) | released | [Call a provider](guides/models/call-a-provider.md) |
| Router (aliases, strategies, fallbacks, health) | released | [Aliases and fallbacks](guides/routing/aliases-and-fallbacks.md) |
| Prompts in `.skye` | released | [Write a prompt](guides/prompts/write-a-prompt.md) |
| Tools: local functions, remote APIs, MCP client, toolkits | released | [Local functions](guides/tools/local-functions.md) |
| State backends (memory, file, DynamoDB, Valkey/Redis, PostgreSQL) | released | [Choose a backend](guides/state/choose-a-backend.md) |
| Plugins: your own provider, backend, toolkit, routing strategy or agent, with one object, `skye.Plugins()` | released | [Write a plugin](guides/extend/write-a-plugin.md) |
| Agents, memory, guard, policy, gateway, teams, flows | planned | [Status and roadmap](project/roadmap.md) |

## Find your way

- [Get started](get-started/index.md): install, a first call, a first router, a first `.skye` file, Lambda.
- [Guides](guides/index.md): how to do one thing, with code that runs.
- [Concepts](concepts/index.md): how Skye is built and why.
- [Reference](reference/index.md): the Python API, the CLI, the language, the configuration keys and the extras.
- [Status and roadmap](project/roadmap.md), [Size and load budgets](project/budgets.md), [Contributing](project/contributing.md),
  [Glossary](project/glossary.md).
