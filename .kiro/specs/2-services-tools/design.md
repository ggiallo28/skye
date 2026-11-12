Builds on: #[[file:.kiro/steering/11-design.md]] (sections: Extension points, MCP client, Ports, Public API and lazy imports, Extras and budgets)

# Design Document: tools

## Overview

`tools` is the services layer-2 component (codename updraft). It holds Skye's capabilities — local functions, remote
APIs and the MCP client — behind the interfaces in `base`. A capability is defined once and used with any provider; the
MCP client consumes an MCP server's tools, prompts and resources and converts them to Skye types at one boundary. There is
a built-in standard-library MCP client by default and `fastmcp` only by explicit choice (Requirement 10.2, 10.3; D15, D16).
`tools` carries no third-party library on the core path; `fastmcp` lives behind the separate `mcp` extra (Requirement 10.7,
7.3). This document describes only the internals of `tools`; the layer, the allowed imports, the Ports, the extension-point
policy and the extras policy are in the steering sections named above and are not restated here.

Ports used by this component: the `capability` Port (capability registration, validation and execution) and the `registry`
Port, both in `base` (Requirement 16.1); the resource Port in `base` that the MCP client implements (Requirement 10.5, D26);
and the `observer` Port for emitting capability-call events (Requirement 18.3). `tools` never imports `prompts`: the MCP
prompt facet returns `base` messages (Requirement 2.3, D17).

## Architecture

`tools` sits in layer 2 (services) and may import only `base` (design "Layers"/"Allowed imports", enforced by the import
matrix). The shape is: one capability interface and schema contract; a thread-safe registry mapping names to capabilities;
three capability kinds (local function, remote API, MCP tool) behind the same interface; a decorator that turns a plain
function into a capability; a call handler that parses, validates and executes provider capability calls; and a tri-faceted
MCP client (tools, prompts, resources) with a built-in and a `fastmcp` implementation behind one Port, converting protocol
shapes at a single boundary module.

## Package layout

```
tools/
  interface.py              CapabilityInterface (get_schema, execute, aexecute)
  schema.py                 CapabilitySchema (name, description, parameters, returns)
  registry.py               CapabilityRegistry (register, get, list, namespaces, search, execute)
  local_function.py         LocalFunctionCapability (signature + docstring -> schema)
  remote_api.py             RemoteAPICapability (HTTP capability over base/http.py)
  decorator.py              @capability (wraps a function as a LocalFunctionCapability)
  capability_models.py      CapabilityResult (and re-exported CapabilityCall from base)
  capability_call_handler.py  CapabilityCallHandler (parse/validate/execute/format)
  exceptions.py             CapabilityError hierarchy (on top of SkyeError)
  mcp_client.py             MCPClientInterface, SkyeMCPClient, MCPToolCapability, create_mcp_client
  mcp_fastmcp.py            FastMCPClient (the only module importing fastmcp, lazily)
  mcp_boundary.py           the single protocol -> Skye conversion point (stdlib only)
  mcp_resource.py           re-exports Resource and ResourceProviderInterface from the base resource Port (D26), keeping the old path
```

## Components and Interfaces

### Capability interface and schema

`interface.py` defines `CapabilityInterface`, the abstract capability contract: `get_schema()` returns a
`CapabilitySchema`, and `execute`/`aexecute` run the capability synchronously and asynchronously (Requirement 16.1, 16.2).
`schema.py` defines `CapabilitySchema` (name, description, JSON-Schema `parameters` and `returns`), the pure contract the
`base` design assigns to the capability schema (design "Base contracts"). New data structures are dataclasses, not pydantic
(Requirement 16.1, D24); the current `CapabilitySchema`, `CapabilityResult` and `CapabilityCall` models still use pydantic
and are migrated under D24/O4 — see "Superseded (history)" and tasks.md.

### Registry and the extension point

`registry.py` holds `CapabilityRegistry` behind the `registry` Port: thread-safe register/get/list/unregister, dotted
namespaces (`weather.get_current`), duplicate-name rejection, and semantic search over name and description. A capability
is the tool extension point: a new local function or remote API is registered here and nothing outside `tools` changes
(Requirement 6.1, 6.2; design "Extension points"). The registry validates each capability's schema on registration and the
call handler validates arguments at call time (Requirement 16.2).

### Local functions, remote APIs and the decorator

`local_function.py` (`LocalFunctionCapability`) derives a `CapabilitySchema` from a function's signature and docstring,
mapping Python types to JSON Schema, and runs sync or async. `remote_api.py` (`RemoteAPICapability`) wraps an HTTP endpoint
(GET/POST/PUT/DELETE/PATCH, headers, auth, timeout) and calls over the one shared stdlib transport `base/http.py`, so
`tools` opens no socket of its own and imports no third-party HTTP client (Requirement 7.3, 10.7). `decorator.py` exposes
`@capability`, turning a plain function into a `LocalFunctionCapability` with an optional name and description override.
These are the registered capability kinds (Requirement 6.1, 6.2).

### Capability call handling

