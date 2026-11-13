---
title: "Local functions"
status: current
---

# Local functions

This guide shows you how to turn a Python function into a capability, run it yourself, and let a model ask for it.

A capability is something a model can ask to run. It has a schema (a name, a description and the JSON Schema of its parameters) and
runs with `execute` (synchronous) or `aexecute` (asynchronous). Skye calls a tool a *capability*; the two words mean the same thing.

## What you need

- `pip install skyeai`. Capabilities are part of the core: there is no extra to install.
- A provider key only to call a real model. The examples run offline without one: a scripted client asks for the calls and the
  example prints which mode ran. In the examples, `get_client("openai")` returns `skye.provider("openai", api_key=...)` when
  `OPENAI_API_KEY` is set.

## 1. Define a capability

Decorate a function with [`@capability`](../../reference/api/tools.md). Sync and async functions both work.

```python
--8<-- "examples/capabilities/local_function.py:21:32"
```

The schema comes from the function:

- **Name**: the function name. **Description**: the first line of the docstring.
- **Parameters**: one property per argument. The type hints map to JSON Schema, nested types included:

    | Type hint | JSON Schema |
    |---|---|
    | `str`, `int`, `float`, `bool` | `string`, `integer`, `number`, `boolean` |
    | `list[X]`, `set[X]`, `tuple[X, ...]` | `array` whose `items` are `X` (`set` adds `uniqueItems`) |
    | `tuple[X, Y]` | `array` with one schema per position (`prefixItems`) |
    | `dict[str, X]` | `object` whose values (`additionalProperties`) are `X` |
    | `X | None`, `Optional[X]` | `X`, and the argument is not required |
    | `X | Y`, `Union[X, Y]` | `anyOf` |
    | `Literal["a", "b"]` | `enum` |

    Any other hint, or no hint, becomes `string`. An argument without a default value, and not typed `X | None`, is required.
- **Descriptions**: each parameter's `description` comes from the Google-style `Args:` section of the docstring.

```python
from typing import Literal

from skye.tools import capability


@capability
def forecast(city: str, days: list[int], unit: Literal["c", "f"] = "c", note: str | None = None) -> str:
    """Forecast for a city.

    Args:
        city: Name of the city.
        days: Days from today, 0 is today.
        unit: Temperature unit.
        note: Free text for the log.
    """
    return city

forecast.get_schema().parameters["properties"]["days"]
# {'type': 'array', 'items': {'type': 'integer'}, 'description': 'Days from today, 0 is today.'}
```

To choose the name and the description yourself, pass them to the decorator. The name must be one a model provider accepts: letters, digits, `_` and `-`, 64 characters at most
(`weather.current` is refused, and the message suggests `weather_current`). A common prefix with an underscore (`weather_current`,
`weather_forecast`) groups capabilities by namespace in a registry.

```python
from skye.tools import capability


@capability(name="weather_current", description="Current weather for a city")
def current_weather(city: str) -> str:
    return f"Sunny in {city}"
```

You can read the schema with `get_schema()`:

```python
--8<-- "examples/capabilities/local_function.py:35:40"
```

## 2. Run it yourself

`execute` runs a sync function; `aexecute` runs either kind (a sync function runs in a worker thread). The arguments are checked
against the schema before the function runs. Calling `execute` on an async function raises `CapabilityValidationError`: use
`aexecute`.

The log records of a run carry the capability name and the outcome, never the arguments: they may hold personal data.

```python
import asyncio

get_weather.execute(location="London", unit="celsius")  # {'location': 'London', 'temp': 12.8, 'unit': 'celsius'}
asyncio.run(fetch_user.aexecute(user_id="user_123"))   # {'name': 'Alice', 'role': 'admin'}
```

## 3. Let the model ask for it

Pass the capabilities to `complete` as a list. When the model wants one, the response has `capability_calls`: each call has an `id`,
a `name` and the `arguments` the model chose.

```python
--8<-- "examples/capabilities/local_function.py:43:58"
```

`capability_choice` steers the model: `"auto"` (the model decides), `"required"` (it must call one) or the name of one capability.

