---
name: skye
description: Write, check, generate and explain Skye (the `skyeai` Python library) code and `.skye` files, which hold routers, flows and prompts. Use whenever the user mentions Skye, skyeai, a `.skye` file, `skye check` or `skye new`, a model router with fallbacks, a flow with steps, a prompt block, or a plugin (`skye.Plugins()`, a provider profile), or asks to configure, generate or fix any of them, even if they never say "skill".
---

# Skye

Skye is a modular GenAI library: one client per provider, a model router with fallbacks, capabilities, agents, flows and prompts.
Its core is the Python standard library only, and routers, flows and prompts are written in one small language in `.skye` files.

## Do this first

1. Start from a template instead of a blank file: `skye new router|flow|prompt NAME` (add `-o FILE` to write it).
2. Edit it. Lines marked `CHANGE ME` are the ones to change, the `description` of the front matter among them.
3. Run `skye check FILE` and fix every message until it prints `ok`. Each message gives the line, the column, the reason and the fix, so
   the checker, not memory, is the source of truth for syntax.

## Read only what the task needs

| The task is about | Read |
|---|---|
| the `skye` command, templates, installing this skill | [references/cli.md](references/cli.md) |
| the syntax, references, expressions, what is not available yet | [references/language.md](references/language.md) |
| a router: models, fallbacks, strategies, retries | [references/router.md](references/router.md) |
| a flow: steps, branches, parallel, loops, errors | [references/flow.md](references/flow.md) |
| a prompt: variables, roles, conditions, loops | [references/prompt.md](references/prompt.md) |
| a prompt's answer as JSON, table or XML (`output`, conditional outputs) | [references/output.md](references/output.md) |
| calling a provider or loading a router from Python | [references/python-api.md](references/python-api.md) |
| adding a provider, a store, a tool set or an agent with `skye.Plugins()`, a provider profile, `skye plugins` | [references/plugins.md](references/plugins.md) |
| writing or reviewing code inside the library | [references/rules.md](references/rules.md) |

## Why these habits

Skye is new, and a model's memory of other configuration languages (YAML, Terraform, Jinja) is a poor guide to its rules: references
need a prefix, durations are strings, every step has `next`. A file that passes `skye check` is valid by construction, so use it every time.
