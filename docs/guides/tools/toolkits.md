---
title: "Toolkits"
status: current
---

# Toolkits

This guide shows you how to give an agent a set of related tools with the toolkits that ship with Skye, how to build on one of them, and how
a `SKILL.md` makes an agent read files.

A toolkit is a group of tools an agent takes apart from its own `tools=`. Each tool is named `<toolkit>.<tool>`, so two toolkits never clash.
The toolkits that ship with Skye are plugins like yours, so you build them by name.

## What you need

- `pip install skyeai`. The four toolkits use the standard library only.

## The built-in toolkits

| Toolkit | Tools | What it does |
|---|---|---|
| `files` | `list_files`, `read_file` | reads the files under one or more folders, and nothing outside them |
| `openapi` | one for each operation of the document | calls an HTTP API described by an OpenAPI document |
| `human` | `ask_human`, `escalate`, `check_escalation` | asks a person a question, or hands a case over to one |
| `shell` | `run_command` | runs a program from a list of allowed names |

## 1. Build a toolkit by name

`skye.toolkit(name, **options)` builds one. The options are the ones of that toolkit, and an unknown name raises `ConfigurationError`
listing the registered ones.

```python
--8<-- "examples/plugins/builtin_toolkit.py:43:48"
```

`list_schemas()` returns the schema of every tool, which is what the model sees. Pass `alias="docs"` to build the same toolkit twice
under two names (the tools become `docs.read_file`).

### `files`

Read only. `root` is the folder it may read and it is required; `roots` is a list of folders, and you give one of the two, not both.

| Option | Default | Meaning |
|---|---|---|
| `root` or `roots` | none | the folder or folders that may be read |
| `max_bytes` | `65536` | the most bytes `read_file` returns (64 KB) |
| `include_hidden` | `False` | names that start with a dot are left out of the listing and refused by `read_file` |

`list_files` returns at most 500 entries. A path that leaves the folder, with `..`, an absolute path or a link that points outside, is
refused, and the error never shows a real path of your machine. With several `roots`, every path starts with the name of its folder
(`refund-policy/references/a.md`), a repeated name gets `-2`, `-3`, and `list_files` with no path lists the folder names.

### `openapi`

One tool for each operation of an OpenAPI document, named after its `operationId`.

| Option | Default | Meaning |
|---|---|---|
| `spec` | none, required | the document: a mapping, the path of a JSON file or an `http(s)` address (JSON only) |
| `base_url` | the first `servers` entry | where the calls go |
| `headers` | none | sent with every call, for example an `Authorization` key; never returned and never logged |
| `allow` | the GET operations | the `operationId` values that become tools |
| `timeout` | `30.0` | seconds to wait |
| `max_bytes` | `65536` | the most bytes of one response that are returned |

Only the GET operations are tools unless you list others in `allow`, so a model cannot change anything on the API by default.

### `human`

The agent asks a person, or hands a case over. `channel` is how the person is reached: `"file"` (the default, writes a ticket to a
`directory` you give and reads the reply from a file next to it) or `"console"`. `timeout` and `poll_interval` are in seconds. A channel
of your own implements `HumanChannel`.

### `shell`

Opt-in. `allow` is required: the list of program names that may run, with no path in them. The command is split into words and run
**without a shell**, so `|`, `>`, `;` and `$(...)` are plain arguments, and the first word must be in `allow` exactly. The environment is
minimal, a time limit kills the process and the output is cut at `max_bytes`.

!!! warning "It is not a sandbox"
    An allowed program such as `git` or `python` can do anything its user can do. Allow only programs you would run yourself.

## 2. Build on a toolkit

A built-in toolkit is a class you can extend. `acme-api` below is the `openapi` toolkit with the document of one API and the key already
set: an agent asks for `acme-api` with just the key and never sees the address or the header.

```python
--8<-- "examples/plugins/builtin_toolkit.py:26:40"
```

`plugins.get("toolkit", "openapi")` returns the class that ships with Skye, so the new name does not replace it. To change what a
built-in name does, pass `replace=True` when you register it.

## 3. Skills add `files` by themselves

An agent that is given a `SKILL.md` with `skills=[...]` adds **one** `files` toolkit over the folders of all its skills, however many
there are. You do not pass `files` yourself, and the agent never imports the toolkits: it asks the registrar for the name `files`.

```python
--8<-- "examples/plugins/builtin_toolkit.py:50:58"
```

The paths the model uses start with the folder of the skill (`refund-policy/references/a.md`). The agent that ships today is a
placeholder: it holds the toolkit in `skill_toolkits` and the loop that calls it is part of the agents work.

## See also

- [Local functions](local-functions.md): the tools a toolkit is made of.
- [Capabilities and toolkits of your own](../extend/custom-capability.md): how to write a toolkit with `skye.Toolkit`, and `check_toolkit` to test it.
- Reference: [`skye.tools`](../../reference/api/tools.md), [`skye.plugins`](../../reference/api/plugins.md).
- Example: [`plugins/builtin_toolkit.py`](https://github.com/ggiallo28/skye/blob/main/examples/plugins/builtin_toolkit.py).
