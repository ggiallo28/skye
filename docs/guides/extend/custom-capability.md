---
title: "Custom capability"
status: current
---

# Custom capability

This guide shows you how to write a capability by hand, by implementing `CapabilityInterface`, and how to offer a whole toolset through
the `ToolProvider` Port.

Most capabilities need neither: a decorated function ([Local functions](../tools/local-functions.md)), an HTTP endpoint
([Remote APIs](../tools/remote-apis.md)) or an MCP server ([MCP client](../tools/mcp-client.md)) cover the common cases. Write your own
when the schema cannot come from a Python signature, when the capability holds state (a client, a connection), or when calls go
somewhere Skye does not reach.

## What you need

- `pip install skyeai`.

`CapabilityInterface` and `CapabilitySchema` are the Ports of `skye.interfaces`; `skye.tools` re-exports the same two classes, so
import them from either. The `ToolProvider` Port and `CapabilityContext` come from `skye.interfaces`.

## 1. Implement `CapabilityInterface`

A capability has three methods: `get_schema()` returns its `CapabilitySchema`; `execute(**kwargs)` and `aexecute(**kwargs)` run it
with the arguments the model chose.

```python
from typing import Any

from skye.tools import CapabilityInterface, CapabilitySchema


class AddNumbers(CapabilityInterface):
    """Add two numbers: a capability written by hand."""

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name="math_add",
            description="Add two numbers",
            parameters={
                "type": "object",
                "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
                "required": ["a", "b"],
            },
            returns={"type": "number"},
        )

    def execute(self, **kwargs: Any) -> Any:
        return kwargs["a"] + kwargs["b"]

    async def aexecute(self, **kwargs: Any) -> Any:
        return self.execute(**kwargs)
```

- `parameters` is a JSON Schema object: the model sees it as is. Write a description for each property when the name is not enough.
- The name must be unique where the capability is used, and it must be one a model provider accepts: letters, digits, `_` and `-`, 64 characters
  at most (a dot or a space is refused with a message that suggests a valid name). An underscore groups capabilities by namespace
  (`math_add`, `math_subtract`), and `registry.get_by_namespace("math")` lists them.
- `aexecute` must not block the event loop: await an async client, or run blocking work with `asyncio.to_thread`.
- Raise when the call fails. The response methods turn the exception into a `CapabilityMessage` with the status `error`, which goes back
  to the model; raise `CapabilityExecutionError(message, capability_name="math_add")` (from `skye.exceptions`) to say it is the capability that
  failed.
- Return any value: a string stays as it is, a dictionary or a list becomes JSON in the message for the model.

## 2. Use it

A hand-written capability is used like any other: in the list of capabilities of a call, or in a registry.

```python
from skye.tools import CapabilityRegistry

add = AddNumbers()
response = client.complete(messages=question, model="gpt-4o-mini", capabilities=[add])
results = response.execute_capability_calls()

registry = CapabilityRegistry(capabilities=[add])
print(registry.execute("math_add", {"a": 2, "b": 3}).content)  # 5
```

When you only need a schema the signature cannot express (an enum, a minimum, a nested object) for a plain function, wrap the function
and give it the schema instead of writing a class:

```python
from skye.tools import CapabilitySchema, LocalFunctionCapability


def search(query: str, top_k: int = 5) -> list[str]:
    return [query] * top_k


search_docs = LocalFunctionCapability(
    search,
    schema_override=CapabilitySchema(
        name="docs_search",
        description="Search the documentation",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}, "top_k": {"type": "integer", "minimum": 1}},
            "required": ["query"],
        },
    ),
)
```

With `schema_override`, the capability takes the overridden name (`docs_search`): the registry and the errors use it, not the name of
the function.

## 3. Offer a toolset: the `ToolProvider` Port

`ToolProvider` is how a runtime component takes its toolset: it lists the schemas for an operation and runs one call. It is a
runtime-checkable Protocol with three coroutines, so nothing needs to be inherited. `CapabilityRegistry` implements it; a client of a
remote tool catalogue is another implementation.

