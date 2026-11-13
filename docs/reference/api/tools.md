---
title: "skye.tools"
status: current
---

# `skye.tools`

Capabilities: the registry, local functions, remote APIs and the MCP client. Generated from the docstrings.

::: skye.tools
    options:
      show_root_heading: false
      show_submodules: false


## Where the code lives

`skye.tools` has two plugin folders, one for each thing you choose by name:

| Folder | Holds | Chosen with |
|---|---|---|
| `skye.tools.engines` | the MCP clients: `skyemcp` (the default, standard library) and `fastmcp` (optional) | `skye.mcp_client(target, impl="fastmcp")` |
| `skye.tools.plugins` | the toolkits: `files`, `openapi`, `human`, `shell` | `skye.toolkit("files", root="docs")` |

An engine is one of several implementations of the same Port (today `MCPClientInterface`), and a toolkit is what an agent is given. Both are
registered by `"module:attribute"` text, so `import skye` imports none of them.

## `skye.Toolkit`

The base class of a toolkit. Its methods marked with `@capability` are its tools, named `<toolkit>_<method>`; a toolkit with no constructor
takes its prefix from the class name (`JiraToolkit` is `jira`). A toolkit made from a function or a list of tools is registered with
`plugins.toolkit("name", tools=[...])`. See [Toolkits](../../guides/tools/toolkits.md) for the ones that ship and
[Capabilities and toolkits of your own](../../guides/extend/custom-capability.md) to write one.

## Checking what you add

Two functions run offline and return the names of the checks that passed, or raise `AssertionError` naming the first that failed:

```python
from skye.tools import check_mcp_client, check_toolkit

await check_mcp_client(MyClient, "http://localhost:8000/mcp")   # builds the client, never connects
await check_toolkit(MyToolkit, option="value")                  # lists the tools, runs none
```
