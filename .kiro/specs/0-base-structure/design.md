---
component: none (cross-cutting: structure, base contracts, consolidation, documentation)
---

# Design Document: structure

Builds on: #[[file:.kiro/steering/11-design.md]] (sections: Layers, Allowed imports, Installation, Ports, Composition, Extension points, Base contracts, Transport and providers, Store layout, Extras and budgets, Auth component, MCP client, Codename placement, Correctness properties).
The high-level design lives there. This file holds only the detail of this spec: the target package tree and the file-by-file mapping of the migration,
the overlap resolutions, the data model locations, error handling, the testing strategy, the rename and governance notes, the wiki detail, the detailed
design of the base contracts (former `skye` spec) and the consolidation history.

## Target package tree

The target tree places a real `base` package at the foundation and a curated top-level `__init__.py`. `base` is a real importable package, not only a conceptual layer (Requirement 3).

```
src/skye/
├── __init__.py                 # re-exports ONLY: messages, completion, exceptions, config (Req 6)
│
├── base/                       # Layer 0 — standard library only, no I/O (Req 2, 3)
│   ├── __init__.py
│   ├── messages.py             # core message models
│   ├── completion.py           # CompleteRequest / CompleteResponse
│   ├── capability_schema.py    # pure capability schema/contract (lets completion drop its tools import)
│   ├── exceptions.py           # SkyeError hierarchy, incl. MissingExtraError
│   ├── config.py               # configuration loading
│   ├── http.py                 # the single stdlib-only HTTP transport (sanctioned exception to no-I/O; shared by auth, models, tools)
│   └── interfaces/             # Ports (interfaces), no I/O, no import of layers >0 (Req 3)
│       ├── __init__.py
│       ├── model.py            # ModelInterface port
│       ├── decision.py         # DecisionModel port (Jev contract) (Req 4)
│       ├── runnable.py         # Runnable port: one input → one output (Req 11)
│       ├── vector_encoder.py
│       ├── storage.py          # store port (Overlap 10.2 target: port side)
│       ├── registry.py         # unified registry port (Overlap 10.1 target: port side)
│       ├── cost_calculator.py  # cost port (Overlap 10.3)
│       ├── error_handler.py    # error port (Overlap 10.3)
│       ├── token_counter.py    # token port (Overlap 10.3)
│       ├── memory.py           # memory port (impl stays in memory Component; removes base→memory leak, Req 2)
│       ├── router.py
│       ├── safety.py
│       ├── observer.py
│       ├── event_handler.py
│       ├── content_reader.py
│       ├── multimodal_handler.py
│       ├── prompt.py
│       ├── config_loader.py
│       ├── plugin.py
│       ├── capability.py       # capability port
│       ├── authorizer.py       # authorizer Port: principal, action, resource -> permit/forbid; implemented by policy (Req 17)
│       └── authentication.py   # authentication Port; implemented by auth (Req 18)
│
├── auth/                       # Layer 0 — authentication and credentials; imports only base (Req 18)
│   ├── __init__.py
│   └── sigv4.py                # SigV4 signer (moved from models/transport); strategies and credential sources land in the auth and models specs
│
├── models/                     # Layer 1 — adapters to every model API kind (Req 4)
│   ├── __init__.py
│   ├── base.py                 # shared base adapter (from providers/base.py, split)
│   ├── registry.py             # provider/model registry impl (Overlap 10.1 target: impl side)
│   ├── transport/              # ONE shared stdlib transport, retry, error mapping, token counting (Req 4)
│   │   ├── __init__.py
│   │   ├── http.py             # re-exports base/http.py (the single stdlib urllib transport; no httpx/requests)
│   │   ├── streaming.py        # stdlib SSE (text/event-stream) parser
│   │   ├── retry.py            # shared retry policy (max 3 attempts, Req 4)
│   │   ├── error_mapping.py    # provider error → Skye error
│   │   ├── token_counter.py    # token counting impl
│   │   └── multimodal.py       # multimodal content handling
│   ├── llm/                    # large language model adapters (stdlib REST dialects)
│   │   ├── __init__.py
│   │   ├── openai_compatible.py # OpenAI wire format (parametrized by base_url/api_key); openai.py and azure.py hold the vendor specifics
│   │   ├── anthropic.py        # Anthropic Messages API (/v1/messages)
│   │   └── bedrock.py          # AWS Bedrock via shared SigV4 over urllib
│   ├── embeddings/             # embedding model adapters
│   │   ├── __init__.py
│   │   ├── bedrock_embeddings.py
│   │   ├── cohere_embeddings.py
│   │   ├── openai_embeddings.py
│   │   ├── google_embeddings.py
│   │   └── google_multimodal_embeddings.py
│   └── decision/               # Decision_Model (Jev) — third model kind (Req 4)
│       ├── __init__.py
│       └── jev.py              # DecisionModel implementation
│
├── store/                      # Layer 1 — ONE shared package for external state (Req 5)
│   ├── __init__.py
│   ├── memory.py               # in-memory backend
│   ├── file.py                 # file backend
│   ├── dynamodb.py             # DynamoDB backend (first-choice durable, Req 5)
│   └── redis.py                # Redis backend
│
├── router/                     # Layer 2 — ModelRouter and routing concerns
│   ├── __init__.py
│   ├── model_router.py
│   ├── routing_strategies.py
│   ├── health_tracker.py       # health tracking used by routing
│   ├── config_models.py
│   └── fallbacks.py
│
├── tools/                      # Layer 2 — capabilities (MCP "tool" terminology) (Req 1, naming)
│   ├── __init__.py
│   ├── registry.py
│   ├── local_function.py
│   ├── remote_api.py           # HTTP via stdlib urllib transport; httpx/requests eliminated (Req 7)
│   ├── mcp_client.py           # create_mcp_client(target, impl="skyemcp"): the one factory (Req 21)
│   │                           # (removed 2026-11-08: the legacy MCPCapability and MCPServerClient probes; the built-in client is mcp_client.py)
│   ├── mcp_fastmcp.py          # fastmcp-backed client (mcp extra) behind the same Port
│   ├── mcp_boundary.py         # the single conversion point from official MCP types to Skye types (Req 15)
│   ├── mcp_resource.py         # re-exports Resource and ResourceProviderInterface from the resource Port in base (D26)
│   ├── capability_call_handler.py
│   ├── decorator.py
│   └── exceptions.py
│
├── prompts/                    # Layer 2 — loaders, role-based messages, templates
│   ├── __init__.py
│   ├── loaders.py
│   ├── messages.py
│   └── templates/
│
├── memory/                     # Layer 2 — declared-but-minimal this step (Req 6, A3)
│   └── __init__.py
├── guard/                      # Layer 2 — declared-but-minimal this step (Req 6, A3)
│   └── __init__.py
├── observe/                    # Layer 2 — declared-but-minimal this step (Req 6, A3)
│   └── __init__.py
├── policy/                     # Layer 2 — declared-but-minimal; implements the authorizer Port (content in policy spec)
│   └── __init__.py
│
├── gateway/                    # Layer 3 — NEW declared-but-minimal (content in gateway spec)
│   └── __init__.py
├── agents/                     # Layer 3 — declared-but-minimal (content in agents spec)
│   └── __init__.py
├── teams/                      # Layer 3 — declared-but-minimal; coordinates units toward a shared objective (content in teams spec)
│   └── __init__.py
└── flows/                      # Layer 3 — declared-but-minimal; sequences units into ordered steps (content in flows spec)
    └── __init__.py
```

Notes:

- `base` is a real package containing the core models, the error hierarchy, configuration loading, and the Ports — all four module groups (Requirement 3).
- The Decision_Model (Jev) lives in `models/decision/`, as a third model kind alongside LLMs and embeddings (Requirement 4); its contract (the `DecisionModel` Port) lives in `base/interfaces/decision.py` (Requirement 4).
- The lazy-import mechanism is the standard library plus a thin `MissingExtraError` helper in `base` (see Lazy imports at boundaries); it imports only standard-library `importlib`, so it is compatible with the base-layer stdlib-only rule (Requirement 2).

### Import paths (component, not layer)

The public import path uses the **Component** name, never the Layer name. A Layer is Axis-1 metadata consumed only by the AST import test (see Two independent axes); it is not a package and never appears in an import path.

Valid import paths name a Component:

```python
import skye                       # curated base re-exports: messages, completion, exceptions, config (Req 6)
from skye.models.llm import ...   # Component "models"
from skye.store import ...        # Component "store"
from skye.router import ...       # Component "router"
from skye.gateway import ...      # Component "gateway"
```

There is **no** `skye.base`-as-layer, **no** `skye.adapters`, **no** `skye.services`, and **no** `skye.runtime` in any import path. The four Layer names (`base` as an ordinal, `adapters`, `services`, `runtime`) are not importable packages — only `base` exists as a real package, and it does so as a Component, not as "the base layer."

Rationale:

- The Layer is only AST-test metadata (Axis 1). A Component may be reassigned to a different Layer without breaking a single import path, because paths are keyed to the Component name that does not change.
- The Layer names `adapters`, `services`, and `runtime` are not members of the 15-Component name set fixed by Requirement 1, so they must not appear in a path. Letting a layer name into an import path would break the shared-name rule (Requirement 1), which binds the package folder, spec folder, module package, and docs section to one identical Component name.
- This mirrors the spirit of the codename rule: structural/taxonomic labels (layers, codenames) are kept out of import paths, which carry only the plain Component name.

`base` is still a real package at `skye/base/`, but its curated public surface (`messages`, `completion`, `exceptions`, `config`) is re-exported at the top level so users reach it through `import skye` (Requirement 6).

## Data Models

The structure spec defines **where** data models live and the boundary rules they obey; it does not redefine their fields. Per Assumption A1, the `base` package must import without pydantic for structural purposes, so the models below are described by role and location, independent of whether they are pydantic models or dataclasses (the pydantic-to-dataclasses migration is a separate later spec, Requirement 3).

| Model group | Location | Description | Boundary rule |
|-------------|----------|-------------|---------------|
| Messages | `base/messages.py` | `SkyeMessage` and role variants (user/assistant/system/capability) | stdlib-only; no import of layers >0 (Req 3) |
| Completion | `base/completion.py` | `CompleteRequest` / `CompleteResponse` | references the capability **schema** in base, not the `tools` Component (removes `completion`→`capabilities`, Req 2) |
| Capability schema | `base/capability_schema.py` | pure capability contract (name, description, parameter schema) | pure contract in base; runtime handlers/registry stay in `tools` |
| Error hierarchy | `base/exceptions.py` | `SkyeError` and subclasses incl. `MissingExtraError` | stdlib-only (Req 3, 6) |
| Config | `base/config.py` | configuration loading and `${VAR}` substitution | stdlib-only (Req 3, 2) |
| Decision result | returned by the `DecisionModel` Port | a choice from a finite option set + per-option probability in `[0,1]` summing to `1.0` | contract in `base/interfaces/decision.py`; impl in `models/decision/` (Req 4) |
| Router config | `router/config_models.py` | route aliases, targets, strategy, rate limits | services layer; consumes base ports only |
| Store records | `store/*.py` | backend-specific record/state shapes | one location per backend in `store` (Req 5) |
| Resource (MCP) | `tools` (MCP client) | MCP resource read by URI: a MIME type and either text or bytes | type internal to `tools`, returned by the MCP client; **no base Port** and no new Component today (Requirement 15). When `prompts`/`memory` consume resources, a resource Port is added to `base` per the no-horizontal-import rule (see the MCP section) |

