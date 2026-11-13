---
title: "Codename glossary"
status: current
---

# Codename glossary

A codename is a small watermark in the Nimbus cloud and weather theme. The plain name is always the real name; a codename never appears in an import path, folder, file, class, function or config key.

## Component codenames (15)

| Codename | Component | Role |
|----------|-----------|------|
| stratus | `base` | Messages, completion, errors, config and the Ports (interfaces). Standard library only. |
| ozone | `auth` | Authentication and credentials: strategies, credential sources and a token cache. Authorization is `policy`. |
| zephyr | `models` | Adapters to every kind of model API (LLMs, embeddings, decision models) and the shared HTTP transport. |
| lake | `store` | External state: in-memory, file, DynamoDB, Redis, PostgreSQL. |
| jet | `router` | ModelRouter, routing strategies, health tracking and fallbacks. |
| updraft | `tools` | Tool registry, local functions, remote APIs and the MCP client. |
| cirrus | `prompts` | Loaders, role-based messages and templates. |
| dew | `memory` | Memory implementations behind the memory Port. |
| halo | `guard` | Safety filters. |
| isobar | `policy` | Policy engine (Cedar-inspired): authorization decisions. |
| radar | `observe` | Events, logs, metrics and traces. |
| horizon | `gateway` | MCP gateway with a toolset per operation. |
| cyclone | `agents` | The agent loop (`AgentLoop`), the built-in agent `REACT` and hooks. |
| front | `teams` | Optional teams of agents. |
| stream | `flows` | Optional flows (workflows). |

## Documentation-only watermarks

These are not component codenames and are not counted among the 15.

| Watermark | Meaning |
|-----------|---------|
| vapor | The `Runnable` Port (composition abstraction). |
| nimbus | The whole project; the umbrella watermark, free after the rename to Skye. |

## `auth` and `policy`

`auth` is authentication and credentials (who are you, how do you prove it). `policy` is authorization (may this principal perform this action on this resource).

## Words used in the code and the documentation

### Capability, tool and function call

These three words name the same thing: something a language model can ask the program to run. The library says **capability** in type and
variable names (`CapabilityInterface`, `CapabilityRegistry`, `capability_calls`). **Tool** and **function call** are the words of the
providers and of the MCP protocol, so they appear where a provider or MCP wire format is described (`tools=` in an OpenAI request, an MCP
tool). The folder `skye.tools` keeps its name for the same reason.

### Port and Interface

A **Port** is the contract a class implements to plug into the library. In code a Port is a class named `*Interface` (`ModelInterface`,
`MemoryInterface`, `ObserverInterface`). Three Ports keep another name and are documented exceptions: `Runnable`, `DecisionModel` and
`StorageBackend`. "Interface" in prose means the same as Port.

### Naming rules

- A name says what a user does or has: a verb for an action, a noun for a thing.
- The synchronous form is `x` and the asynchronous form is `ax` (`complete` and `acomplete`, `stream` and `astream`, `invoke` and `ainvoke`).
- `get_x` reads one thing, `list_x` reads many, `set_x` configures, `register` adds to a registry.
- A file is named after the one idea in it: a provider file `<provider>.py`, an embeddings file `<provider>_embeddings.py`.
- A public class name is defined once; another path re-exports it. A test (`tests/budget/test_unique_names.py`) fails on a name defined twice.
