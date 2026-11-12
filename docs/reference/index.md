---
title: "Reference"
status: current
---

# Reference

Exact descriptions, for looking things up.

| Page | Contents |
|---|---|
| [Python API](api/skye.md) | Every public class and function, generated from the docstrings: [skye](api/skye.md), [models](api/models.md), [router](api/router.md), [prompts](api/prompts.md), [tools](api/tools.md), [store](api/store.md), [auth](api/auth.md), [dsl](api/dsl.md), [interfaces](api/interfaces.md), [exceptions](api/exceptions.md), [plugins](api/plugins.md) |
| [CLI](cli.md) | The `skye` command: `check`, `fmt`, `render`, `new`, `prompt`, `skill`, `vscode` |
| [.skye language](skye-language.md) | Grammar, blocks, references, expressions and diagnostics |
| [Editor support](editor.md) | The VS Code extension for `.skye` files |
| [Configuration keys](configuration-keys.md) | Every configuration key, its default and its environment variable |
| [Extras](extras.md) | Every optional extra, what it enables and what it installs |

Import paths are short and public: `skye`, `skye.<package>` or a facade such as `skye.dsl` and `skye.interfaces`. Names under
`skye.base` are internal and may move.