## Current-file mapping table

Every current file maps to a target location, or is marked split/merge/delete with a one-line reason. This table is the declared target; `tasks.md` executes the moves.

| Current path | Target | Reason |
|--------------|--------|--------|
| `__init__.py` | `skye/__init__.py` (curated) | Re-export only messages, completion, exceptions, config (Req 6). |
| `messages.py` | `skye/base/messages.py` | Core models belong in base (Req 3). |
| `completion.py` | `skye/base/completion.py` | Core models in base; its `capabilities` import is replaced by the base capability schema (Req 2). |
| `exceptions.py` | `skye/base/exceptions.py` | Error hierarchy in base; hosts MissingExtraError (Req 3, 6). |
| `config.py` | `skye/base/config.py` | Configuration loading in base (Req 3). |
| `interfaces/__init__.py` | `skye/base/interfaces/__init__.py` | Ports belong in base (Req 3). |
| `interfaces/model.py` | `skye/base/interfaces/model.py` | Port. |
| `interfaces/capability.py` | `skye/base/interfaces/capability.py` | Port. |
| `interfaces/config_loader.py` | `skye/base/interfaces/config_loader.py` | Port. |
| `interfaces/content_reader.py` | `skye/base/interfaces/content_reader.py` | Port. |
| `interfaces/cost_calculator.py` | `skye/base/interfaces/cost_calculator.py` | Cost Port (Overlap 10.3, port side). |
| `interfaces/error_handler.py` | `skye/base/interfaces/error_handler.py` | Error Port (Overlap 10.3, port side). |
| `interfaces/token_counter.py` | `skye/base/interfaces/token_counter.py` | Token Port (Overlap 10.3, port side). |
| `interfaces/event_handler.py` | `skye/base/interfaces/event_handler.py` | Port. |
| `interfaces/memory.py` | `skye/base/interfaces/memory.py` | Port stays in base; memory impl stays in `memory` Component, removing the base→memory import (Req 2). |
| `interfaces/multimodal_handler.py` | `skye/base/interfaces/multimodal_handler.py` | Port. |
| `interfaces/observer.py` | `skye/base/interfaces/observer.py` | Port. |
| `interfaces/plugin.py` | `skye/base/interfaces/plugin.py` | Port. |
| `interfaces/prompt.py` | `skye/base/interfaces/prompt.py` | Port. |
| `interfaces/router.py` | `skye/base/interfaces/router.py` | Port. |
| `interfaces/safety.py` | `skye/base/interfaces/safety.py` | Port. |
| `interfaces/storage.py` | `skye/base/interfaces/storage.py` | Store Port; backends go to `store` (Overlap 10.2). |
| `interfaces/vector_encoder.py` | `skye/base/interfaces/vector_encoder.py` | Port. |
| `interfaces/route_registry.py` | merge → `skye/base/interfaces/registry.py` | Unified registry port (Overlap 10.1). |
| `providers/__init__.py` | `skye/models/__init__.py` | Rename providers → models (naming, Req 1). |
| `providers/base.py` (1,043) | **split** → `skye/models/base.py` + `skye/models/transport/{http,streaming,retry,error_mapping,token_counter}.py` | 1,043-line file mixes base adapter with shared transport concerns; split by responsibility into the stdlib `urllib` transport (`http.py`, implemented in `base/http.py`), stdlib SSE streaming (`streaming.py`), plus the retry/error/token modules (Requirement 4). SigV4 signing goes to `auth` (Requirement 18). |
| `providers/retry.py` | `skye/models/transport/retry.py` | One shared retry policy (Req 4). |
| `providers/error_handler.py` | `skye/models/transport/error_mapping.py` | One shared error mapping (Req 4). |
| `providers/token_counter.py` | `skye/models/transport/token_counter.py` | One shared token counter (Req 4). |
| `providers/multimodal.py` | `skye/models/transport/multimodal.py` | Shared transport concern. |
| *(new)* | `skye/base/http.py` (re-exported by `skye/models/transport/http.py`) | The single shared JSON HTTP transport over stdlib `urllib.request`; replaces httpx/requests; shared by `models`, `tools`, and `auth` (Dependency policy). |
| *(new)* | `skye/models/transport/streaming.py` | Shared stdlib SSE (`text/event-stream`) parser for streaming (Dependency policy). |
| *(new)* | `skye/auth/sigv4.py` | AWS SigV4 signer over stdlib `hashlib`/`hmac`/`datetime`; lets Bedrock run without boto3; lives in `auth` (Requirement 18). |
| `providers/cost_calculator.py` | `skye/models/transport/` (cost impl) | Cost implementation in the responsible Component (Overlap 10.3, impl side). |
| `providers/health.py` | **merge** → `skye/router/health_tracker.py` | Health is consumed by routing; recommend merging into the router health tracker rather than keeping it in models. |
| `providers/registry.py` | merge → `skye/models/registry.py` (impl) behind `base/interfaces/registry.py` (port) | Unify the two registries (Overlap 10.1). |
| `providers/lazy_import.py` | `skye/base/` thin `missing_extra` helper over stdlib `importlib` | Reduced from a bespoke importer to a thin `MissingExtraError` wrapper over stdlib `importlib` (or removed in favor of stdlib + the helper); stdlib keeps base compliant (Req 2, 6; see Lazy imports). |
| `providers/llm/openai_provider.py` + `providers/llm/azure_provider.py` | **collapse** → `skye/models/llm/openai_compatible.py` (+ `openai.py`, `azure.py`) | One parametrized stdlib-REST adapter; Azure is the same `/v1/chat/completions` dialect with a different `base_url` and auth header (Dependency policy). |
| `providers/llm/anthropic_provider.py` | `skye/models/llm/anthropic.py` | Anthropic Messages API (`/v1/messages`) over stdlib REST; no SDK (Dependency policy). |
| `providers/llm/bedrock_provider.py` | `skye/models/llm/bedrock.py` | AWS Bedrock via shared stdlib SigV4 signer over `urllib`; no boto3 required (Dependency policy). |
| `providers/llm/vertex_provider.py` | `skye/models/llm/google.py` (own dialect, flagged) | The provider is renamed `google` (Assumption A6); it may need its own dialect rather than the OpenAI-compatible adapter. |
| `providers/embeddings/*` | `skye/models/embeddings/*` | Embedding adapters over the same stdlib transport; Cohere via the OpenAI-compatible path where applicable; Google embeddings may need their own dialect (Requirement 4; Dependency policy). |
| `capabilities/__init__.py` | `skye/tools/__init__.py` | Rename capabilities → tools (naming + MCP term, Req 1). |
| `capabilities/registry.py` | `skye/tools/registry.py` | Tools registry. |
| `capabilities/capability_call_handler.py` | `skye/tools/capability_call_handler.py` | Handler stays in tools. |
| `capabilities/capability_models.py` | **split** → `skye/base/capability_schema.py` (pure contract) + `skye/tools/` (runtime models) | Pure schema belongs in base so `completion` can drop its tools import (Req 2); runtime pieces stay in tools. |
| `capabilities/schema.py` | → `skye/base/capability_schema.py` | Capability schema is a pure contract (base). |
| `capabilities/decorator.py` | `skye/tools/decorator.py` | Tools decorator. |
| `capabilities/exceptions.py` | `skye/tools/exceptions.py` | Tools-local exceptions (base.exceptions holds the shared hierarchy). |
| `capabilities/interface.py` | → `skye/base/interfaces/capability.py` | Capability port in base. |
| `capabilities/local_function.py` | `skye/tools/local_function.py` | Local function capability. |
| `capabilities/mcp_capability.py` | *(removed 2026-11-08)* | The legacy MCP capability probe; superseded by `MCPToolCapability` in `mcp_client.py`. |
| `capabilities/mcp_server_client.py` | `skye/tools/mcp_client.py` | Tri-faceted MCP client in `tools` (tools/prompts/resources); built-in stdlib client and `fastmcp` behind one Port (Req 15). The legacy `mcp_server_client.py` module was removed on 2026-11-08. |
| *(new)* | `skye/tools/mcp_resource.py` | Re-exports `Resource` and `ResourceProviderInterface`, which live in `skye/base/interfaces/resource.py` (D26, Req 10.5); no new Component. |
| `capabilities/remote_api.py` | `skye/tools/remote_api.py` | HTTP calls use the shared stdlib `urllib` transport; the `httpx`/`requests` imports are eliminated at the source, not merely deferred (Req 7; Dependency policy). |
| `routes/__init__.py` | `skye/router/__init__.py` | Rename routes → router (name was misleading, Req 1). |
| `routes/config_models.py` | `skye/router/config_models.py` | Router config. |
| `routes/health_tracker.py` | `skye/router/health_tracker.py` | Stays in router (merge target for providers/health.py). |
| `routes/model_router.py` (1,105) | `skye/router/model_router.py` | Router core; large file, split deferred to its own spec (not required by structure). |
| `routes/routing_strategies.py` | `skye/router/routing_strategies.py` | Router strategies. |
| `routes/storage_backends.py` (665) | **split/move** → `skye/store/*` | Storage backends belong in the one shared store (Overlap 10.2, Req 5). |
| `prompts/__init__.py` | `skye/prompts/__init__.py` | Prompts Component. |
| `prompts/base.py` | `skye/prompts/loaders.py` + `messages.py` | Reuse liteprompt design (loaders, role messages, registry, truncation); see Prompts note. |
| `prompts/templates/` | `skye/prompts/templates/` | Templates. |
| `utils/__init__.py` | **delete/fold** → `skye/base/` | Keep utilities in base rather than a loose `utils` package; justify under Store/utility note. |
| `utils/validation.py` | `skye/base/` (small validation util) | Pure validation helper used across layers belongs at the foundation. |
| `agents/__init__.py` | `skye/agents/__init__.py` | Declared-but-minimal; content in agents spec (Req 6, A3). |
| `guard/__init__.py` | `skye/guard/__init__.py` | Declared-but-minimal (Req 6, A3). |
| `memory/__init__.py` | `skye/memory/__init__.py` | Declared-but-minimal (Req 6, A3). |
| `observe/__init__.py` | `skye/observe/__init__.py` | Declared-but-minimal (Req 6, A3). |
| *(new)* | `skye/policy/__init__.py` | NEW declared-but-minimal; real content in policy spec (Req 6). |
| *(new)* | `skye/gateway/__init__.py` | NEW declared-but-minimal; real content in gateway spec (Req 6). |
| *(new)* | `skye/teams/__init__.py` | NEW declared-but-minimal; coordinates units toward a shared objective; content in teams spec (Req 6). |
| *(new)* | `skye/flows/__init__.py` | NEW declared-but-minimal; sequences units into ordered steps; content in flows spec (Req 6). |
| *(new)* | `skye/base/interfaces/runnable.py` | NEW `Runnable` composition Port in base (Requirement 11). |
| *(new)* | `skye/base/interfaces/authorizer.py`, `skye/base/interfaces/authentication.py` | NEW authorizer and authentication Ports in base (Requirements 17, 18). |
| *(new)* | `skye/auth/__init__.py` | NEW declared-but-minimal Layer-0 Component (Requirement 18). |

