---
title: "MCP client"
status: current
---

# MCP client

This guide shows you how to list and call the tools of an MCP server, and how to hand them to a model as capabilities.

[MCP](https://modelcontextprotocol.io/) (Model Context Protocol) is a standard way for a server to offer tools, prompts and resources.
Skye ships a client written on the standard library; a second client built on `fastmcp` is optional.

## What you need

- `pip install skyeai` for the built-in client: nothing else to install.
- The address of an MCP server that speaks HTTP (for example `http://localhost:8000/mcp`).

The built-in client only consumes servers over HTTP: JSON-RPC 2.0 over stateless HTTP POST. It has no stdio transport, never starts a
subprocess and never runs a server.

## 1. Create a client and list the tools

`create_mcp_client(target)` returns the built-in client. `list_tools()` already returns capabilities, one per tool, with the schema
the server declared.

```python
--8<-- "examples/capabilities/mcp_client.py:16:32"
```

All the methods of the client are coroutines. When the server cannot be reached the call raises `OSError` or a `SkyeError`; an error
answer from the server raises `ProviderError`.

`create_mcp_client` also takes `headers=` (for example an `Authorization` header for a protected server) and `timeout=` in seconds
(`30.0` by default).

## 2. Give the tools to a model

The capabilities from `list_tools()` go in the list of capabilities like local ones. A call runs through the client, as a
`tools/call` request to the server.

```python
--8<-- "examples/capabilities/mcp_server.py:24:47"
```

When a tool reports an error, the call's `CapabilityMessage` has the status `error`, and the model reads the message of the server.
You can also call a tool directly: `await client.call_tool("name", {"arg": 1})` returns its value (structured content, or the joined
text), and raises `CapabilityExecutionError` when the tool reports an error.

## 3. Prompts and resources

The same client reads the prompts and the resources of the server:

| Method | Returns |
|---|---|
| `list_prompts()` | `MCPPrompt` objects (name, description, arguments) |
| `get_prompt(name, arguments)` | Skye messages, ready for `complete` |
| `list_resources()` | `Resource` objects (URI, name, MIME type) |
| `read_resource(uri)` | a `Resource` with its text or bytes |

```python
--8<-- "examples/tools/mcp_prompts_and_resources.py:33:61"
```

Every MCP client is also a `ResourceProviderInterface`, so you can pass it wherever a resource provider is expected.

## The optional fastmcp client

`impl="fastmcp"` selects a client built on [fastmcp](https://gofastmcp.com/). Use it when you need what the built-in client does not
do, such as the transports fastmcp supports. It returns the same Skye types.

=== "pip"

    ```bash
    pip install skyeai[mcp]
    ```

=== "uv"

    ```bash
    uv add "skyeai[mcp]"
    ```

```python
from skye.tools import create_mcp_client

client = create_mcp_client("http://localhost:8000/mcp", impl="fastmcp")
```

The choice is this argument only: no environment variable, no configuration entry, no automatic fallback. Without the extra,
`impl="fastmcp"` raises `MissingExtraError` naming `mcp`; any name that is not registered raises `ConfigurationError` listing the registered ones. A plugin adds an implementation with
`registrar.mcp_client("name", factory)`; the factory is called as `factory(target, headers=..., timeout=...)` and returns an `MCPClientInterface`.

## See also

- [Local functions](local-functions.md): how capabilities, calls and results work.
- Reference: [`skye.tools`](../../reference/api/tools.md) (`create_mcp_client`, `MCPClientInterface`, `MCPPrompt`, `Resource`).
- Examples: [`mcp_client.py`](https://github.com/ggiallo28/skye/blob/main/examples/capabilities/mcp_client.py),
  [`mcp_server.py`](https://github.com/ggiallo28/skye/blob/main/examples/capabilities/mcp_server.py),
  [`mcp_prompts_and_resources.py`](https://github.com/ggiallo28/skye/blob/main/examples/tools/mcp_prompts_and_resources.py),
  [`mcp_fastmcp.py`](https://github.com/ggiallo28/skye/blob/main/examples/tools/mcp_fastmcp.py).
