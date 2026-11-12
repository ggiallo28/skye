---
title: "Configuration"
status: current
---

# Configuration

This guide shows you how to load the Skye configuration from a JSON file, the environment and code, and how to set the log levels.

## What you need

- `pip install skyeai`. Configuration is standard library.
- Optionally, a JSON file. The library reads no YAML: a `.yaml` or `.yml` file raises `ConfigurationError`. A router is not written
  here: it is a `router` block in a `.skye` file (see [Aliases and fallbacks](routing/aliases-and-fallbacks.md)).

## 1. Write the file

```json
{
  "log_level": "INFO",
  "component_log_levels": {"router": "DEBUG", "tools": "WARNING"},
  "correlation_id_header": "${CORRELATION_HEADER}"
}
```

`${NAME}` is replaced by the environment variable `NAME` when the file is loaded, in the file and in the overrides. A variable that is
not set raises `ConfigurationError` naming it.

The file holds only the keys the library reads: `log_level`, `component_log_levels`, `correlation_id_header` and `plugins` (the installed
plugins that may load; see [Which plugins load](../reference/configuration-keys.md#which-plugins-load)). Any other key raises
`ConfigurationError` naming it, so a mistyped key is caught when the file loads instead of being ignored. Models and their keys are
not configured here: they belong to the router (see [Aliases and fallbacks](routing/aliases-and-fallbacks.md)). The keys, their
defaults and their meaning are in [Configuration keys](../reference/configuration-keys.md).

## 2. Load it

`skye.load_config(path=None, *, overrides=None)` returns a validated `SkyeConfig`. Values come from three sources; the higher one wins:

1. `overrides`, the values you pass in code;
2. the `SKYE_` environment variables;
3. the file.

```python
--8<-- "examples/basic/configuration.py:18:43"
```

With no `path`, `load_config` reads the file that `SKYE_CONFIG` names; with neither, only the environment and the overrides count. A
missing file, a file that is not `.json`, text that is not a JSON object, an unknown key, or values that do not validate raise
`ConfigurationError` with the details. `load_config` then applies the log levels it read (see [Logging](#logging)).

## The environment variables

Skye reads two prefixed variables:

| Variable | Effect |
|---|---|
| `SKYE_CONFIG` | the path of the JSON file `load_config` reads when you pass no path |
| `SKYE_LOG_LEVEL` | sets `log_level` (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`) |

Credentials never come from a `SKYE_` variable: each provider reads its own standard variable (`OPENAI_API_KEY`, `AWS_*`, ...). See
[Credentials and secrets](security/credentials.md).

## Configuration that is not in a file

`ConfigLoader` in [`skye.config`](../reference/api/skye.md) takes the text of a file, or a dictionary, and opens nothing. Use it when
the configuration comes from a secret store, a test or a string.

```python
from skye.config import ConfigLoader

config = ConfigLoader.from_text('{"log_level": "INFO"}', source="inline")
config = ConfigLoader.from_dict({"log_level": "INFO"}, overrides={"log_level": "DEBUG"})
config = ConfigLoader.load(overrides={"log_level": "ERROR"})  # environment and code only
```

`ConfigLoader.load()` with no text and `SKYE_CONFIG` set raises `ConfigurationError`: it does not open files, so it tells you to call
`skye.load_config()`.

## Logging

Skye logs with the standard `logging` module, on loggers named after its modules: `skye.models...`, `skye.router...`, `skye.tools...`.
It installs no handler, so you choose where the records go. `skye.load_config` sets the levels it reads: the `skye` logger gets
`log_level` and each `skye.<component>` logger its entry of `component_log_levels`.

```python
import logging

import skye

logging.basicConfig(format="%(asctime)s %(name)s %(levelname)s %(message)s")

config = skye.load_config("skye.json")  # "skye" gets log_level; "skye.router" and "skye.tools" get their own
```

A configuration built with `ConfigLoader` (from text or a dictionary) does not touch the loggers: call `config.apply_log_levels()`.
An error never logs itself when it is raised: the code that handles it logs it once, so a caught error prints nothing.

`config.level_for("router")` returns the level of one component: its entry in `component_log_levels`, else `log_level`.

## What you get

A `SkyeConfig`: a validated object with the three keys above, its log levels already applied to the `skye` loggers.

## See also

- [Observability](observability.md): what you can watch today.
- Reference: [Configuration keys](../reference/configuration-keys.md), [`skye`](../reference/api/skye.md) (`skye.config`).
- Example: [`configuration.py`](https://github.com/ggiallo28/skye/blob/main/examples/basic/configuration.py).