**Prompts note (target, not a move):** the prompts Component reuses the liteprompt design (loaders, role-based messages, registry, truncation) but **not** its Jinja2 engine. Jinja2 pulls a compiled package and is not guaranteed in the target serverless runtime; although `jinja2` is a core dependency in `budgets.toml` today, the target avoids depending on a compiled template engine. This is a target direction, not an executed change.

## Overlap resolutions

Each Overlap has exactly one resolution location (Requirement 10), recorded as a target.

### Overlap A — two registries (Requirement 10)

Sources: `interfaces/route_registry.py` and `providers/registry.py`. Resolution: one registry **Port** in `skye/base/interfaces/registry.py` and one **implementation** owned by the `models` Component at `skye/models/registry.py`. The `models` Component owns the implementation because the registry's primary job is to register and resolve model adapters; the router consumes it through the base port. This is a single unification location.

### Overlap B — two storage concepts (Requirement 10)

Sources: `interfaces/storage.py` and `routes/storage_backends.py`. Resolution: the storage **Port** stays in `skye/base/interfaces/storage.py`; the concrete **backends** move into the one shared `store` Component (`skye/store/{memory,file,dynamodb,redis}.py`). The `store` Component is the single unification target (Requirements 10, 5).

### Overlap C — scattered cost, error, token (Requirement 10)

For each of the three concepts, the interface placement is a Port in `base`, and the implementation placement is in the responsible Component:

| Concept | Port (base/interfaces) | Implementation |
|---------|------------------------|----------------|
| cost | `cost_calculator.py` | `skye/models/transport/` (cost impl, from `providers/cost_calculator.py`) |
| errors | `error_handler.py` | `skye/models/transport/error_mapping.py` (from `providers/error_handler.py`) |
| tokens | `token_counter.py` | `skye/models/transport/token_counter.py` (from `providers/token_counter.py`) |

Each concept has exactly one port location and one implementation location.

### Planned spec renames (Requirement 10, recorded as future actions)

`skye → base`, `model-providers → models`, `capability-support → tools`, `prompts-support → prompts`, `policy-engine → policy`, `agent-runtime → agents`, `gateway` unchanged, and `skye-consolidation` folded into `structure`. These are declarations only; each spec is renamed by its own task, never as a side effect of this one.

## Error Handling

- **MissingExtraError.** A custom exception in the `SkyeError` hierarchy, defined in `skye/base/exceptions.py`. It is raised when code uses an optional Component whose Extra is not installed; it wraps the underlying `ImportError`/`ModuleNotFoundError` and records the missing Extra name (Requirement 6). Callers can catch `SkyeError` broadly or `MissingExtraError` specifically.
- **Model transport errors.** The shared transport retries a transient failure up to a configurable maximum of 3 attempts, then maps the failure to a Skye error through the single shared error-mapping module (Requirement 4).
- **DecisionModel errors.** An empty allowed-option set is rejected with a Skye error indicating at least one option is required; no choice is returned (Requirement 4).
- **Import-boundary violations.** The AST import-matrix test reports each violation with the importing Component and Layer and the imported Component and Layer, and exits non-zero (Requirement 2). It additionally reports any direct import among the `agents`, `teams`, and `flows` implementation modules (Requirement 11).
- **Cyclic composition.** When a `teams` or `flows` unit nests a unit within itself directly or transitively, the composing unit detects the cycle (visited-set of unit identities or a configurable depth bound, default max nesting depth 100) and raises a Skye error indicating the cyclic composition without recursing beyond the bound (Requirement 11). This is a runtime behavior covered by the orchestrators' own specs.
- **Codename violations.** The codename test reports the offending Codename and its location when a Codename appears in a package name, file name, or import (Requirement 9).
- **Budget violations.** The budget tests report the offending library for a forbidden import or an unexpected leak, and the specific mismatch for an Extra that declares or omits a library (Requirements 7, 8).

## Testing Strategy

The structure is verified by deterministic tests, all runnable with `uv run pytest`, consistent with the existing `tests/budget` suite.

**Static / deterministic tests:**

- **Import-matrix test** — AST-based, modeled on `tests/budget/test_policy.py`. Parses every `src/skye` module, resolves imports to Components and Layers, and asserts (i) the Layer ceiling (no upward import), (ii) membership in each Component's declared allowed set in the Per-component dependency matrix, and (iii) no direct import among the `agents`, `teams`, and `flows` implementation modules (Requirement 11). Reports importer/imported Component and Layer; exits non-zero on violation (Requirements 2, 11). Covers the three known violations in Requirement 2, catches out-of-set imports such as `gateway` importing `memory` and `teams`/`flows` importing `models` (a composed model must arrive as a `Runnable` reference, Requirement 11), and catches orchestrator cross-imports such as `flows` importing `agents`.
- **Base stdlib-only test** — asserts no `base` module imports a non-stdlib package (pydantic included) or a higher Layer (Requirement 3).
- **Codename test**: asserts the `^[a-z]{3,7}$` pattern, uniqueness, exactly **15** entries, and absence from package/file/import names (Requirement 9).
- **Extras-declare-exactly test** — compares each Extra's declared libraries against the libraries imported by its Component's code (Requirement 8), reusing the `[imports.max_files]` machinery in `budgets.toml`.
- **No-provider-SDK test (Property 10)** — AST-based; asserts that no module in the `models` Component (transport and adapters) imports a provider SDK (`openai`, `anthropic`, `boto3`, `azure`, `cohere`, `google`) or a third-party HTTP client (`httpx`, `requests`); every import resolves to the standard library, a permitted Skye Component, or an honest residual Extra (Requirements 7, 8). This overlaps the `forbidden_at_import` check but asserts it at the source-tree level for `models`.

**Footprint / load tests** (modeled on `tests/budget/test_footprint_budget.py`):

- `import skye` in a clean core-only environment loads no `forbidden_at_import` library and stays within `max_modules_loaded` and `max_import_ms` (Requirement 7).
- `known_leaks` and `known_import_failures` are driven to empty as the `httpx`/`requests` dependency is eliminated at the source by the stdlib `urllib` transport (not merely deferred); the tests fail if a listed entry starts working, keeping the lists from going stale (Requirement 7).

**Property-based testing.** PBT applies to the small set of pure, input-varying behaviors in this structure spec:

- **DecisionModel probabilities (Property 9).** Use a property-based testing library for Python (`hypothesis`) to generate non-empty finite option sets and assert the probability range, the sum-to-one invariant, and choice membership, and to generate the empty set and assert rejection. Minimum 100 iterations per property test; tag format `Feature: structure, Property 9: DecisionModel probabilities are well-formed`.

The structural properties (1–8, 10, 11, 12, and 13) are not generated-input property tests; they are **deterministic invariants over the static source tree, the install, and the configuration**, best enforced by the AST/budget/codename/no-provider-SDK tests above (which already run exhaustively over all modules rather than sampled inputs). Property 11 (no import edge among `agents`/`teams`/`flows`) is checked by condition (iii) of the import-matrix test; Property 12 (`teams`/`flows` import neither `models` nor any orchestrator implementation module) is checked by conditions (ii) and (iii) of the import-matrix test, since a `teams`/`flows` import of `models` is an out-of-set import; Property 13 (an added integration stays within its owning Component) is enforced by the extension-point design plus the import-matrix test, since it quantifies over hypothetical additions rather than a generated input space. This is the right tool because there is no meaningful random input space — the "for all modules" quantifier is satisfied by enumerating every module, not by sampling. Only Property 9 (DecisionModel probabilities) has a meaningful random input space and is the single generated-input property test.

The runtime cycle-detection behavior behind the `Runnable` composition model (visited-set of unit identities or a configurable depth bound, default max nesting depth 100, raising a Skye error on a cyclic composition — Requirement 11) is a runtime invariant of the orchestrators, not a static source-tree check; it is covered by the `agents`, `teams`, and `flows` orchestrator tests in their own specs, not by this structure phase.

**Definition of done:** the import-matrix test, the base stdlib-only test, the codename test, the extras-declare-exactly test, the no-provider-SDK test, and the footprint/load tests all pass, and both `make budget-fast` and `make budget` are green.

## Planned rename Nimbus to Skye (executed last)

Documented now, executed as the final task group (Requirement 19); nothing is renamed before it.

- **Names.** Project **Skye**; import package `skye`; PyPI distribution `skyeai` (`skye` belongs to an unrelated package, `skyai` is taken).
- **Mechanical substitution.** `src/nimbus -> src/skye` and every import; `NimbusMessage`/`NimbusError`/`NimbusConfig` and any other `Nimbus*` name to `Skye*`; the three `NIMBUS_*` environment variables to `SKYE_*`; `nimbus.yaml -> skye.yaml`; the project name in `pyproject.toml` to `skyeai`; and the occurrences in `budgets.toml`, CI, CODEOWNERS, the Makefile, the specs, the steering, the wiki, the examples, and the README. The GitHub repository rename is done by the owner (the platform redirects the old address).
- **Precondition (non-coding first task).** All previous task groups closed; the owner has checked the trademark of "Skye" in software; the owner has reserved `skyeai` (and `skye-ai`) on PyPI.
- **Definition of done.** `make budget-fast`, `make budget`, `make differential`, and the guardrail tests give the same results as before the rename, with the codename test adapted to the new names.
- **Umbrella watermark.** After the rename `nimbus` becomes the project-wide umbrella watermark, documentation-only, outside the 15 Component Codenames and analogous to `vapor`; it never appears in an import path, folder, file, class, function, configuration key, or spec folder name.

## Governance: licence, budget CI gate, budget debts, and the prompts template target

These anchor Requirements 24–27. The first three describe policy already in place; the fourth is a target.

