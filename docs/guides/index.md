---
title: "Guides"
status: current
---

# Guides

Each guide shows how to do one thing, with code that runs. If you are new to Skye, start with [Get started](../get-started/index.md).

| Area | Guides |
|---|---|
| Models | [Call a provider](models/call-a-provider.md) · [Streaming and async](models/streaming.md) · [Structured output](models/structured-output.md) · [Images](models/images.md) · [Embeddings](models/embeddings.md) · [Tokens and cost](models/tokens-and-cost.md) |
| Routing | [Aliases and fallbacks](routing/aliases-and-fallbacks.md) · [Strategies](routing/strategies.md) · [Health and cooldown](routing/health-and-cooldown.md) · [Router state in a store](routing/router-state.md) |
| Prompts | [Write a prompt in .skye](prompts/write-a-prompt.md) · [Variables and filters](prompts/variables-and-filters.md) · [Few-shot examples](prompts/few-shot.md) · [Output schema](prompts/output-schema.md) |
| Tools | [Local functions](tools/local-functions.md) · [Remote APIs](tools/remote-apis.md) · [MCP client](tools/mcp-client.md) · [Toolkits](tools/toolkits.md) |
| State | [Choose a store backend](state/choose-a-backend.md) |
| Security | [Credentials and secrets](security/credentials.md) |
| Operations | [Configuration](configuration.md) · [Observability](observability.md) |
| Extend Skye | [Which Port to implement](extend/index.md) · [Write a plugin](extend/write-a-plugin.md) · [Custom provider](extend/custom-provider.md) · [Custom store backend](extend/custom-store.md) · [Custom capability](extend/custom-capability.md) |

Every guide links to its runnable examples in
[`examples/`](https://github.com/ggiallo28/skye/tree/main/examples), which run offline: without an API key they use a scripted
client and say so.
