# The `.skye` language

One language for three kinds of block: `router`, `flow` and `prompt`. A file may hold several blocks, in any order, and is self-sufficient
unless it takes parts of other files (see Include below). It may start with front matter: `---`, TOML `key = value` lines (`title`, `description`, `version`, `tags`; never YAML `key: value`), `---`. Comments: `/** ... **/` documents (a section, a usage example), `#` to the end of the line is a short note; a plain `/* ... */` only disables code for a while, never in a shared file (not `//`, which is floor division). Each item of a block is on its own line or separated by a comma.

```text
KIND "label" { ... }        a block: router "main", flow "triage", step "Classify", route "fast"
name = value                an attribute
KIND "label" = [ ... ]      shorthand: route "fast" = ["openai/gpt-4o-mini", "anthropic/claude-haiku"]
```

## Values

Strings (`"..."`, or `"""..."""` over several lines), numbers, `true` and `false`, lists `[a, b]`, maps `{ k = v }`, references, expressions.
**Durations are strings with a unit:** `"30s"`, `"5m"`, `"24h"`. A bare `30` is an error and the message says so.

## References always have a prefix

| Prefix | Meaning |
|---|---|
| `registry.NAME` | a name in the dictionary the Python caller passes (an agent, a function, a model, a team) |
| `flow.NAME`, `router.NAME`, `prompt.NAME` | a block of the same file |
| `step.NAME.output` | the result of a step of the same flow |
| `context.FIELD` | a field declared in the flow's `context` |
| `env.NAME` | an environment variable (use it for keys, never write a key in the file) |
| `item` | the current element inside a step that has `foreach` |

Inside a `prompt` block the variables are written bare (`domain`, `turn.role`).
A prompt variable may have a shape, with the same field syntax as the `output` block: `list({ name = string, note = string("") }, [])`
(see [prompt.md](prompt.md)). Only a prompt's `variables` and an `output` block take a trailing `"description"` after a type.

## Expressions

Python-like and safe: comparison, `and`, `or`, `not`, `+ - * /`, `in`, and the functions `len`, `min`, `max`, `abs`, `round`, `str`, `int`,
`float`. Nothing else: no other calls, no names with a leading underscore. They are used in `when` conditions and in `set`.

## Include (version 1.1)

A prompt takes what files repeat from a **partial** (a file shaped like a prompt, front matter `partial = true`, not listed or built alone).
`from "lib/m.skye" import a, b as c` or `include "lib/m.skye" as m` (`as` is required) at the top; then one `use a` per line, where
the content goes: in `variables` it inserts entries, in a message body the `when a` / `when not a` blocks of the partial. `use m` brings a
whole file. A duplicate name is an error; to change what a `use` brought, write `override` after it: `override show_ids = bool(true) "..."`
in `variables`, `override when not show_ids { ... }` in a body. A partial holds no `use` or `override`. Paths are relative and stay in the folder. A builder reads them: `register_template(name, path, from_string=False)`.

```skye title="lib/m.skye"
---
partial = true
---
prompt "m" {
  variables = { who = string("") "The user" }
  message "system" { when who { text = "User: {{ who }}" } }
}
```

```skye title="app.skye"
from "lib/m.skye" import who

prompt "app" {
  variables = { use who }
  message "system" { use who }
}
```

## Not available yet (version 2)

`wait` and `on_event` (waiting for an event with persistence), and in prompts: examples, multimodal content and `bind`
(the prompt `output` block is available: see [output.md](output.md)). The checker rejects them with "not available in this version". Do not write them; say that they are not available and offer
the nearest thing that is (see [flow.md](flow.md)).

## Nesting

Inside a flow the structure is flat: a `parallel` holds only `step`s, and a `choice` or another `parallel` cannot sit inside it. Depth is
obtained by composition: a step runs another flow (`run = flow.NAME`), and that flow can have its own `parallel` or `choice`. A flow cannot
contain itself. Prompt `when` and `each` blocks nest freely, but never more than 100 levels in all (blocks, maps, lists and the brackets of an
expression count): deeper is the error "nesting is too deep (more than 100 levels)". Move the inner part into its own flow or prompt.

## Read the errors

Each message names the file, line, column, reason and fix, and suggests the closest name ("Did you mean ...?"). Fix the first message, run
`skye check` again, and repeat: later messages often disappear with the first.