- **Licence and attribution (Requirement 24).** The project is MIT-licensed (`LICENSE` at the root). No third-party code or documentation text is copied without its licence and attribution (a `NOTICE`/`THIRD_PARTY_NOTICES` file plus a comment at the copied code); ideas and public API shapes are exempt. `CONTRIBUTING.md` states these rules, forbids copying from the `enterprise/` directory of LiteLLM (separate commercial licence), and requires prompt templates to be written for Skye or carry their source's licence. Where `prompts` reuses the liteprompt design or anything from prompt-poet (Character.AI, MIT), it carries the prompt-poet MIT notice for those parts.
- **Budget CI gate (Requirement 25).** `.github/workflows/budgets.yml` runs the `tests/budget` suite on every pull request and fails the PR when any `budgets.toml` limit is exceeded. `budgets.toml` is the single source of truth, consumed identically by `make budget-fast`/`make budget` and by CI, so local and CI results agree. A limit is never weakened to make a failing change pass; a limit change is an explicit, reviewed edit to `budgets.toml`.
- **Budget debts empty (Requirement 26).** `known_leaks` and `known_import_failures` in `budgets.toml` are both empty: the `httpx`/`requests` leak was eliminated at the source by the stdlib `urllib` transport, and the former `skye.capabilities` import failure was resolved by the migration. While an entry is tracked the budget tests emit a non-failing warning naming it; if a listed entry starts working again the tests fail, so the lists cannot go stale.
- **Prompts without a compiled template engine (Requirement 27, target).** The target `prompts` Component reuses the liteprompt design (loaders, role-based messages, registry, truncation) without the Jinja2 engine, because Jinja2 pulls a compiled package not guaranteed in the target serverless runtime. This is **not yet executed**: `jinja2` is still a core dependency in `pyproject.toml` and in `allowed_dependencies` of `budgets.toml`. Its removal is tracked by an open task (group 9 in `tasks.md`); when executed, `jinja2` leaves the core dependencies and `allowed_dependencies`, and neither `import skye` nor `prompts` imports a compiled template engine, with the budget tests green.

**Documentation-as-wiki is out of scope here.** Migrating `docs/` from a flat folder to a per-component wiki, and the codename glossary page (including `auth = ozone` and the `nimbus` umbrella watermark), are owned by the `wiki` cross-cutting spec. This `structure` spec keeps only the component↔doc-section name binding (Requirement 1.2).

## Wiki (merged from the former wiki spec)

### Layout

```
docs/
├── index.md        entry point; links every section and the glossary
├── glossary.md     the one codename glossary
├── <component>/    one folder per component, index.md first, codename line under the title
├── budgets.md      reference page (see "Pages without a component")
```

Section folders use the plain component name; the codename appears only in the section front matter and the italic line under the title.
Each page has front matter (title, status, last_updated, related pages) and is linked from its section index.

### Migration of the flat docs

| Old page | Section |
|---|---|
| `routing-guide.md` (and the two empty routing stubs, removed) | `router/` |
| `provider-architecture-validation.md`, `provider-consolidation-summary.md`, `provider-transformation-architecture.md` | `models/` |
| `budgets.md` | `docs/budgets.md` as a reference page, not a component section |

Pages are moved, not rewritten; content edits are a separate task.

### Glossary page

`docs/glossary.md`: 15 rows (codename, plain name, role), then the two documentation-only watermarks (`vapor`, and the project umbrella watermark),
then the `auth` (authentication) versus `policy` (authorization) contrast.

### Docs test

`tests/docs`: every page has front matter, every relative link resolves, every page is reachable from `docs/index.md`. Offline and deterministic.


## Consolidation (history, merged from the former skye-consolidation spec)

## Design Document

### Overview

This design outlines a comprehensive consolidation effort for the Skye library to ensure consistent naming conventions, enhance configuration management with YAML support and environment variable substitution, improve test organization and coverage, and update documentation to reflect the current state of the codebase.

The consolidation addresses several key areas:
1. **Terminology Consistency**: Standardize on "Capability" terminology throughout
2. **Configuration Enhancement**: Add YAML configuration support with environment variable substitution
3. **Test Organization**: Restructure tests into clear categories with improved coverage
4. **Documentation Updates**: Ensure steering documents accurately reflect current architecture
5. **Example Reorganization**: Improve example structure and documentation

### Architecture

#### Current State Analysis

The codebase currently has:
- Mixed terminology in some areas (tool_models.py, tool_call_handler.py, tool_transformer.py)
- Router configuration only via Python code
- Tests scattered across unit/ and integration/ directories
- Examples in a flat structure under examples/
- Steering documents that may not reflect recent changes

#### Target State

The refactored codebase will have:
- Consistent "Capability" terminology throughout
- YAML configuration support for routers with environment variable substitution
- Well-organized test structure: unit/, integration/, stress/
- Categorized examples with clear README files
- Updated steering documents reflecting current architecture

### Components and Interfaces

#### 1. Configuration Loader for YAML

**Purpose**: Load router configurations from YAML files with environment variable substitution.

**Location**: `src/skye/config.py` (enhance existing)

**Key Methods**:
```python
def load_router_config(yaml_path: str) -> dict[str, Any]:
    """Load router configuration from YAML file with env var substitution."""
    
def substitute_env_vars(config: dict[str, Any]) -> dict[str, Any]:
    """Recursively substitute ${VAR_NAME} with environment variables."""
```

**YAML Format**:
```yaml
routes:
  - alias: "gpt-3.5-turbo"
    strategy: "rate_limit_aware"
    targets:
      - model: "azure/chatgpt-v-2"
        provider: "azure"
        api_key: "${AZURE_API_KEY}"
        api_base: "${AZURE_API_BASE}"
        tpm: 100000
        rpm: 1000
      - model: "gpt-3.5-turbo"
        provider: "openai"
        api_key: "${OPENAI_API_KEY}"
        tpm: 200000
        rpm: 2000

fallbacks:
  - primary: "gpt-4"
    fallbacks: ["gpt-3.5-turbo"]

retry_policies:
  - error_type: "RateLimitError"
    max_retries: 3

allowed_fails_policies:
  - error_type: "RateLimitError"
    allowed_fails_per_minute: 100
```

#### 2. ModelRouter Enhancement

**Purpose**: Support loading configuration from YAML files and environment variable substitution in Python config.

**Location**: `src/skye/routes/model_router.py`

**New Methods**:
```python
@classmethod
def from_yaml(cls, yaml_path: str, **kwargs) -> "ModelRouter":
    """Create router from YAML configuration file."""

@classmethod
def from_config_dict(cls, config: dict[str, Any], **kwargs) -> "ModelRouter":
    """Create router from configuration dictionary."""
```

**Enhanced ModelTarget**:
```python
class ModelTarget(BaseModel):
    # ... existing fields ...
    
    def model_post_init(self, __context: Any) -> None:
        """Post-initialization to substitute environment variables."""
        self._substitute_env_vars()
    
    def _substitute_env_vars(self) -> None:
        """Substitute ${VAR_NAME} patterns with environment variables."""
```

#### 3. File Renaming Strategy

**Files to Rename**:
- `tool_models.py` → `capability_models.py`
- `tool_call_handler.py` → `capability_call_handler.py`
- `tool_transformer.py` → `capability_transformer.py`

**Classes to Rename**:
- `ToolCall` → `CapabilityCall`
- `ToolResult` → `CapabilityResult`
- `ToolCallHandler` → `CapabilityCallHandler`
- `ToolTransformer` → `CapabilityTransformer`

**Breaking Change**:
This is a clean break with no backward compatibility. All old names will be removed.

#### 4. Test Organization

**New Structure**:
```
tests/
├── unit/                      # Fast, isolated tests
│   ├── capabilities/          # Capability system tests
│   ├── providers/             # Provider tests
│   ├── routes/                # Router tests
│   └── utils/                 # Utility tests
├── integration/               # Multi-component tests
│   ├── capabilities/          # End-to-end capability tests
│   ├── providers/             # Provider integration tests
│   └── routes/                # Router integration tests
├── stress/                    # Performance and load tests
│   ├── test_concurrent_routing.py
│   ├── test_rate_limiting.py
│   └── test_capability_load.py
└── fixtures/                  # Shared test fixtures
    ├── __init__.py
    ├── mock_responses.py
    ├── sample_configs.py
    └── images/
```

#### 5. Example Reorganization

**New Structure**:
```
examples/
├── README.md                  # Overview of all examples
├── basic/                     # Basic usage examples
│   ├── README.md
│   ├── simple_completion.py
│   └── streaming_example.py
├── capabilities/              # Capability examples
│   ├── README.md
│   ├── local_function.py
│   ├── remote_api.py
│   └── mcp_server.py
├── providers/                 # Provider-specific examples
│   ├── README.md
│   ├── openai_example.py
│   ├── anthropic_example.py
│   ├── bedrock_example.py
│   ├── azure_example.py
│   └── vertex_example.py
├── routing/                   # Router examples
│   ├── README.md
│   ├── basic_routing.py
│   ├── yaml_config.py
│   ├── fallback_chains.py
│   └── rate_limiting.py
└── advanced/                  # Advanced patterns
    ├── README.md
    ├── multimodal.py
    ├── structured_output.py
    └── function_calling.py
```

### Data Models

#### RouterConfig (New)

```python
class RouterConfig(BaseModel):
    """Complete router configuration from YAML."""
    
    routes: list[RouteConfig] = Field(default_factory=list)
    fallbacks: list[FallbackConfig] = Field(default_factory=list)
    retry_policies: list[RetryPolicyConfig] = Field(default_factory=list)
    allowed_fails_policies: list[AllowedFailsPolicyConfig] = Field(default_factory=list)
    strategy: RoutingStrategy = RoutingStrategy.ROUND_ROBIN
    cooldown_seconds: float = 60.0
    enable_pre_call_checks: bool = True
```

#### CapabilityCall (Renamed from ToolCall)

```python
class CapabilityCall(BaseModel):
    """Represents a capability invocation request from an LLM."""
    
    id: str = Field(..., description="Unique identifier")
    name: str = Field(..., description="Capability name")
    arguments: dict[str, Any] = Field(default_factory=dict)
```

#### CapabilityResult (Renamed from ToolResult)

```python
class CapabilityResult(BaseModel):
    """Represents the result of executing a capability."""
    
    capability_call_id: str = Field(..., description="ID of the capability call")
    name: str = Field(..., description="Capability name")
    result: Any = Field(default=None)
    error: str | None = Field(default=None)
```

#### 6. Provider-Specific Transformation Consolidation

**Purpose**: Consolidate all provider-specific transformation logic into provider client classes, making the core library completely provider-agnostic.

**Current Problem**:
- Provider-specific transformations are scattered across multiple modules
- `MessageTransformer` has provider-specific methods (`to_openai_format`, `to_bedrock_format`)
- `CapabilityTransformer` has provider-specific methods
- Core library code needs to know about provider formats
- Adding a new provider requires changes to multiple files

**Target Architecture**:
- Each provider client class handles ALL transformations for that provider
- Core library uses only Skye-native models
- Transformers become thin delegation layers
- Adding a new provider only requires creating a new provider client class

**New Provider Client Interface**:
```python
class BaseModelProvider(ABC):
    """Base class for all model providers with transformation methods."""
    
    @abstractmethod
    def _transform_request(self, request: CompleteRequest) -> dict[str, Any]:
        """Transform Skye request to provider-specific format.
        
        This method handles ALL provider-specific transformations:
        - Message format conversion
        - Capability/tool format conversion
        - Parameter mapping
        - Provider-specific options
        """
        pass
    
    @abstractmethod
    def _transform_response(self, response: Any) -> CompleteResponse:
        """Transform provider response to Skye format.
        
        This method handles ALL provider-specific transformations:
        - Message extraction
        - Tool call extraction and conversion
        - Usage information extraction
        - Metadata extraction
        """
        pass
    
    def _transform_messages(self, messages: list[SkyeMessage]) -> list[dict[str, Any]]:
        """Transform Skye messages to provider-specific format.
        
        Override this method to implement provider-specific message transformation.
        """
        raise NotImplementedError
    
    def _transform_capabilities(self, capabilities: list[CapabilityInterface]) -> list[dict[str, Any]]:
        """Transform Skye capabilities to provider-specific format.
        
        Override this method to implement provider-specific capability transformation.
        """
        raise NotImplementedError
    
    def _extract_tool_calls(self, response: Any) -> list[CapabilityCall] | None:
        """Extract tool calls from provider response.
        
        Override this method to implement provider-specific tool call extraction.
        """
        return None
```