`capability_call_handler.py` (`CapabilityCallHandler`) is provider-agnostic: it delegates parsing of provider responses and
formatting of results to the provider adapter (`parse_capability_calls`, `format_capability_results` live in `models`), and
owns the provider-independent middle — look the capability up in the registry, validate arguments against the schema,
execute it, and wrap the outcome in a `CapabilityResult`. All provider-specific transformation stays in the provider
adapter, so the handler and the capabilities stay provider-agnostic (Requirement 9.10). `capability_models.py` defines
`CapabilityResult` (and re-exports `CapabilityCall` from `base/completion.py`); a result converts to a `CapabilityMessage`
for the next turn (Requirement 16.2). The term is "Capability", never "Tool", in every type and name (Requirement 22.1,
22.2); the only exceptions are MCP wire terms and the folder name `tools`.

### Execution errors

`exceptions.py` defines the `CapabilityError` hierarchy on top of `SkyeError`: `CapabilityNotFoundError`,
`CapabilityValidationError`, `CapabilityExecutionError`, `CapabilityCallParsingError`. A failing capability is wrapped with
its name and the original error kept as context (`raise ... from e`), so a failure surfaces with context rather than opaquely
(Requirement 18.1).

### Observability of capability calls

The handler and the registry emit structured log events (message plus `extra={...}`) for each capability call, its result
and its latency, and errors with full context, feeding the `observer` Port so a platform engineer can monitor agent
behaviour (Requirement 18.3).

### MCP client, tri-faceted

`mcp_client.py` defines `MCPClientInterface`, the one Port with three facets whose return types are identical across
implementations: `list_tools`/`call_tool` return tools as `CapabilityInterface` objects (reusing the `tools` interfaces),
`list_prompts`/`get_prompt` return prompts as `base` messages (without importing `prompts`), and
`list_resources`/`read_resource` return resources as `Resource` objects of the `base` resource Port (Requirement 10.1, 10.5). `SkyeMCPClient` is a
standard-library JSON-RPC 2.0 client over stateless HTTP POST on `base/http.py`: consume-only, with no stdio transport, no
subprocess and no server of its own; it handles both a plain-JSON and an SSE-framed reply and paginates list calls by cursor
(Requirement 10.2). `MCPToolCapability` is the capability that executes a server tool through the client.

### Built-in by default, fastmcp by explicit choice

`create_mcp_client(target, impl="skyemcp", ...)` returns the built-in client by default, and the `fastmcp` client when
`impl="fastmcp"`; any other value raises `ConfigurationError` and returns no client, and `impl="fastmcp"` without `fastmcp`
installed raises `MissingExtraError` naming the extra `mcp`. The choice is this argument only — no environment variable, no
configuration entry, no fallback (Requirement 10.3, 10.4; D15, D16). `mcp_fastmcp.py` (`FastMCPClient`) is the only module
that imports `fastmcp`, and it imports it lazily through `base.lazy_import.missing_extra` when a client is constructed, never
at `import skye` or `import skye.tools`; it opens a short-lived stateless session per call and converts what `fastmcp`
returns through the same boundary, mapping library errors to `ProviderError`. Both clients are kept equal by the differential
tests in `tests/differential/test_mcp_differential.py` (Requirement 10.4).

### The MCP boundary (one conversion point)

`mcp_boundary.py` is the single place official MCP shapes become Skye types (Requirement 10.6). Both clients hand their raw
payload — a plain `dict` (built-in JSON-RPC) or an `mcp.types`/`fastmcp` object read through `model_dump`/`dataclasses`/
attributes — to the `to_*` functions: `to_tool_schema` → `CapabilitySchema`, `to_tool_result` → the tool's structured or
text value, `to_prompt`/`to_prompt_messages` → `MCPPrompt` descriptors and `base` user/assistant messages,
`to_resource`/`to_resource_contents`/`to_read_resource` → `Resource`. The conversion covers every field and behaviour Skye
consumes; a required field that is absent or malformed raises `ValidationError` naming the MCP type and field, and no
partially populated Skye object is returned (Requirement 10.6). This module imports no third-party library, so `fastmcp`/
`mcp.types` never leak past it.

### Tri-faceted output and resources via a base Port

The three facets convert to Skye types only: tools as `Capability` objects, prompts as `base` messages (the prompt facet
returns `base` messages and does NOT implement `PromptBuilderInterface`, D26), and resources as `Resource`. Under D26 MCP
resources are a Port in `base` (list and read by URI, MIME type, text or bytes) implemented by the MCP client in `tools`, so
`prompts` and `memory` can consume MCP resources through `base` without importing `tools` (Requirement 10.5). The Port
is `skye.base.interfaces.resource` (`ResourceProviderInterface`, a `Protocol` with `list_resources` and `read_resource`, and `Resource`, a
frozen `@validated` dataclass whose `text` and `data` are mutually exclusive; both exported from `skye.interfaces`).
`MCPClientInterface` inherits the Port, so `SkyeMCPClient` and `FastMCPClient` implement it, and `tools/mcp_resource.py` only
re-exports the two names so `skye.tools.mcp_resource` keeps working.

## Data Models

