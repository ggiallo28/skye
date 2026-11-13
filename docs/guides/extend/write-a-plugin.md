---
title: "Write a plugin"
status: current
---

# Write a plugin

A plugin adds one thing to Skye without changing it: a model provider, a storage backend, a tool set, a routing strategy. This page
shows the whole path, from the first line to a package that `pip install` adds. The page [Extend Skye](index.md) tells you which kind to
pick; here you see how any of them is written.

## One handle, one decorator

You create the handle once and add to it. Everything you add is registered as soon as the call runs, wherever the code runs: at the
top of a module, inside a function, in a test.

```python
--8<-- "examples/plugins/template_filter.py:15:23"
```

There are nine kinds, and each has its own word: `provider`, `backend`, `credential_source`, `routing_strategy`, `mcp_client`,
`tokenizer`, `template_filter`, `agent` and `toolkit`. The table with the word of each one is in [`skye.plugins`](../../reference/api/plugins.md#the-nine-kinds).
A model, an embedding and a decision provider share the word `provider`; Skye tells them apart by the methods of the class, or by
`function=` (`"model"`, `"embedding"`, `"decision"`) when you want to say it.

The word that adds a kind is also the word that builds it: `@plugins.agent("name")` adds an agent and `skye.agent("name")` builds it.

### The decorator and the direct call

The decorator goes on top of a function or a class. The direct call takes the name and the target, and is the form to use for a class you
do not own:

```python
plugins.provider("acme", OpenAICompatibleProvider, profile=profile)
```

### A name that is already taken

A name already registered for its kind raises `ConfigurationError`. Pass `replace=True` to take it over, for example to put your own class
under the name of a built-in one:

```python
@plugins.agent("react", replace=True)
class MyAgent: ...
```

## Write async methods only

A provider writes its call once, as an async method: `async def _acall_provider(request)` and an async generator for the stream. The
synchronous `complete` and `stream` are derived from the async ones by Skye, and so are `encode` and `encode_batch` from `aencode` and
`aencode_batch`. A blocking library goes through `asyncio.to_thread` inside the async method. A class that still defines the old
synchronous hooks does not instantiate; the error names the method to write. See [Custom provider](custom-provider.md).

## Say what is specific to a provider once

Everything that belongs to one provider is declared once, in its **profile**: the variables the key is read from, the default endpoint,
the region rule, and for each model its prices, its tokenizer and what it can do. Cost, token counting and the client read the profile
and need nothing else. The reference of every field is in [Provider profile](../../reference/provider-profile.md).

```python
--8<-- "examples/plugins/model_provider.py:26:43"
```

`skye.provider("acme")` now builds the client, as it builds the built-in providers. To change a provider that exists, you do not
register it again: you merge a change into its profile.

```python
--8<-- "examples/plugins/tokenizer.py:34:35"
```

The merge rules are in the [reference](../../reference/provider-profile.md#change-a-profile-that-exists).

## Ship it as a package

A plugin installed with `pip` needs no line in your program. The package declares a module in the entry-point group `skye.plugins`:

```toml
--8<-- "examples/plugins/pyproject.toml:5:11"
```

The value is a module. Skye imports it the first time it meets a name it does not know, and `import skye` never does; importing the
module runs the `plugins` calls it contains.

To see what is registered and what each installed plugin did, run:

```bash
skye plugins
```

It prints the registrations of each kind, and for every entry point its name, its distribution, and one state: `loaded`, `failed` (with
the error) or `skipped`. See [`skye plugins`](../../reference/cli.md#skye-plugins).

To let only some installed plugins load, name them in the `plugins` key of the configuration file; a plugin not listed is never
imported, and `[]` lets none load. See [Which plugins load](../../reference/configuration-keys.md#which-plugins-load).

## Check what you wrote, offline

Each kind has a function that runs the rules of its Port against fakes, with no key and no network. It returns the names of the checks
that passed, or raises `AssertionError` naming the first one that failed. The built-in registrations pass the same functions in the
test suite, so a plugin that passes them behaves as the ones that ship with Skye.

Every kind has a check you import from the package that owns it:

```python
from skye.agents import check_agent
from skye.auth import check_credential_source
from skye.models import check_provider, check_tokenizer
from skye.prompts import check_template_filter
from skye.router import check_routing_strategy
from skye.store import check_backend
from skye.tools import check_mcp_client, check_toolkit

await check_backend(make_backend)                        # a function that builds a fresh backend
await check_toolkit(MyToolkit, option="value")           # lists the tools, runs none
await check_mcp_client(MyClient, "http://localhost:8000/mcp")  # builds the client, never connects
```

Importing the package does not import the check: it is read the first time you ask for it. Call them from a test of your package.

## Next

| You want to | Read |
|---|---|
| Write a provider class of your own | [Custom provider](custom-provider.md) |
| Add a storage backend | [Custom store backend](custom-store.md) |
| Add tools or a toolkit | [Custom capability](custom-capability.md) |
| See one runnable example of each kind | [`examples/plugins/`](https://github.com/ggiallo28/skye/tree/main/examples/plugins) |