**Refactored MessageTransformer**:
```python
class MessageTransformer:
    """Thin delegation layer for message transformations.
    
    This class no longer contains provider-specific logic.
    It delegates to provider client methods.
    """
    
    @staticmethod
    def transform_for_provider(
        messages: list[SkyeMessage],
        provider: BaseModelProvider
    ) -> list[dict[str, Any]]:
        """Delegate message transformation to provider."""
        return provider._transform_messages(messages)
```

**Refactored CapabilityTransformer**:
```python
class CapabilityTransformer:
    """Thin delegation layer for capability transformations.
    
    This class no longer contains provider-specific logic.
    It delegates to provider client methods.
    """
    
    @staticmethod
    def transform_for_provider(
        capabilities: list[CapabilityInterface],
        provider: BaseModelProvider
    ) -> list[dict[str, Any]]:
        """Delegate capability transformation to provider."""
        return provider._transform_capabilities(capabilities)
```

**Migration Path**:
1. Add transformation methods to BaseModelProvider
2. Move provider-specific logic from transformers to provider clients
3. Update provider clients to implement all transformation methods
4. Update transformers to delegate to provider clients
5. Remove provider-specific methods from transformers
6. Update all call sites to use new delegation pattern

### Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

#### Property 1: Environment Variable Substitution Consistency

*For any* configuration string containing ${VAR_NAME} pattern, when the environment variable exists, substitution should replace the pattern with the variable value, and when it doesn't exist, it should raise a ConfigurationError.

**Validates: Requirements 2.2, 6.1**

#### Property 2: YAML Configuration Round-Trip

*For any* valid RouterConfig, serializing to YAML and then loading back should produce an equivalent configuration (excluding environment variable substitution).

**Validates: Requirements 2.1**

#### Property 3: Terminology Consistency

*For any* public API in the capabilities module, references to tool functionality should use "Capability" terminology, not "Tool" terminology.

**Validates: Requirements 1.1, 1.2**

#### Property 4: Complete Terminology Migration

*For any* public API or internal code, there should be zero references to "Tool" terminology in capability-related code.

**Validates: Requirements 1.5**

#### Property 5: Test Organization

*For any* test file, it should be located in the appropriate directory (unit/, integration/, or stress/) based on its testing scope.

**Validates: Requirements 8.1, 8.2, 8.3**

#### Property 6: Example Completeness

*For any* major feature category (capabilities, routing, providers), there should exist at least one working example demonstrating its usage.

**Validates: Requirements 4.1, 4.2, 4.3, 4.4**

#### Property 7: Configuration Validation

*For any* invalid YAML configuration (missing required fields, invalid types), loading should raise a clear ConfigurationError with specific details about what is invalid.

**Validates: Requirements 2.4**

#### Property 8: Concurrent Request Handling

*For any* router under concurrent load, it should correctly track active requests and rate limits without race conditions.

**Validates: Requirements 7.1**

#### Property 9: Provider Transformation Encapsulation

*For any* provider client class, all provider-specific transformation logic should be contained within that class and not leak into core library code.

**Validates: Requirements 9.1, 9.5**

#### Property 10: Core Library Provider Agnosticism

*For any* core library module (router, capabilities, completion models), it should only reference Skye-native models and never provider-specific formats.

**Validates: Requirements 9.4, 9.6, 9.7, 9.8**

#### Property 11: Transformer Delegation

*For any* transformation operation, the transformer should delegate to the appropriate provider client method rather than implementing provider-specific logic.

**Validates: Requirements 9.2, 9.3**

### Error Handling

#### Configuration Errors

```python
class ConfigurationError(SkyeError):
    """Raised when configuration is invalid."""
    
    def __init__(
        self,
        message: str,
        config_path: str | None = None,
        field_name: str | None = None,
        **kwargs
    ):
        super().__init__(message, {
            "config_path": config_path,
            "field_name": field_name,
            **kwargs
        })
```

**Error Scenarios**:
1. Missing environment variable: "Environment variable '${VAR}' not found"
2. Invalid YAML syntax: "Failed to parse YAML: {error}"
3. Invalid configuration: "Invalid router configuration: {details}"
4. Missing required field: "Required field '{field}' missing in configuration"

#### Deprecation Warnings

```python
import warnings

def _deprecated_alias(old_name: str, new_name: str):
    """Issue deprecation warning for renamed classes."""
    warnings.warn(
        f"{old_name} is deprecated, use {new_name} instead",
        DeprecationWarning,
        stacklevel=2
    )
```

### Testing Strategy

#### Unit Tests

**Coverage Goals**:
- Configuration loading: 90%+
- Environment variable substitution: 95%+
- Router selection logic: 90%+
- Capability models: 85%+

**Key Test Files**:
- `tests/unit/test_config_loader.py`: YAML loading and env var substitution
- `tests/unit/router/test_router_config.py`: Router configuration validation
- `tests/unit/tools/test_capability_models.py`: Renamed model tests
- `tests/unit/tools/test_capability_call_handler.py`: Handler tests

#### Integration Tests

**Scenarios**:
1. End-to-end router configuration from YAML
2. Multi-provider routing with fallbacks
3. Capability execution across different providers
4. Rate limiting with concurrent requests

**Key Test Files**:
- `tests/integration/routes/test_yaml_routing.py`
- `tests/integration/capabilities/test_end_to_end.py`
- `tests/integration/providers/test_multi_provider.py`

#### Stress Tests

**Scenarios**:
1. Concurrent routing (100+ simultaneous requests)
2. Rate limit enforcement under load
3. Failover behavior under high error rates
4. Capability execution with high concurrency

**Key Test Files**:
- `tests/stress/test_concurrent_routing.py`
- `tests/stress/test_rate_limiting.py`
- `tests/stress/test_capability_load.py`

**Metrics to Track**:
- Requests per second
- Average latency
- P95/P99 latency
- Error rate
- Memory usage

#### Property-Based Tests

Use `hypothesis` for property-based testing:

```python
from hypothesis import given, strategies as st

@given(st.text(min_size=1))
def test_env_var_substitution_idempotent(var_name: str):
    """Substituting twice should equal substituting once."""
    # Property test for env var substitution
```

### Migration Guide

#### For Users

**Breaking Changes**: All "Tool" terminology has been removed. You must update your code.

**Step 1**: Update all imports:
```python
## Old (will not work)
from skye.capabilities import ToolCall, ToolResult, ToolCallHandler

## New (required)
from skye.capabilities import CapabilityCall, CapabilityResult, CapabilityCallHandler
```

**Step 2**: Update all variable names and references:
```python
## Old
tool_call = ToolCall(id="1", name="get_weather", arguments={})
tool_result = ToolResult(tool_call_id="1", name="get_weather", result={})

## New
capability_call = CapabilityCall(id="1", name="get_weather", arguments={})
capability_result = CapabilityResult(capability_call_id="1", name="get_weather", result={})
```

**Step 3**: Use YAML configuration (optional but recommended):
```python
## Programmatic (still works)
router = ModelRouter(routes=[...])

## YAML (recommended for complex configs)
router = ModelRouter.from_yaml("router_config.yaml")
```

**Step 4**: Use environment variables in config:
```python
## In YAML
api_key: "${OPENAI_API_KEY}"

## Or in Python
target = ModelTarget(
    model="gpt-4",
    provider="openai",
    api_key="${OPENAI_API_KEY}"  # Will be substituted
)
```

#### For Contributors

**Step 1**: Follow new test organization:
- Unit tests → `tests/unit/`
- Integration tests → `tests/integration/`
- Stress tests → `tests/stress/`

**Step 2**: Use "Capability" terminology exclusively:
- Never use "Tool" in new code
- Update any remaining "Tool" references to "Capability"

**Step 3**: Run full test suite:
```bash
pytest tests/
```

### Implementation Notes

#### Phase 1: Terminology Consolidation
1. Rename files (tool_* → capability_*)
2. Rename classes (Tool* → Capability*)
3. Add backward compatibility aliases
4. Update all internal references
5. Update documentation

#### Phase 2: Configuration Enhancement
1. Implement environment variable substitution
2. Add YAML loading support
3. Create RouterConfig model
4. Add validation and error handling
5. Write comprehensive tests

#### Phase 3: Test Reorganization
1. Create new test directory structure
2. Move existing tests to appropriate locations
3. Add stress tests
4. Improve test fixtures
5. Update test documentation

#### Phase 4: Example Reorganization
1. Create new example directory structure
2. Move and categorize existing examples
3. Add missing examples (YAML config, etc.)
4. Write README files for each category
5. Ensure all examples work

#### Phase 5: Documentation Updates
1. Update steering documents
2. Update architecture diagrams
3. Update API documentation
4. Add migration guide
5. Update README

### Performance Considerations

#### Environment Variable Substitution

- Cache substituted values to avoid repeated os.getenv() calls
- Perform substitution once during initialization, not per-request
- Use compiled regex for pattern matching

#### YAML Loading

- Load and parse YAML once at startup
- Cache parsed configuration
- Validate configuration eagerly to fail fast

#### Test Performance

- Use pytest-xdist for parallel test execution
- Mock external dependencies in unit tests
- Use fixtures to avoid repeated setup
- Profile slow tests and optimize

### Security Considerations

#### Environment Variables

- Never log actual API key values
- Mask sensitive values in error messages
- Support .env files for local development
- Document secure practices for production

#### YAML Configuration

- Validate all inputs from YAML files
- Sanitize file paths to prevent directory traversal
- Limit file size to prevent DoS
- Use safe YAML loading (yaml.safe_load)

### Breaking Changes

#### Removed Names

All "Tool" terminology has been removed and replaced with "Capability":
- `ToolCall` → `CapabilityCall` (no alias)
- `ToolResult` → `CapabilityResult` (no alias)
- `ToolCallHandler` → `CapabilityCallHandler` (no alias)
- `ToolTransformer` → `CapabilityTransformer` (no alias)

#### Migration Required

Users must update their code to use the new names:
```python
## Old (will not work)
from skye.capabilities import ToolCall  # ImportError

## New (required)
from skye.capabilities import CapabilityCall
```

This is a breaking change requiring a major version bump.

### Documentation Updates

#### Steering Documents

Update `.kiro/steering/skye-architecture.md`:
- Reflect current package structure
- Add YAML configuration examples
- Update naming conventions section
- Add environment variable guidelines

#### API Documentation

- Update all docstrings to use "Capability" terminology
- Add examples of YAML configuration
- Document environment variable substitution
- Add migration guide

#### README

