---
title: "Status and roadmap"
status: current
---

# Status and roadmap

What you can use today, what is being built, and what is planned. Skye is before 1.0: the public API can still change
between minor versions. Each component has a spec in the repository (`.kiro/specs/`), where the tasks and their state are tracked.

## Released

| Component | What it does | Guide |
|---|---|---|
| `base` | Messages, completion types, errors, configuration and the Ports | [Architecture](../concepts/architecture.md) |
| `auth` | Authentication strategies, credential sources, secret managers, SigV4 | [Credentials and secrets](../guides/security/credentials.md) |
| `models` | Adapters for OpenAI, Anthropic, Bedrock, Azure OpenAI and Google, embeddings, structured output, token counting | [Call a provider](../guides/models/call-a-provider.md) |
| `store` | State backends: memory, file, DynamoDB, Valkey/Redis, PostgreSQL, Lambda durable functions | [Choose a backend](../guides/state/choose-a-backend.md) |
| `router` | Aliases, strategies, fallbacks, retries, health and cooldown | [Aliases and fallbacks](../guides/routing/aliases-and-fallbacks.md) |
| `tools` | Capabilities: local functions, remote APIs, the MCP client; toolkits (`files`, `openapi`, `human`, `shell`) | [Local functions](../guides/tools/local-functions.md), [Toolkits](../guides/tools/toolkits.md) |
| plugins | `skye.Plugins()`: a decorator for each of nine kinds, provider profiles, `skye plugins`, and an offline `check_<kind>` for each | [Write a plugin](../guides/extend/write-a-plugin.md) |
| `.skye` tools | `skye check`, `fmt`, `render`, `new`, the VS Code extension; shared parts of a prompt with `include`, `use` and `override` | [CLI](../reference/cli.md), [The `.skye` language](../reference/skye-language.md) |

## In progress

| Component | State |
|---|---|
| `prompts` | Rendering, few-shot examples (as text or as messages), `.skye` prompts with shared parts, six bundled prompts (extraction, code generation, summarization, explanation, question answering and a ReAct agent) and a gallery of 26 more to copy, and `render_parts` work; audio, video and files in a prompt wait for the typed content blocks of `base` (only images are attached today) |

## Planned

These components have a design and a spec but no released code. They are not part of the API yet.

| Component | What it will do |
|---|---|
| `agents` | One agent loop, `AgentLoop`, with a hook before and after each operation, and the built-in agent `REACT`; streaming checks at checkpoints; suspend and resume across Lambda invocations; an infinite-context mode and tools written by the agent. See [Agents (preview)](../concepts/agents-preview.md). |
| `memory` | Conversation and long-term memory (episodic, semantic, procedural, persona, working) behind one Port, with a vector store (Valkey, pgvector) |
| `guard` | Safety filters and pre-flight checks the runtime uses through a Port |
| `policy` | A policy engine inspired by [Cedar](https://www.cedarpolicy.com/), in pure Python: `permit` and `forbid` over principal, action and resource, guarding tools, models and memory |
| `observe` | Events, logs, metrics and traces behind Ports, for any observability stack |
| `gateway` | An MCP endpoint over a shared catalogue of tools, with a toolset per operation chosen by hybrid search or a decision model |
| `teams` | Several units (models, agents, flows, teams) toward one objective |
| `flows` | Steps with conditions, parallel branches, bounded loops, retries and timeouts, written in `.skye` |

## How decisions are made

Requirements and decisions are written down before code: `.kiro/steering/10-requirements.md` lists what each component must do and
`.kiro/steering/12-decisions.md` records every decision, with the questions still open. Read them on
[GitHub](https://github.com/ggiallo28/skye/tree/main/.kiro/steering).
