# plugins

What you learn: add an integration to Skye without changing it. You create `plugins = skye.Plugins()` and add to it with a decorator on
top of a function or a class, one decorator for each kind of integration; the three kinds of provider (model, embedding, decision) share the decorator `@plugins.provider`. What you add is there as soon as the decorator runs, wherever that
code runs: at the top of a module, inside a function, in a test.

```python
import skye

plugins = skye.Plugins()


@plugins.template_filter("shout")
def shout(value):
    return str(value).upper() + "!"
```

Read in this order, from the simplest (a function) to the longest (a provider):

1. `template_filter.py`: a function that changes a value in a prompt.
   `template_filter_text.py`: two more, for a list and for a long text.
2. `builtin_toolkit.py`: the built-in toolkits (`files`, `openapi`), how to ask for one, and how to build your own on top of one.
3. `tokenizer.py`: a function that counts tokens.
   `tokenizer_provider.py`: the same, for the models of a provider of your own.
4. `routing_strategy.py`: a function that chooses a model.
5. `decision_model.py`: a class that picks one option out of a set.
6. `agent_type.py`: a class that is an agent.
7. `credential_source.py`: a class that authenticates a request.
8. `store_backend.py`: a class that stores values and counters.
9. `embedding_provider.py`: a class that turns text into vectors.
10. `model_provider.py`: a provider with a profile (key, endpoint, prices), and how to ship a plugin as a package.
11. `mcp_client.py`: a class that talks to an MCP server.
12. `custom_toolkit.py`: a named set of tools that an agent takes apart from its own.
13. `agent.py`: use an agent with tools, a toolkit and a skill: `skye.agent(REACT, ...)`.

`pyproject.toml` is the entry-point declaration of `model_provider.py` that lets `pip install` add a plugin with no line of yours.

| Kind | Decorator | On top of | Example |
|---|---|---|---|
| template filter | `@plugins.template_filter("name")` | a function | `template_filter.py` |
| tokenizer | `@plugins.tokenizer("name")` | a function | `tokenizer.py` |
| routing strategy | `@plugins.routing_strategy("name")` | a function | `routing_strategy.py` |
| decision model | `@plugins.provider("name")` | a class with `decide` | `decision_model.py` |
| agent type | `@plugins.agent("name")` | a class | `agent_type.py` |
| credential source | `@plugins.credential_source("name")` | a class | `credential_source.py` |
| store backend | `@plugins.backend("name")` | a class | `store_backend.py` |
| embedding provider | `@plugins.provider("name")` | a class with `aencode` | `embedding_provider.py` |
| model provider | `@plugins.provider("name", profile=...)` | a class with `generate`, or `plugins.provider("name", cls, profile=...)` | `model_provider.py` |
| MCP client | `@plugins.mcp_client("name")` | a class | `mcp_client.py` |
| toolkit | `@plugins.toolkit("name")` | a class that is a `ToolProvider` | `custom_toolkit.py` |

Run: `python examples/plugins/template_filter.py`

What you see: for each example, what was added and the result of using it by name.

What you need: `pip install skyeai`. No key and no network.