```python
from skye.completion import CapabilityCall, arun_capability_call
from skye.interfaces import CapabilityContext
from skye.messages import CapabilityMessage
from skye.tools import CapabilityInterface, CapabilitySchema


class StaticToolset:
    """A ToolProvider over a fixed set of capabilities."""

    def __init__(self, capabilities: list[CapabilityInterface]) -> None:
        self._by_name = {c.get_schema().name: c for c in capabilities}

    async def list_schemas(self, operation: str | None = None) -> list[CapabilitySchema]:
        return [c.get_schema() for c in self._by_name.values()]

    async def run(self, call: CapabilityCall, context: CapabilityContext | None = None) -> CapabilityMessage:
        capability = self._by_name.get(call.name)
        return await arun_capability_call(capability, call.id, call.name, call.arguments)

    async def close(self) -> None:
        """Nothing to release."""
```

The promises of the Port:

- `list_schemas(operation)` returns the schemas the model may be offered for that operation (all of them for `None`), and an empty
  list when there are none.
- `run` never raises for a failing call: it returns a `CapabilityMessage` with the status `error`. `arun_capability_call` does this
  for you, including the message for an unknown name.
- `context` carries the scope token and the operation; keep it apart from the model's arguments.
- `close` releases what the provider holds (a connection, a session); it is called once.

No released component takes a `ToolProvider` yet: the agent loop will (see [Status and roadmap](../../project/roadmap.md)). Until then,
call `list_schemas` and `run` from your own loop.

## A toolkit: a named set of tools

A toolkit is a set of tools that several agents share or that needs a setup (a connection, a folder, a key). You add it as a plugin and
an agent takes it apart from its own `tools=`, in `toolkits=[...]`. The class extends `skye.Toolkit`, takes its options in `__init__`, and
writes one method for each tool with the `@capability` you already know (`self` is not part of the schema):

```python
--8<-- "examples/plugins/custom_toolkit.py:21:60"
```

The name of a tool is the toolkit and the method: `create_issue` of `"jira"` is `jira_create_issue`, so a toolkit never clashes with your own
tools. Build one with `skye.toolkit("jira", base_url=...)`; to use the same toolkit twice, give each an `alias`
(`skye.toolkit("jira", alias="jira-eu", ...)`). Functions with no state need no class: `plugins.toolkit("text", tools=[slugify])`.
`async close()` releases what the toolkit holds. The name of a tool is `<toolkit>_<method>` with letters, digits, `_` and `-` only and 64 characters at most, the names that every provider accepts; a longer or other name raises a `ConfigurationError` that tells you to give the toolkit another alias or the tool another `name=`. A function marked with `@capability` stays callable: `slugify("A B")` calls the function itself, and `slugify.execute(...)` runs it with the checks.

Skye ships four toolkits, each built by name:

| Name | Tools | Options |
|---|---|---|
| `files` | `list`, `read`: read-only, nothing outside the folder, hidden names left out | `root` (required), or `roots` for several folders; `max_bytes`, `include_hidden` |
| `openapi` | one tool for each operation of an OpenAPI document (JSON); GET only unless you allow more | `spec` (path, address or the document), `base_url`, `headers`, `allow`, `timeout`, `max_bytes` |
| `human` | `ask`, `escalate`, `check_escalation`: the agent asks a person, or hands a case over | `channel` (`"file"` or `"console"`), `timeout`, `poll_interval`, and the options of the channel |
| `shell` | `run_command`: runs one program from a list you give, with no shell | `allow` (required), `cwd`, `timeout`, `max_bytes`, `env` |

`shell` is opt-in and is not a sandbox: it runs the programs you list with the permissions of your process, so list only what the agent may
run. A built-in toolkit is a plugin like yours, so you can build on it (a subclass of `plugins.get("toolkit", "openapi")` with the document and
the key already set), as
[`builtin_toolkit.py`](https://github.com/ggiallo28/skye/blob/main/examples/plugins/builtin_toolkit.py) shows. An agent that is given a
`SKILL.md` (`skills=[...]`) also gets `files`, limited to the folder of that skill.

## See also

- [Local functions](../tools/local-functions.md): `@capability`, the registry, and how results go back to the model.
- [Which Port to implement](index.md): every Port of Skye.
- Reference: [`skye.tools`](../../reference/api/tools.md), [`skye.plugins`](../../reference/api/plugins.md),
  [`skye.interfaces`](../../reference/api/interfaces.md).
- Examples: [`custom_toolkit.py`](https://github.com/ggiallo28/skye/blob/main/examples/plugins/custom_toolkit.py),
  [`registry.py`](https://github.com/ggiallo28/skye/blob/main/examples/tools/registry.py),
  [`capability_agent.py`](https://github.com/ggiallo28/skye/blob/main/examples/capabilities/capability_agent.py).