`tools` consumes and produces the `base` contracts: `CapabilityCall` and the `SkyeMessage` role variants (including
`CapabilityMessage`) come from `base`; a completion carries capabilities in the OpenAI data shape converted inside the
provider adapter (Requirement 9.10). The `tools`-local structures are `CapabilitySchema`, `CapabilityResult`, the MCP
descriptors `MCPPrompt`/`MCPPromptArgument`/`MCPToolResult`; `Resource` comes from `base`. New structures are dataclasses, not pydantic
(D24): `CapabilitySchema`, `CapabilityResult` and `CapabilityCall` are `Validated` dataclasses, and no module of `tools` imports
pydantic (`tests/unit/tools/test_mcp_conformance.py`). The MCP descriptors and `Resource` are frozen dataclasses.

## Error Handling

A missing capability, a schema-validation failure, an execution failure and a parsing failure each map to a specific
`CapabilityError` subtype, wrapping the original error and keeping its context (Requirement 18.1). The MCP boundary rejects a
required field that is absent or malformed with `ValidationError` naming the MCP type and field and returns no partial object
(Requirement 10.6); a JSON-RPC protocol error becomes `ProviderError` with the server's code, and a tool result flagged
`isError` becomes `CapabilityExecutionError`. The `fastmcp` client converts what the fastmcp/mcp stack raises into
`ProviderError` so no library error type leaks past the boundary.

## Testing Strategy

Unit tests in `tests/unit/tools` cover the interface, schema, registry, local-function and remote-API capabilities (and, in `test_mcp_conformance.py`, the dataclass rule, the resource Port and the prompt-facet rule),
the decorator, the call handler, the exceptions, the built-in MCP client and the boundary against mocked transport, with no
network. The boundary rule is guarded statically and at runtime by `tests/budget/test_boundary_rule.py` (no third-party
import in `mcp_boundary.py`; no external type in a public annotation or return value). The differential tests in
`tests/differential/test_mcp_differential.py` run the built-in and the `fastmcp` client against a local fake MCP server and
compare the subset Skye consumes (field-subset equality, numeric epsilon, error category), skipping when `fastmcp` is absent
(Requirement 10.4). Property-based tests fit the boundary round-trips and are added where they apply.

## Correctness Properties

*A property is a characteristic that should hold across all valid executions; it bridges the user stories and the tests.*

### Property 1: Registering then resolving a capability round-trips

For any capability with a valid schema, registering it in a `CapabilityRegistry` and then getting it by name returns the same
capability, and listing includes its name; a second registration under the same name is rejected.

**Validates: Requirements 2.1, 2.2**

### Property 2: A capability call is executed against its schema or fails with context

For any registered capability and any arguments, the call handler either validates the arguments against the schema and
returns a `CapabilityResult`, or raises a `CapabilityError` naming the capability and keeping the original error.

**Validates: Requirements 5.1, 5.2, 6.1**

### Property 3: The MCP boundary returns Skye types or rejects the input

For any MCP tool, prompt or resource payload (a plain dict or a library object), the boundary returns a Skye type carrying no
external-library type, or raises `ValidationError` naming the MCP type and field when a required field is absent or
malformed, returning no partial object.

**Validates: Requirements 8.1, 8.2**

### Property 4: Client selection is explicit and types are identical

For any call, `create_mcp_client` returns the built-in client without `impl`, the `fastmcp` client for `impl="fastmcp"`, and
otherwise raises; both clients return identical Skye types for tools, prompts and resources, with no environment variable,
configuration entry or fallback involved.

**Validates: Requirements 9.1, 9.2, 9.3**

### Property 5: tools imports no third-party library on the core path

For any module under `tools`, a static import scan finds no third-party library except `fastmcp` inside `mcp_fastmcp.py`
imported lazily, and `import skye` reaches neither `fastmcp` nor any optional MCP dependency.

**Validates: Requirements 11.1, 11.2**

## Superseded (history)

The former `capability-support` spec is replaced, not deleted; its text is in the git history. The changes:
- The pydantic `CapabilitySchema`, `CapabilityResult` and `CapabilityCall` models are replaced by dataclasses (D24;
  Requirement 16.1); done, guarded by `tests/unit/tools/test_mcp_conformance.py`.
- The `fastmcp`-required, stdio/subprocess MCP design — `MCPCapability` and `MCPServerClient` that import `fastmcp` to run,
  with placeholder stdio framing — is replaced by the consume-only tri-faceted client: a stdlib JSON-RPC-over-HTTP
  `SkyeMCPClient` by default and `FastMCPClient` behind the same Port, selected by an explicit `impl` with no fallback
  (D15, D16; Requirement 10.2, 10.3, 10.4). The legacy `mcp_capability.py` and `mcp_server_client.py` probes are deleted
  (2026-11-08), with their tests and the `LEGACY_TOOLS_PROBES` allowance of `tests/budget/test_boundary_rule.py`: `fastmcp` is imported
  only in `mcp_fastmcp.py`.
- MCP resources moved from a `tools`-internal `Resource` to a resource Port in `base` implemented here (done 2026-11-08), and the MCP
  prompt facet returns `base` messages rather than implementing `PromptBuilderInterface` (D26; Requirement 10.5).