- Update quick start examples
- Add YAML configuration example
- Update feature list
- Add link to migration guide

## Base contracts: detailed design (former `skye` spec)

The interfaces, message types, response models, configuration and package structure of `base`, as designed before the structure migration. Class names read with the old project name as written. Where this text and `11-design.md` differ, `11-design.md` wins.

## Design Document: skye

### Overview

The skye library serves as the foundational layer for the Skye GenAI platform. It provides a Clean Architecture-based design where all components are built on a stable core of interfaces and models. The design emphasizes:

- **Provider-agnostic abstractions** for LLM interactions
- **Optional extras architecture** - install only what you need
- **Type safety** using Pydantic models and Python type hints
- **Minimal base dependencies** to remain lightweight and stable
- **Zero coupling** between optional components

#### Installation Philosophy

The base installation (`pip install skyeai`) provides only:
- **Interfaces**: Contracts that define how components interact
- **Models**: Data structures (messages, requests, responses, configs)
- **Exceptions**: Error hierarchy
- **Configuration**: Config loading system

All implementations are optional extras:
```bash
pip install skyeai                    # Base only
pip install skyeai[bedrock]           # + Bedrock provider
pip install skyeai[agents,memory]     # + Multiple extras
pip install skyeai[all]               # Everything
```

#### Usage Example

```python
## Install: pip install skyeai[bedrock]

from skye.completion import CompleteRequest
from skye.messages import UserMessage
from skye.providers.bedrock import BedrockModel

model = BedrockModel(model_id="anthropic.claude-3-sonnet")
response = model.complete(
    CompleteRequest(
        messages=[UserMessage(content="Hello")],
        model="claude-3-sonnet"
    )
)
```

### Architecture

#### High-Level Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    skye (base)                        │
│  ┌───────────────────────────────────────────────────┐  │
│  │           Core Interfaces & Contracts             │  │
│  │  - ModelInterface                                 │  │
│  │  - PromptBuilderInterface                         │  │
│  │  - CapabilityInterface                            │  │
│  │  - MemoryInterface                                │  │
│  │  - SafetyFilterInterface                          │  │
│  │  - ObserverInterface                              │  │
│  │  - PluginInterface                                │  │
│  │  - EventHandlerInterface                          │  │
│  │  - VectorEncoderInterface                         │  │
│  │  - ContentReaderInterface                         │  │
│  │  - ModelRouterInterface                           │  │
│  └───────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────┐  │
│  │           Data Models (Pydantic)                  │  │
│  │  - SkyeMessage, UserMessage, AssistantMessage   │  │
│  │  - SystemMessage, CapabilityMessage               │  │
│  │  - ContentChunk                                   │  │
│  │  - CompleteRequest                              │  │
│  │  - CompleteResponse                             │  │
│  │  - StreamChunk                                    │  │
│  │  - TokenUsage                                     │  │
│  │  - ModelConfig, RateLimitConfig, RetryConfig    │  │
│  │  - CooldownConfig, RoutingStrategy              │  │
│  └───────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────┐  │
│  │           Exception Hierarchy                     │  │
│  │  - SkyeError (base)                             │  │
│  │  - ProviderError                                  │  │
│  │  - ConfigurationError                             │  │
│  │  - ValidationError                                │  │
│  └───────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────┐  │
│  │           Configuration System                    │  │
│  │  - ConfigLoader                                   │  │
│  │  - EnvironmentConfig                              │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                          │
                          │ (depends on)
                          ▼
        ┌─────────────────────────────────────┐
        │   Optional Extras (same package)    │
        │  - skyeai[bedrock]                  │
        │  - skyeai[openai]                   │
        │  - skyeai[agents]                   │
        │  - skyeai[prompts]                  │
        │  - skyeai[tools]                    │
        │  - skyeai[memory]                   │
        │  - skyeai[guard]                    │
        │  - skyeai[observe]                  │
        └─────────────────────────────────────┘
```

#### Dependency Flow

All optional extras depend on the base skye package. The base package has no dependencies on any extras, creating a stable foundation.

```
skye (base: interfaces + models)
    ↑
    │ optional extras
    │
    ├── skyeai[bedrock] (AWS Bedrock provider)
    ├── skyeai[openai] (OpenAI provider)
    ├── skyeai[anthropic] (Anthropic provider)
    ├── skyeai[agents] (Agent runtime)
    ├── skyeai[prompts] (Prompt management)
    ├── skyeai[tools] (Capabilities/tools)
    ├── skyeai[memory] (Persistent memory)
    ├── skyeai[guard] (Safety filters)
    └── skyeai[observe] (Observability)
```

### Components and Interfaces

#### 1. Message Types

Different message types for structured conversation handling.

**Purpose**: Provide type-safe message representations for different roles and contexts.

**Message Type Definitions**:
```python
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List, Literal
from datetime import datetime

class SkyeMessage(BaseModel):
    """Base class for all message types."""
    content: str
    role: Literal["user", "assistant", "system", "capability"]
    metadata: Dict[str, Any] = Field(default_factory=dict)
    id: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    @property
    def message_type(self) -> str:
        """Return the message type."""
        return self.role
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert message to dictionary format."""
        return {
            "role": self.role,
            "content": self.content,
            "metadata": self.metadata,
            "id": self.id,
            "timestamp": self.timestamp.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SkyeMessage":
        """Create message from dictionary format."""
        role = data.get("role")
        if role == "user":
            return UserMessage(**data)
        elif role == "assistant":
            return AssistantMessage(**data)
        elif role == "system":
            return SystemMessage(**data)
        elif role == "capability":
            return CapabilityMessage(**data)
        else:
            return cls(**data)
    
    def format_for_provider(self, provider: str) -> Dict[str, Any]:
        """Format message for specific provider (OpenAI, Anthropic, etc.)."""
        # Base implementation - can be overridden by subclasses
        return {"role": self.role, "content": self.content}

class UserMessage(SkyeMessage):
    """Message from a user."""
    role: Literal["user"] = "user"

class AssistantMessage(SkyeMessage):
    """Message from an AI assistant."""
    role: Literal["assistant"] = "assistant"
    capability_calls: List[Dict[str, Any]] = Field(default_factory=list)
    
    def format_for_provider(self, provider: str) -> Dict[str, Any]:
        """Format assistant message with capability calls for provider."""
        base = super().format_for_provider(provider)
        if self.capability_calls:
            if provider == "openai":
                base["tool_calls"] = self.capability_calls
            elif provider == "anthropic":
                base["tool_use"] = self.capability_calls
        return base

class SystemMessage(SkyeMessage):
    """System-level instruction message."""
    role: Literal["system"] = "system"

class CapabilityMessage(SkyeMessage):
    """Message containing capability execution results."""
    role: Literal["capability"] = "capability"
    capability_id: str
    capability_name: str
    
    def format_for_provider(self, provider: str) -> Dict[str, Any]:
        """Format capability message for provider."""
        base = {"role": "tool" if provider == "openai" else "user", "content": self.content}
        if provider == "openai":
            base["tool_call_id"] = self.capability_id
            base["name"] = self.capability_name
        return base
```

#### 2. ModelInterface

The core abstraction for LLM provider interactions.

**Purpose**: Define a contract for invoking language models regardless of the underlying provider.

**Interface Definition**:
```python
from abc import ABC, abstractmethod
from typing import Iterator, Optional
from skye.models import CompleteRequest, CompleteResponse, StreamChunk

class ModelInterface(ABC):
    """Abstract interface for LLM providers."""
    
    @abstractmethod
    def complete(self, request: CompleteRequest) -> CompleteResponse:
        """Execute a synchronous completion request."""
        pass
    
    @abstractmethod
    def stream(self, request: CompleteRequest) -> Iterator[StreamChunk]:
        """Execute a streaming completion request."""
        pass
    
    @abstractmethod
    async def acomplete(self, request: CompleteRequest) -> CompleteResponse:
        """Execute an asynchronous completion request."""
        pass
    
    @abstractmethod
    async def astream(self, request: CompleteRequest) -> Iterator[StreamChunk]:
        """Execute an asynchronous streaming completion request."""
        pass
    
    @abstractmethod
    def get_model_info(self) -> dict:
        """Return metadata about the model (name, provider, capabilities)."""
        pass
```

**Key Design Decisions**:
- Supports both sync and async operations
- Streaming is a first-class citizen
- Request/response use Pydantic models for validation
- Provider-specific details are abstracted away

#### 2. PromptBuilderInterface

Abstraction for prompt template management and rendering.

**Purpose**: Enable reusable, parameterized prompts with version control.

**Interface Definition**:
```python
from abc import ABC, abstractmethod
from typing import Dict, Any, List
from skye.models import Message

class PromptBuilderInterface(ABC):
    """Abstract interface for prompt template management."""
    
    @abstractmethod
    def render(self, template_name: str, variables: Dict[str, Any]) -> List[Message]:
        """Render a template with provided variables into messages."""
        pass
    
    @abstractmethod
    def register_template(self, name: str, template: str, version: str = "1.0") -> None:
        """Register a new prompt template."""
        pass
    
    @abstractmethod
    def get_template(self, name: str, version: Optional[str] = None) -> str:
        """Retrieve a template by name and optional version."""
        pass
```

#### 3. CapabilityInterface

Abstraction for tools/functions that agents can invoke.

**Purpose**: Define executable capabilities that extend agent functionality.

**Interface Definition**:
```python
from abc import ABC, abstractmethod
from typing import Dict, Any
from pydantic import BaseModel

class CapabilitySchema(BaseModel):
    """Schema defining a capability's signature."""
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema format
    returns: Dict[str, Any]

class CapabilityInterface(ABC):
    """Abstract interface for agent capabilities (tools)."""
    
    @abstractmethod
    def get_schema(self) -> CapabilitySchema:
        """Return the capability's schema for LLM function calling."""
        pass
    
    @abstractmethod
    def execute(self, **kwargs) -> Any:
        """Execute the capability with provided arguments."""
        pass
    
    @abstractmethod
    async def aexecute(self, **kwargs) -> Any:
        """Execute the capability asynchronously."""
        pass
```

#### 4. MemoryInterface

Abstraction for persistent memory storage and retrieval.

**Purpose**: Enable agents to store and recall information across sessions.

**Interface Definition**:
```python
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from skye.models import MemoryEntry

class MemoryInterface(ABC):
    """Abstract interface for memory storage."""
    
    @abstractmethod
    def store(self, entry: MemoryEntry) -> str:
        """Store a memory entry and return its ID."""
        pass
    
    @abstractmethod
    def retrieve(self, query: str, limit: int = 10, filters: Optional[Dict] = None) -> List[MemoryEntry]:
        """Retrieve relevant memories based on query."""
        pass
    
    @abstractmethod
    def get_by_id(self, entry_id: str) -> Optional[MemoryEntry]:
        """Retrieve a specific memory by ID."""
        pass
    
    @abstractmethod
    def delete(self, entry_id: str) -> bool:
        """Delete a memory entry."""
        pass