Some models refuse a forced choice: Claude Opus 5.5, Sonnet 5.5, Fable 5.1 and Mythos 5.1, on Anthropic and on Bedrock. For them
Skye asks for the call instead of forcing it, and you write the same request:

- it sends `"auto"` and appends one instruction at the end of the conversation ("Answer now with a call to the capability
  `search`, and nothing else");
- if the answer holds no such call it tries once more, then raises `CapabilityChoiceError` (from `skye.exceptions`);
- the instruction comes back in `response.added_messages`: add those messages to your history before the next call. These models
  tie their reasoning to the conversation as it was sent, so a history without the instruction counts as an edited one;
- `force_choice=True` sends only the named capability, which is more reliable but changes the tool list. It is allowed only
  before the model's first answer; later Skye raises `ValidationError` before calling.

`response.metadata["capability_choice_emulated"]` is `True` when the choice was emulated. A stream is sent the same way, with no
check and no retry.

## 4. Send the results back

Run the calls, then send the conversation back with the assistant turn (`response.to_message()`) and one result message per call.

```python
--8<-- "examples/advanced/function_calling.py:42:63"
```

`execute_capability_calls` (and `aexecute_capability_calls`, which awaits `aexecute`) returns one `CapabilityMessage` per call, in
order. It never raises: when a capability raises, or the model names one that does not exist, the message has the status `error` and
the content `Error: ...`, so the model can read it and recover. Use the async form when any capability is an async function.

To change an argument before the call runs, pass overrides by call id, or run one call yourself with keyword overrides:

```python
messages = response.execute_capability_calls(argument_overrides={"call_123": {"unit": "celsius"}})

for call in response.capability_calls:
    message = call.execute(unit="celsius")  # merged over the arguments the model chose
```

## Many capabilities: the registry

A [`CapabilityRegistry`](../../reference/api/tools.md) holds capabilities by name, finds them by text and runs them.

```python
--8<-- "examples/tools/registry.py:46:67"
```

- `register` raises `CapabilityValidationError` when the name is already taken. `get`, `exists`, `list_all`, `get_by_namespace` and
  `unregister` do what their names say.
- `search(query, limit=5, threshold=0.3)` returns `(name, capability, score)` tuples, best first. The score is a text similarity of the
  query with the name and description, not an embedding search.
- `registry.execute(name, arguments)` raises `CapabilityNotFoundError` for an unknown name, `CapabilityValidationError` when the
  arguments do not match the schema and `CapabilityExecutionError` (the original exception is its `__cause__`) when the capability
  fails. It is the one execution path that raises.

To offer the model a subset, search the registry and pass the result as a list:

```python
selected = [cap for _name, cap, _score in registry.search("weather")]
response = client.complete(messages=question, model="gpt-4o-mini", capabilities=selected)
results = response.execute_capability_calls()
```

!!! warning
    `capabilities=` takes a list. The built-in adapters do not accept a `CapabilityRegistry` there today. A registry is accepted by
    `execute_capability_calls(registry=...)`, which uses it when the request carried no capabilities.

`CapabilityRegistry.get_instance()` returns one registry shared by the process. Prefer your own instance, so tests and handlers do not
share state.

## A loop of calls

`skye.agents` has no agent loop yet (see [Status and roadmap](../../project/roadmap.md)). Until then, write the loop yourself: ask, run
the calls, append the results, repeat until the model answers in text. The example
[`capability_agent.py`](https://github.com/ggiallo28/skye/blob/main/examples/capabilities/capability_agent.py) does it in thirty lines.

## See also

- [Remote APIs](remote-apis.md) and [MCP client](mcp-client.md): capabilities that run elsewhere.
- [Custom capability](../extend/custom-capability.md): implement `CapabilityInterface` yourself.
- Reference: [`skye.tools`](../../reference/api/tools.md), [`skye`](../../reference/api/skye.md) (`CompleteResponse`).
- Examples: [`local_function.py`](https://github.com/ggiallo28/skye/blob/main/examples/capabilities/local_function.py),
  [`function_calling.py`](https://github.com/ggiallo28/skye/blob/main/examples/advanced/function_calling.py),
  [`registry.py`](https://github.com/ggiallo28/skye/blob/main/examples/tools/registry.py).