```

#### 5. SafetyFilterInterface

Abstraction for input/output validation and moderation.

**Purpose**: Provide guardrails for safe AI interactions.

**Interface Definition**:
```python
from abc import ABC, abstractmethod
from typing import List
from skye.models import Message, SafetyResult

class SafetyFilterInterface(ABC):
    """Abstract interface for safety filters and guardrails."""
    
    @abstractmethod
    def validate_input(self, messages: List[Message]) -> SafetyResult:
        """Validate input messages before sending to model."""
        pass
    
    @abstractmethod
    def validate_output(self, response: str) -> SafetyResult:
        """Validate model output before returning to user."""
        pass
    
    @abstractmethod
    def get_policies(self) -> List[str]:
        """Return list of active safety policies."""
        pass
```

#### 6. ObserverInterface

Abstraction for telemetry, logging, and monitoring.

**Purpose**: Enable observability without coupling to specific monitoring tools.

**Interface Definition**:
```python
from abc import ABC, abstractmethod
from typing import Dict, Any
from enum import Enum

class EventType(Enum):
    MODEL_CALL = "model_call"
    CAPABILITY_EXECUTION = "capability_execution"
    MEMORY_ACCESS = "memory_access"
    ERROR = "error"

class ObserverInterface(ABC):
    """Abstract interface for observability."""
    
    @abstractmethod
    def log_event(self, event_type: EventType, data: Dict[str, Any], correlation_id: str) -> None:
        """Log an event with structured data."""
        pass
    
    @abstractmethod
    def record_metric(self, metric_name: str, value: float, tags: Dict[str, str]) -> None:
        """Record a metric value."""
        pass
    
    @abstractmethod
    def start_trace(self, operation_name: str) -> str:
        """Start a distributed trace and return trace ID."""
        pass
    
    @abstractmethod
    def end_trace(self, trace_id: str, status: str) -> None:
        """End a distributed trace."""
        pass
```

#### 7. StorageAdapterInterface (removed in D41: nothing implemented or used it)

Abstraction for data persistence backends.

**Purpose**: Decouple storage implementation from business logic.

**Interface Definition**:
```python
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

class StorageAdapterInterface(ABC):
    """Abstract interface for storage backends."""
    
    @abstractmethod
    def save(self, collection: str, data: Dict[str, Any]) -> str:
        """Save data to a collection and return ID."""
        pass
    
    @abstractmethod
    def query(self, collection: str, filters: Dict[str, Any], limit: int = 10) -> List[Dict[str, Any]]:
        """Query data from a collection."""
        pass
    
    @abstractmethod
    def vector_search(self, collection: str, embedding: List[float], limit: int = 10) -> List[Dict[str, Any]]:
        """Perform vector similarity search."""
        pass
    
    @abstractmethod
    def delete(self, collection: str, item_id: str) -> bool:
        """Delete an item from a collection."""
        pass
```

#### 8. PluginInterface

Abstraction for plugin lifecycle management.

**Purpose**: Enable dynamic plugin registration and initialization.

**Interface Definition**:
```python
from abc import ABC, abstractmethod
from typing import Dict, Any

class PluginInterface(ABC):
    """Abstract interface for Skye plugins."""
    
    @abstractmethod
    def initialize(self, config: Dict[str, Any]) -> None:
        """Initialize the plugin with configuration."""
        pass
    
    @abstractmethod
    def shutdown(self) -> None:
        """Clean up resources before shutdown."""
        pass
    
    @abstractmethod
    def get_metadata(self) -> Dict[str, Any]:
        """Return plugin metadata (name, version, dependencies)."""
        pass
```

#### 9. EventHandlerInterface

Abstraction for event handling during execution.

**Purpose**: Enable hooking into various lifecycle events for logging, monitoring, or custom logic.

**Interface Definition**:
```python
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from skye.models import SkyeMessage, CompleteResponse

class EventHandlerInterface(ABC):
    """Abstract interface for execution event handlers."""
    
    @abstractmethod
    def on_model_invoke_start(self, messages: List[SkyeMessage], **kwargs) -> None:
        """Called when model invocation starts."""
        pass
    
    @abstractmethod
    def on_model_invoke_end(self, response: CompleteResponse, **kwargs) -> None:
        """Called when model invocation completes."""
        pass
    
    @abstractmethod
    def on_model_invoke_error(self, error: Exception, **kwargs) -> None:
        """Called when model invocation fails."""
        pass
    
    @abstractmethod
    def on_capability_invoke_start(self, capability_name: str, inputs: Dict[str, Any], **kwargs) -> None:
        """Called when a capability invocation starts."""
        pass
    
    @abstractmethod
    def on_capability_invoke_end(self, capability_name: str, output: Any, **kwargs) -> None:
        """Called when a capability invocation completes."""
        pass
    
    @abstractmethod
    def on_capability_invoke_error(self, capability_name: str, error: Exception, **kwargs) -> None:
        """Called when a capability invocation fails."""
        pass
    
    @abstractmethod
    def on_execution_step(self, step_name: str, step_data: Dict[str, Any], **kwargs) -> None:
        """Called on each execution step."""
        pass
    
    @abstractmethod
    def on_execution_complete(self, result: Any, **kwargs) -> None:
        """Called when execution completes."""
        pass
```

#### 10. VectorEncoderInterface

Abstraction for text-to-vector encoding models.

**Purpose**: Provide a unified interface for generating vector representations from text.

**Interface Definition**:
```python
from abc import ABC, abstractmethod
from typing import List

class VectorEncoderInterface(ABC):
    """Abstract interface for vector encoding models."""
    
    @abstractmethod
    def encode(self, text: str) -> List[float]:
        """Encode a single text into a vector."""
        pass
    
    @abstractmethod
    def encode_batch(self, texts: List[str]) -> List[List[float]]:
        """Encode multiple texts into vectors."""
        pass
    
    @abstractmethod
    async def aencode(self, text: str) -> List[float]:
        """Encode a single text into a vector asynchronously."""
        pass
    
    @abstractmethod
    async def aencode_batch(self, texts: List[str]) -> List[List[float]]:
        """Encode multiple texts into vectors asynchronously."""
        pass
    
    @abstractmethod
    def get_vector_dimension(self) -> int:
        """Return the dimension of the output vectors."""
        pass
```

#### 11. ContentReaderInterface

Abstraction for reading content from various sources.

**Purpose**: Standardize content ingestion from different file formats and sources.

**Interface Definition**:
```python
from abc import ABC, abstractmethod
from typing import List, Iterator, Optional, Dict, Any
from skye.models import ContentChunk

class ContentReaderInterface(ABC):
    """Abstract interface for content readers."""
    
    @abstractmethod
    def read(self) -> List[ContentChunk]:
        """Read all content from the source."""
        pass
    
    @abstractmethod
    def read_stream(self) -> Iterator[ContentChunk]:
        """Stream content chunks one at a time."""
        pass
    
    @abstractmethod
    async def aread(self) -> List[ContentChunk]:
        """Read all content asynchronously."""
        pass
    
    @abstractmethod
    def get_reader_metadata(self) -> Dict[str, Any]:
        """Return metadata about the reader (supported formats, source type)."""
        pass
```

#### 12. ModelRouterInterface

Abstraction for intelligent model routing and load balancing.

**Purpose**: Enable advanced routing strategies including load balancing, fallbacks, rate limiting, and cost optimization.

**Interface Definition**:
```python
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from enum import Enum
from skye.models import CompleteRequest, CompleteResponse, ModelConfig

class RoutingStrategy(Enum):
    """Available routing strategies."""
    ROUND_ROBIN = "round_robin"
    LEAST_BUSY = "least_busy"
    LOWEST_LATENCY = "lowest_latency"
    LOWEST_COST = "lowest_cost"
    RATE_LIMIT_AWARE = "rate_limit_aware"
    WEIGHTED = "weighted"

class ModelRouterInterface(ABC):
    """Abstract interface for model routing and load balancing."""
    
    @abstractmethod
    def register_model(self, config: ModelConfig) -> None:
        """Register a model configuration for routing."""
        pass
    
    @abstractmethod
    def select_model(self, request: CompleteRequest) -> ModelConfig:
        """Select the best model configuration based on routing strategy."""
        pass
    
    @abstractmethod
    def route_request(self, request: CompleteRequest) -> CompleteResponse:
        """Route request to selected model with fallback support."""
        pass
    
    @abstractmethod
    async def aroute_request(self, request: CompleteRequest) -> CompleteResponse:
        """Route request asynchronously with fallback support."""
        pass
    
    @abstractmethod
    def mark_model_failed(self, model_id: str, error: Exception) -> None:
        """Mark a model as failed for cooldown tracking."""
        pass
    
    @abstractmethod
    def get_model_health(self, model_id: str) -> Dict[str, Any]:
        """Get health metrics for a model (success rate, latency, etc.)."""
        pass
    
    @abstractmethod
    def set_routing_strategy(self, strategy: RoutingStrategy) -> None:
        """Set the routing strategy."""
        pass
```



### Data Models

#### Core Pydantic Models

All data structures use Pydantic for validation and serialization.

**ContentChunk Model**:
```python
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional

class ContentChunk(BaseModel):
    """Represents a chunk of content with metadata."""
    text: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    chunk_id: Optional[str] = None
    source: Optional[str] = None
    
    def __str__(self) -> str:
        return self.text
```

**Message Models** (see Message Types section above for SkyeMessage, UserMessage, AssistantMessage, SystemMessage, CapabilityMessage)

**CompleteRequest Model**:
```python
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Type

class CompleteRequest(BaseModel):
    """Request for model completion."""
    messages: List[SkyeMessage]
    model: str
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=None, gt=0)
    top_p: Optional[float] = Field(default=1.0, ge=0.0, le=1.0)
    stop: Optional[List[str]] = None
    stream: bool = False
    capabilities: Optional[List[Dict[str, Any]]] = None
    capability_choice: Optional[str] = None
    response_format: Optional[Dict[str, Any]] = None  # For structured outputs
    response_schema: Optional[Type[BaseModel]] = None  # Pydantic model for structured outputs
    metadata: Dict[str, Any] = Field(default_factory=dict)
```

**TokenUsage Model**:
```python
from pydantic import BaseModel

class TokenUsage(BaseModel):
    """Token usage statistics."""
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
```

**CompleteResponse Model**:
```python
from pydantic import BaseModel
from typing import Optional, Dict, Any, Union
from datetime import datetime

class CompleteResponse(BaseModel):
    """Response from model completion."""
    id: str
    model: str
    provider: str
    content: str
    structured_output: Optional[BaseModel] = None  # Parsed structured output if requested
    role: str = "assistant"
    finish_reason: str
    usage: TokenUsage
    created_at: datetime
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    def get_output(self) -> Union[str, BaseModel]:
        """Get the output - structured if available, otherwise text content."""
        return self.structured_output if self.structured_output else self.content
```

**StreamChunk Model**:
```python
from pydantic import BaseModel
from typing import Optional

class StreamChunk(BaseModel):
    """A chunk from a streaming response."""
    id: str
    delta: str
    finish_reason: Optional[str] = None
    index: int = 0
```

**MemoryEntry Model**:
```python
from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime

class MemoryEntry(BaseModel):
    """A single memory entry."""
    id: Optional[str] = None
    content: str
    memory_type: str  # episodic, semantic, persona
    embedding: Optional[List[float]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

**SafetyResult Model**:
```python
from pydantic import BaseModel
from typing import List, Optional

class SafetyResult(BaseModel):
    """Result of safety validation."""
    is_safe: bool
    violations: List[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    filtered_content: Optional[str] = None
```

### Structured Output Support

#### Overview

Skye-core provides built-in support for structured outputs, allowing models to return typed, validated data structures instead of raw text.

#### Usage Pattern

```python
from pydantic import BaseModel
from skye.models import CompleteRequest, UserMessage

class PersonInfo(BaseModel):
    name: str
    age: int
    occupation: str

request = CompleteRequest(
    messages=[UserMessage(content="Extract person info: John is 30 and works as an engineer")],
    model="gpt-4",
    response_schema=PersonInfo
)

response = model.complete(request)
person = response.structured_output  # Returns PersonInfo instance
```

#### Implementation Strategy

1. **Schema Generation**: Convert Pydantic models to JSON Schema
2. **Provider Adaptation**: Transform schema to provider-specific format (OpenAI's `response_format`, Anthropic's tool use pattern)
3. **Response Parsing**: Parse model output and validate against schema
4. **Error Handling**: Provide clear errors if output doesn't match schema

#### Provider-Specific Handling

Different providers handle structured outputs differently:

- **OpenAI**: Native `response_format` with JSON schema
- **Anthropic**: Use tool calling pattern with single tool
- **Others**: Prompt engineering + post-processing validation

The ModelInterface implementations handle these differences transparently.

### Error Handling

#### Exception Hierarchy

```python
class SkyeError(Exception):
    """Base exception for all Skye errors."""
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)

class ProviderError(SkyeError):
    """Error from an LLM provider."""
    def __init__(self, message: str, provider: str, status_code: Optional[int] = None, **kwargs):
        super().__init__(message, {"provider": provider, "status_code": status_code, **kwargs})

class ConfigurationError(SkyeError):
    """Error in configuration."""
    pass

class ValidationError(SkyeError):
    """Error in data validation."""
    def __init__(self, message: str, field: str, value: Any):
        super().__init__(message, {"field": field, "value": value})

class CapabilityExecutionError(SkyeError):
    """Error during capability execution."""
    def __init__(self, message: str, capability_name: str, **kwargs):
        super().__init__(message, {"capability": capability_name, **kwargs})
```

#### Error Handling Strategy

1. **Wrap provider-specific errors** in ProviderError with context
2. **Log all errors** with appropriate severity
3. **Include correlation IDs** for tracing
4. **Preserve stack traces** for debugging
5. **Return structured error responses** to callers

### Configuration Management

#### Configuration Sources (Priority Order)

1. **Code** - Explicit parameters passed to constructors
2. **Environment Variables** - SKYE_* prefixed variables
3. **Configuration Files** - YAML/JSON files

#### Configuration Schema

```python
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List

class RateLimitConfig(BaseModel):
    """Rate limit configuration for a model."""
    requests_per_minute: Optional[int] = None
    tokens_per_minute: Optional[int] = None
    requests_per_day: Optional[int] = None
    tokens_per_day: Optional[int] = None

class RetryConfig(BaseModel):
    """Retry configuration for a model."""
    max_retries: int = 3
    retry_after_seconds: int = 5
    exponential_backoff: bool = True
    retry_on_errors: List[str] = Field(default_factory=lambda: ["rate_limit", "timeout", "server_error"])

class CooldownConfig(BaseModel):
    """Cooldown configuration for failed models."""
    enabled: bool = True
    allowed_fails_per_minute: int = 3
    cooldown_duration_seconds: int = 60

class ModelConfig(BaseModel):
    """Configuration for a model."""
    model_id: str
    provider: str
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    timeout: int = 60
    
    # Advanced routing features
    rate_limits: Optional[RateLimitConfig] = None
    retry_config: RetryConfig = Field(default_factory=RetryConfig)
    cooldown_config: CooldownConfig = Field(default_factory=CooldownConfig)
    fallback_models: List[str] = Field(default_factory=list)
    
    # Load balancing
    weight: float = 1.0  # For weighted routing
    priority: int = 0  # Higher priority models are preferred
    tags: List[str] = Field(default_factory=list)  # For tag-based routing
    
    # Cost tracking
    cost_per_1k_prompt_tokens: Optional[float] = None
    cost_per_1k_completion_tokens: Optional[float] = None

class SkyeConfig(BaseModel):
    """Global Skye configuration."""
    log_level: str = "INFO"
    enable_telemetry: bool = True
    correlation_id_header: str = "X-Correlation-ID"
    models: Dict[str, ModelConfig] = Field(default_factory=dict)
    plugins: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    
    # Router configuration
    default_routing_strategy: str = "round_robin"
    enable_fallbacks: bool = True
    enable_rate_limiting: bool = True
```

#### ConfigLoader Implementation

```python
import os
import yaml
import json
from pathlib import Path
from typing import Optional

class ConfigLoader:
    """Loads configuration from multiple sources."""
    
    @staticmethod
    def load(config_path: Optional[Path] = None, overrides: Optional[Dict] = None) -> SkyeConfig:
        """Load configuration with precedence: overrides > env > file."""
        config_data = {}
        
        # 1. Load from file
        if config_path and config_path.exists():
            with open(config_path) as f:
                if config_path.suffix == '.yaml' or config_path.suffix == '.yml':
                    config_data = yaml.safe_load(f)
                elif config_path.suffix == '.json':
                    config_data = json.load(f)
        
        # 2. Override with environment variables
        for key, value in os.environ.items():
            if key.startswith('SKYE_'):
                config_key = key[7:].lower()  # Remove SKYE_ prefix
                config_data[config_key] = value
        
        # 3. Apply code overrides
        if overrides:
            config_data.update(overrides)
        
        return SkyeConfig(**config_data)
```

### Testing Strategy

#### Unit Testing

- **Interface Compliance Tests**: Verify that implementations satisfy interface contracts
- **Pydantic Model Tests**: Validate data model validation rules
- **Configuration Tests**: Test configuration loading from different sources
- **Exception Tests**: Verify exception hierarchy and error handling

#### Integration Testing

- **Mock Provider Tests**: Test ModelInterface with mock providers
- **Plugin Registration Tests**: Test dynamic plugin loading
- **Configuration Integration**: Test multi-source configuration merging

#### Test Structure

```
tests/
├── unit/
│   ├── test_interfaces.py
│   ├── test_models.py
│   ├── test_exceptions.py
│   └── test_config.py
├── integration/
│   ├── test_plugin_system.py
│   └── test_config_loading.py
└── fixtures/
    ├── sample_config.yaml
    └── mock_providers.py
```

### Package Structure

```
skye/
├── pyproject.toml
├── README.md
├── LICENSE
├── src/
│   └── skye/
│       ├── __init__.py              # Core exports
│       ├── completion.py            # CompleteRequest, CompleteResponse, etc.
│       ├── messages.py              # UserMessage, AssistantMessage, etc.
│       ├── memory.py                # MemoryEntry, etc.
│       ├── exceptions.py            # SkyeError hierarchy
│       ├── config.py                # ModelConfig, SkyeConfig, ConfigLoader
│       ├── interfaces/              # All interface definitions (always included)
│       │   ├── __init__.py
│       │   ├── model.py
│       │   ├── prompt.py
│       │   ├── capability.py
│       │   ├── memory.py
│       │   ├── safety.py
│       │   ├── observer.py
│       │   ├── storage.py
│       │   ├── plugin.py
│       │   ├── event_handler.py
│       │   ├── vector_encoder.py
│       │   ├── content_reader.py
│       │   └── router.py
│       ├── providers/               # Optional: [bedrock], [openai], [anthropic]
│       │   ├── __init__.py
│       │   ├── bedrock.py
│       │   ├── openai.py
│       │   └── anthropic.py
│       ├── agents/                  # Optional: [agents]
│       │   ├── __init__.py
│       │   └── runtime.py
│       ├── prompts/                 # Optional: [prompts]
│       │   ├── __init__.py
│       │   └── builder.py
│       ├── tools/                   # Optional: [tools]
│       │   ├── __init__.py
│       │   └── registry.py
│       ├── memory/                  # Optional: [memory] (implementations)
│       │   ├── __init__.py
│       │   ├── episodic.py
│       │   └── semantic.py
│       ├── guard/                   # Optional: [guard]
│       │   ├── __init__.py
│       │   └── filters.py
│       ├── observe/                 # Optional: [observe]
│       │   ├── __init__.py
│       │   └── telemetry.py
│       └── utils/
│           ├── __init__.py
│           └── validation.py
└── tests/
    ├── unit/
    └── integration/
```

### Dependencies

#### Base Dependencies (Always Installed)

```toml
[project]
requires-python = ">=3.10"
dependencies = [
    "pydantic>=2.0",
    "pyyaml>=6.0",
]
```

#### Optional Dependencies (Extras)

```toml
[project.optional-dependencies]
## Individual providers
bedrock = ["boto3>=1.28"]
openai = ["openai>=1.0"]
anthropic = ["anthropic>=0.25"]
azure = ["azure-ai-inference>=1.0.0b1"]

## Individual components
agents = []
prompts = []
tools = []
memory = ["redis>=5.0", "psycopg2-binary>=2.9"]
guard = []
observe = ["opentelemetry-api>=1.20", "prometheus-client>=0.19"]

## Convenience bundles
providers = ["boto3>=1.28", "openai>=1.0", "anthropic>=0.25", "azure-ai-inference>=1.0.0b1"]
all = ["boto3>=1.28", "openai>=1.0", "anthropic>=0.25", "azure-ai-inference>=1.0.0b1", "redis>=5.0", "psycopg2-binary>=2.9", "opentelemetry-api>=1.20", "prometheus-client>=0.19"]
```

#### Development Dependencies

```toml
[dependency-groups]
dev = [
    "pytest>=7.0",
    "pytest-asyncio>=0.21",
    "pytest-cov>=4.0",
    "black>=23.0",
    "ruff>=0.1",
    "mypy>=1.0",
]
```

### Design Principles

1. **Dependency Inversion**: All components depend on abstractions, not concretions
2. **Interface Segregation**: Interfaces are focused and minimal
3. **Single Responsibility**: Each interface has one clear purpose
4. **Open/Closed**: Open for extension (plugins), closed for modification (core interfaces)
5. **Liskov Substitution**: Any implementation of an interface can be substituted
6. **Type Safety**: Strong typing with Pydantic and type hints
7. **Fail Fast**: Validate early with clear error messages
8. **Zero Coupling**: No dependencies between optional components

### Future Considerations

- **Versioning Strategy**: Semantic versioning with interface stability guarantees
- **Backward Compatibility**: Deprecation policy for interface changes
- **Performance**: Benchmarking framework for interface implementations
- **Documentation**: Auto-generated API docs from type hints and docstrings
- **Plugin Discovery**: Automatic plugin discovery via entry points

