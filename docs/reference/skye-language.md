---
title: ".skye language"
status: current
---

# .skye language

This page is the complete reference of the `.skye` language: grammar, blocks, fields, references, expressions, limits and errors.
For an overview with one example of each block, read [The .skye language](../concepts/skye-language.md) first.

`.skye` is one small, readable language for routers, flows and prompts, in files with the extension `.skye`. The parser is written in
the standard library; it takes text, not a path, and never uses `eval`. A file may hold several blocks, in any order; each file is
self-sufficient unless it takes parts of other files with `include` and `use` (see [Include and partial files](#include-and-partial-files)).

Check a file with `skye check app.skye`; start a new one with `skye new flow my_flow` (see [Tools](#tools) and the
[CLI reference](cli.md)).

## Grammar

```text
file        = { block } ;
block       = KIND [ LABEL ] "{" { attribute | statement | block } "}"
            | KIND LABEL "=" value                       (* shorthand: route "fast" = [ ... ] *)
            | KIND LABEL ;                               (* no body: placeholder "history" *)
attribute   = NAME "=" value ;
statement   = "set" NAME "=" value                       (* inside a step or a branch *)
            | "emit" STRING ;
when        = "when" expression "{" body "}" ;           (* choice branch, prompt condition *)
else        = "else" "{" body "}" ;
each        = "each" NAME "in" expression "{" body "}" ; (* prompt loop *)
LABEL       = STRING | name ;                            (* message turn.role { ... } *)
value       = string | number | bool | list | map | typecall | reference | expression ;
string      = '"' text '"' | '"""' multi-line text '"""' ;
number      = digits [ "." digits ] [ ("e" | "E") [ "+" | "-" ] digits ] ;
bool        = "true" | "false" ;
list        = "[" [ value { "," value } [ "," ] ] "]" ;
map         = "{" [ NAME "=" value { "," NAME "=" value } [ "," ] ] "}" ;
typecall    = TYPE [ "(" [ value ] ")" ] ;               (* string("x"), number(0), list *)
TYPE        = "string" | "number" | "bool" | "list" | "map" ;
duration    = STRING matching digits ("s" | "m" | "h" | "d") ;   (* "30s", "5m", "24h" *)
reference   = name ;
include     = "include" STRING "as" NAME ;               (* top level: loads a partial file under a name *)
import      = "from" STRING "import" NAME [ "as" NAME ] { "," NAME [ "as" NAME ] } ;
use         = "use" NAME ;                               (* where an entry or an item may stand *)
name        = IDENT { "." IDENT } ;
comment     = "#" { any character but newline }
            | "/*" { any character } "*/" ;             (* may span lines; does not nest *)
```

Items of a body are separated by a new line or by a comma. Inside `[ ]`, `{ }` of a value and `( )` a new line is just a space. A string
escapes `\n`, `\t`, `\r`, `\"` and `\\`; the text of a `"""` string loses its first new line and its common indentation.
Lines and columns count from 1 in every message.

### Comments

The language drops every comment; the convention says which kind to write:

- `/** ... **/` documents: what a section is for, and the usage example at the end of a prompt file. It may span lines; a long
  explanation is one `/** **/` block, not a run of `#` lines (more than two `#` lines in a row should be a block).
- `#` is a short note on one line, alone or after an item (`route "fast" = [...]   # cheap first answer`).
- A plain `/* ... */` is only for disabling code for a while; it does not belong in a shared file (bundled prompts, examples).

A bundled or example prompt file ends with a usage-example doc comment, after the prompt's closing brace. The dictionary inside it is
made of Python literals only (strings, numbers, booleans, `None`, lists, dicts), so a test reads it with `ast.literal_eval` and renders
it:

```skye
/**
 * Example:
 *
 *   builder.render("greeting", {
 *       "name": "Alice",
 *       "product": "Skye",
 *   })
 **/
```

### Front matter

A file may start with metadata between two `---` lines. It is TOML (`key = value`, the same form as an attribute), not YAML: a
`key: value` line is an error with the fix. The keys are free; the bundled files use `title`, `description`, `version` and `tags`.
`skye.load(path).metadata` holds it as a dict, `skye fmt` writes it back unchanged, and the line numbers of the rest of the file do not change.
The prompt loader takes the template version from `version`.

```skye
---
title       = "Support router"
description = "Routes support questions to a fast and a strong model"
version     = "1.2"
tags        = ["support"]
---
/** The routes; the first target of each list is the primary. **/
router "support" {
  route "fast" = ["openai/gpt-4o-mini"]   # cheap first answer
}
```

## Block kinds

| Kind | Where | What it holds |
|---|---|---|
| `router ["name"]` | top level | global fields, `route`, `retry_policy`, `allowed_fails_policy` |
| `flow "name"` | top level | `context`, `step`, `parallel`, `choice` |
| `prompt "name"` | top level | `variables`, `allow_missing`, `message`, `placeholder`, `each`, `when` |

Version 1 reads these three. A file that holds anything else is rejected with `unknown block`.

### router

Field names are those of today's router configuration. A field that ended in `_seconds` drops the suffix and takes a duration string:
`cooldown_seconds` is now `cooldown = "60s"`, `retry_after_seconds` is `retry_after = "5s"`.

```skye
router "main" {
  strategy               = "rate_limit_aware"
  cooldown               = "60s"
  enable_pre_call_checks = true

  route "gpt-4" {
    strategy          = "round_robin"
    fallback_on_error = true
    fallback          = ["claude"]          # if this route fails, try these routes in order
    target {
      model    = "gpt-4"
      provider = "openai"
      api_key  = env.OPENAI_API_KEY         # becomes the text ${OPENAI_API_KEY}
      tpm      = 100000
      rpm      = 1000
      timeout  = "30s"
      tags     = ["premium"]
      metadata = { region = "us-east-1" }
      options  = { deployment_name = "gpt4-prod" }   # keyword arguments for the provider client
    }
  }
  route "claude" = ["anthropic/claude-haiku", "openai/gpt-4o-mini"]   # shorthand

  retry_policy "RateLimitError" { max_retries = 3, retry_after = "5s", exponential_backoff = true }
  allowed_fails_policy "RateLimitError" { allowed_fails_per_minute = 100 }
}
```

In the shorthand `route "x" = ["provider/model", ...]` the first entry is the primary target and the others are its fallbacks, in order; an
entry may be a map `{ model = "provider/model", api_key = env.X, rpm = 60 }`. Strategies: `simple_shuffle`, `round_robin`, `least_busy`,
`rate_limit_aware`, `latency_based`, `cost_based`, `weighted`, `priority_based`. Targets of one route are alternatives picked by the strategy;
`fallback` names other routes. `cost_based` reads the target fields `cost_per_1k_prompt_tokens` and `cost_per_1k_completion_tokens` (numbers,
0 or more): it picks the available target with the lowest sum of the two (a price left out counts as 0); a target with neither comes last and
ties keep the written order.

### flow

```skye
flow "triage" {
  context { ticket = string, priority = number(0) }

  step "Classify" {
    run   = registry.classifier
    input = { text = context.ticket }
    next  = "Route"
  }

  choice "Route" {
    when step.Classify.output.label == "bug" and context.priority >= 3 { next = "Escalate" }
    else                                                                { next = "General" }
  }

  step "Escalate" { run = registry.oncall_agent,  next = end }
  step "General"  { run = registry.support_agent, next = end }
}
```

- `context { name = type(default) }` declares the typed fields: `string`, `number`, `bool`, `list`, `map`. No default means required.
- `step "Name"`: `run` (a `registry.NAME`, `flow.NAME` or `router.NAME`), `input` (a map), `next`, `on_error`, `on_timeout`, `timeout`,
  `retry`, `max_visits`, `foreach`, and the statements `set field = expr` and `emit "event"`, which run when the step finishes with success.
  `next = end` finishes the flow. A step with no `next` is an error; with no `on_error` it goes to the default error end.
- `retry = { max = 3, after = "2s", backoff = true }`; `retry = 3` means `{ max = 3 }`.
- A step with no `run` is allowed when it has `set`, `emit` or `foreach`.
- `choice "Name"`: `when <expression> { ... }` branches checked in order, and a mandatory `else`.
- `parallel "Name"`: `step` branches, `join = "all" | "any"`, `on_branch_error = "cancel" | "continue"`, `next`, `on_error`. There is no timeout
  on the whole block; each step keeps its own.
- A step that can be entered again (a loop) needs `max_visits = N` on at least one step of the loop. A flow that contains itself is rejected.
- `foreach = context.items` runs the step once for each item; inside it `item` is the current element. It is the only loop over data.
- The first step, parallel or choice in the file is where the flow starts; any other one that cannot be reached is an error.

### prompt

```skye
prompt "summarize" {
  variables     = { text = string, max_words = number(100), style = string("neutral") }
  allow_missing = ["style"]

  message "system" { text = "You write short summaries." }
  placeholder "history"
  message "user" {
    text = "Summarize the text in at most {{ max_words }} words."
    when style { text = "Style: {{ style }}." }
    each line in text { text = "- {{ line }}" }
  }
}
```

Roles are `system`, `user` and `assistant` (or a loop value such as `message turn.role { ... }`). Inside a prompt the variables are written bare, as in a
template; `text` may appear several times in a message and the parts are joined in order. `{{ name }}` and `{{ name | filter }}` interpolate;
the names must be declared in `variables` (or be a loop variable). `{% %}` tags are not used: write a `when` or an `each`.
Inside an `each`, `loop.index` (from 1), `loop.index0`, `loop.first`, `loop.last` and `loop.length` are defined. An `each` over a map loops
over its entries, each with `key` and `value`: `each entry in data { text = "{{ entry.key }}: {{ entry.value }}" }`. To put a list on one
line, use the filters: `{{ tools | map('name') | join(', ') }}`. To put data into the text as JSON, XML or a Markdown table, use the
filters `tojson`, `toxml("root")` and `totable` (or `totable(["name", "price"])` for chosen columns).
A variable may carry a description, a string right after its type (`task = string "What the agent must achieve"`, `phase =
string("plan") "plan, execute or replan"`, one per line or in the comma form): `skye prompt info` and `describe_prompt` show it, and it is
not sent to the model. Only a prompt's `variables` and an `output` block take this trailing string.

A variable may also have a **shape**, written with the field syntax of the `output` block below:

```skye
prompt "classify" {
  variables = {
    categories = list({ name = string "Category name", description = string("") "What it means" }) "Categories to choose from"
    examples   = list({ text = string, category = string, reasoning = string("") }, [])           "Worked examples"
    owner      = map({ team = string, email = string("") })                                        "Who owns it"
    tags       = list(string)                                                                       "Free labels"
  }

  message "user" {
    text = "Pick one of: {{ categories | map('name') | join(', ') }}. Owner: {{ owner.team }}."
    each example in examples { text = "{{ example.text }} -> {{ example.category }}" }
    when tags { text = "Labels: {{ tags | join(', ') }}" }
  }
}
```

The forms are `list(type)` or `[type]`, `list({ fields })` or `[{ fields }]`, `map({ fields })` or `{ fields }`, nested to any depth;
a field is `name = type`, with a default (`string("")`) when it is optional and a trailing description. A structured variable is
required; its default goes after the shape (`list({ ... }, [])`, `map({ ... }, { ... })`) and must match it. The older forms keep
their meaning: `list([])`, `map({})` and `map({ k = 1 })` are a plain list or map with a default, with no shape. At render time
`render_prompt` checks the value given against the shape and raises one `ValidationError` that lists every mistake by path
(`categories[1].name: missing`, `examples[0].text: expected string, got int`); `number` takes an int or a float, `bool` only a bool; a
missing optional field gets its default in a copy (the caller's data is never changed); keys the shape does not declare are kept.

#### The output block: the shape of the answer

An `output` block says what the model must answer and in which format; the renderer writes the instructions, so the structure is
never written by hand in the text.

```skye
prompt "extract_invoice" {
  variables = { document = string }
  output "json" {
    vendor   = string          "Seller name as printed on the invoice"
    total    = number          "Total amount including VAT"
    currency = string("EUR")   "ISO 4217 currency code"
    lines    = list({
      description = string    "Text of the line"
      amount      = number    "Amount of the line"
    })                         "One entry per invoice line"
    meta     = map({ source = string })
  }
  message "user" { text = "Extract the invoice fields from the document.\n{{ document }}" }
}

prompt "products" {
  variables = { text = string }
  output "table" { name = string "Product name", price = number, in_stock = bool }
  message "user" { text = "List the products in: {{ text }}" }
}

prompt "extract" {
  variables = { document = string, fields = map, style = string("xml") }
  output style { schema = fields }
  message "user" { text = "{{ document }}" }
}
```

- The label is the format: `"json"`, `"table"`, `"xml"` or `"text"`; `output { ... }` with no label is `"json"`. Any other string is an error that
  lists the four. A prompt has at most one unconditional `output` block, at the top of the prompt (not inside a message), or any
  number of conditional ones (next item), never both.
- Conditional outputs: an `output` block may sit inside a `when` block at the top of the prompt (or a `when` nested in one; never inside a
  `message` or an `each`, an error), so a variable chooses the shape of the answer:

  ```skye
  prompt "extract_any" {
    variables = { document = string, schema = map({}), format = string("json") }
    when schema     { output format { schema = schema } }
    when not schema { output format { name = string "What the extracted item is", value = string "Its value, as written in the input" } }
    message "user" { text = "{{ document }}" }
  }
  ```

  At render time the active output is the one whose conditions (its `when` and the ones around it) hold, a missing variable taking its
  default; none active means no instructions (free text), and more than one active raises `ValidationError` naming their conditions, so
  write conditions that exclude each other. A prompt with an unconditional `output` and a conditional one is an error naming both lines.
  Every check of the block applies to each conditional one. `skye.prompts.active_output(spec, variables)` returns the active output
  block (or `None`); the prompt model's `output_variants()` lists the conditional ones with their conditions, while its `output` keeps
  the unconditional block. `skye prompt info` shows each one under its condition (`Output (when not schema): json`).
- The label may also be a declared `string` variable (`output style { ... }`, no quotes): the format is its value at render time (or its
  default). An undeclared name is an error with "Did you mean ...?", a variable of another type is an error, and so is a default that is
  not `json`, `table`, `xml` or `text`; at render time a value that is not one of the four raises `ValidationError` listing them, and with
  `"table"` a list or map field raises `ValidationError` naming it (checked then, since the format is not known before).
- `text`: a plain answer, with no fields. `output "text" {}` asks for "Answer in plain text, with no JSON, table or markup around it."; the
  one optional line `style = "a short paragraph"` (or `style = VAR`, a declared `string` variable read at render time) adds the style:
  "Answer in plain text: a short paragraph." Any other line is an error. A bare `output text { ... }` is the variable form above, so the
  label is written with quotes. When the format comes from a variable (`output VAR { ... }`) and its value is `"text"` at render time,
  the fields of the block (and `schema = VAR`) are not read, so one block can serve every format:

  ```skye
  prompt "answer" {
    variables = { question = string, answer_format = string("text"), fields = map({}) }
    output answer_format { schema = fields }
    message "user" { text = "{{ question }}" }
  }

  prompt "plain" {
    variables = { question = string, style = string("a short paragraph") }
    output "text" { style = style }
    message "user" { text = "{{ question }}" }
  }
  ```
- A field is `name = string | number | bool | list | map`, a scalar with a default (`currency = string("EUR")`: a field with a default is
  not required), a list of a type (`list(string)` or `[string]`), a list of objects (`list({ a = string })`), or an object
  (`map({ a = string })` or `{ a = string }`). A bare `list` or `map` takes any items or keys. An unknown type is an error with
  "Did you mean ...?".
- A string right after the type is the field's description, for the model: `total = number "Total amount including VAT"`. It works at
  every level (inside `list({ ... })` and `{ ... }`, after the closing `)` or `}` for the whole list or map) and in the comma form
  (`{ a = string "x", b = number }`). Only an `output` block and the `variables` of a prompt read it: elsewhere a value followed by a
  string is still an error. An empty
  description is an error, and `schema = VAR` takes none (describe the fields in the variable).
- `table`: one row per item, and every column is a `string`, `number` or `bool`; a list or map field is an error that names it.
- `schema = VAR` (the word `schema` is reserved here, and it is the only entry of its block: another field next to it is an error; for
  default fields when the variable is empty, use a conditional output as above) takes the fields at render time from the declared `map`
  variable `VAR`, whose value maps each field name to `"string" | "number" | "bool" | "list" | "map"`, `[type]` or `[{...}]` (a list),
  a nested map (an object), or a described field `{"type": "number", "description": "..."}`, for example
  `{"name": "string", "tags": ["string"], "vendor": {"city": "string"}, "total": {"type": "number", "description": "With VAT"}}`.
  A map with a `"type"` key and no other key than `type`, `description`, `items` and `properties` is a described field: `items` gives
  the item type of a `"list"` (`{"type": "list", "items": {"a": "string"}, "description": "..."}`) and `properties` the fields of a
  `"map"`; an object with a field named `type` is written `{"type": "map", "properties": {"type": "string"}}`. List items take no
  description of their own (describe the list).
- `render_prompt` appends the instructions as the last text of the last user message (a new user message if there is none);
  `skye.prompts.output_instructions(spec, variables)` returns them alone. `json` gives "Answer with a single JSON object and nothing
  else.", the JSON Schema (`required` = the fields without a default; a description becomes the `"description"` of the property, nested
  ones too) and a one-line example; `table` gives the header row, the separator row and the type of each column
  (`- total: number — Total amount including VAT`); `xml` gives a skeleton whose root element is the prompt name in snake_case, a list
  as repeated `<item>` elements and the type of each leaf as text (`<total>number — Total amount including VAT</total>`; a list or map
  with a description gets an XML comment after its opening tag: `<lines> <!-- One entry per invoice line -->`).
- A hand-written format text in a message keeps working; so does `BasePromptBuilder.set_output_schema(name, schema, output_format="json")`
  with a dataclass (a field's `metadata={"description": ...}` is its description) or a JSON-schema dictionary (its `description`s are
  kept), where `output_format` may also be `"table"` or `"xml"` (`"text"` has no fields, so it is refused there).
- The bundled prompt `extraction_generic` takes the format from its `format` variable (`"json"` by default, `"table"` or `"xml"`)
  with a `schema`. `schema` is optional (`map({})`): `when schema` takes the fields from it, `when not schema` asks for two string
  fields, `name` and `value`.

## References and prefixes

A reference always has a prefix, except inside a prompt:

| Reference | Meaning |
|---|---|
| `registry.NAME` | a name resolved from the registry the caller passes (checked only when the caller gives the known names) |
| `flow.NAME`, `router.NAME`, `prompt.NAME` | a block of the same file |
| `step.NAME.output` | the result of an earlier step |
| `context.FIELD` | a declared context field |
| `env.NAME` | an environment variable (in a router block it becomes the text `${NAME}`) |
| `item` | the current element of a `foreach` |

`end` is the one bare word: `next = end`.

## Expressions

An expression is Python-compatible text. It is parsed with `ast.parse(mode="eval")`, checked against a whitelist and walked by a small
evaluator; it is never passed to `eval` or `exec`.

```text
expression = or_test [ "if" or_test "else" expression ] ;
or_test    = and_test { "or" and_test } ;
and_test   = not_test { "and" not_test } ;
not_test   = "not" not_test | comparison ;
comparison = arith { ("==" | "!=" | "<" | "<=" | ">" | ">=" | "in" | "not in" | "is" | "is not") arith } ;
arith      = term { ("+" | "-") term } ;
term       = factor { ("*" | "/" | "//" | "%") factor } ;
factor     = [ "-" | "+" ] atom { "." NAME | "[" expression "]" | "[" [expression] ":" [expression] "]" } ;
atom       = NUMBER | STRING | "True" | "False" | "None" | name | list | tuple | dict | call | "(" expression ")" ;
call       = FUNCTION "(" [ expression { "," expression } ] ")" ;
FUNCTION   = "len" | "min" | "max" | "abs" | "round" | "str" | "int" | "float" ;
```

Anything else is rejected: other calls (`open(...)`, `__import__(...)`, a method call), names or attributes that start with `_`, `**`, shifts,
lambdas, comprehensions, f-strings and the walrus operator. Repeating a string or list more than 10 000 times is a run error.

## Limits

A file may nest at most 100 levels in all: blocks, maps, lists, `type(default)` calls and the brackets of an expression each count one. Deeper
is one error, `file:line:column nesting is too deep (more than 100 levels)`, with the fix "Move the inner part into its own flow or prompt";
it is never a Python exception. The number is half of what the parser, the builder and the emitter survive at Python's default recursion
limit (about 490 levels), rounded down; the recursion limit is not raised.

## Errors

`skye check` prints every error it finds, one per line, as `file:line:column message`, ready to be pasted back to a model:

```text
app.skye:12:12 unknown step "Wirte" in "next". Defined steps: A, Fan, Write. Did you mean "Write"?
app.skye:9:3 step "Fetch" has no next. Add: next = "<step>" or next = end
app.skye:30:3 choice "Decide" has no else. Add: else { next = "<step>" }
app.skye:18:3 step "Write" can be entered again (Decide -> Write) but has no max_visits. Add: max_visits = 4
app.skye:7:12 step "Plan": "plannr" is not in the registry. Known: planner, web_search. Did you mean "planner"?
app.skye:7:12 "planner" has no prefix. Use registry.planner, flow.planner or router.planner
app.skye:22:9 "context.qualty" is not declared. Declared: topic, loops, quality. Did you mean "quality"?
app.skye:41:3 step "Orphan" can not be reached from the start
app.skye:26:5 "wait" needs persistence and is not available in this version
app.skye:19:9 "quality" is number, the value is a string
app.skye:31:12 call "open(...)" is not allowed in an expression. Allowed: len, min, max, abs, round, str, int, float
app.skye:5:5 unknown field "timout" in step "Search". Did you mean "timeout"?
app.skye:9:15 timeout = 30 is not a duration. Use "30s", "5m" or "24h"
app.skye:4:13 role "bot" is not valid. Use system, user or assistant
app.skye:14:5 "cooldown_seconds" was renamed "cooldown" and takes a duration such as "60s"
app.skye:11:15 route "gpt" has no route "claud" in fallback. Did you mean "claude"?
```

A syntax error (an unclosed block, an unterminated string, a value that is missing) is reported alone: the checks that follow need a tree that
parses. In Python, `skye.dsl.check_text(text, filename, registry_names)` returns the same errors as `Diagnostic` objects
(`file`, `line`, `column`, `reason`, `fix`, and `format()` for the printed line), and `skye.load(path)` raises them together as one
`ConfigurationError`. `skye.dsl.build(text, filename=..., registry_names=...)` returns the `Document` (its blocks and its
`diagnostics`) without raising; `document.raise_for_errors()` raises `skye.dsl.SkyeSyntaxError`, whose `.diagnostics` holds every
mistake.

## Include and partial files

A prompt can take what several files repeat (the declaration of a variable, and the text that prints it) from a **partial file**. A
partial is an ordinary `.skye` file written like a prompt, with its own `variables` and `message`, marked with `partial = true` in the
front matter. It is not a prompt: it is not listed by `skye prompt list` and it cannot be built alone. This is language version 1.1.

| Statement | Where | What it does |
|---|---|---|
| `include "lib/memory.skye" as memory` | top level | loads a partial under the name `memory` (`as` is required) |
| `from "lib/agent.skye" import system_prompt, tools` | top level | takes names from a partial; `import tools as agent_tools` renames one |
| `use memory` or `use tools` | a `variables` map, a prompt body or a message body | inserts the content exactly here, one name per line |
| `override name = ...` or `override when name { ... }` | after the `use` that brought it | replaces what that `use` brought (see [Override](#override)) |

Rules:

- **The place decides what is inserted.** In `variables` a `use` inserts entries; in a `message` or `prompt` body it inserts blocks.
  `use memory` (a whole file) inserts the whole `variables` there, and in a message the body of the partial's message of the same name.
- **A name brings its entry and its text.** `use tools` in `variables` inserts the entry `tools`; in a message it inserts the
  first-level blocks of the partial's message whose condition is only `tools` or `not tools` (`when tools { ... }`). A wider
  condition such as `when a or b` is never brought by a name: write it in your file and put `use` inside it.
- **Paths are relative to the file that writes them**, stay inside the folder of the entry file, and are never absolute or a URL.
- **A name defined twice is an error** (in your file and in a partial, or in two partials): it names both places. To change what a
  `use` brought, write an `override` (below); without the word, do not use the part that has it. A partial may not contain `include`,
  `from`, `use` or `override`.
- **Limits.** 64 `include` and `from` lines per document and 1 MB of expanded text.
- **The words are positional.** `from`, `import`, `use`, `as`, `override` and `partial` are still free as the name of a variable or an attribute.

A complete example: two partials, and two prompts that take different names from them. The blocks are one set of files (the `title`
is the path); `skye check` run on `tool_agent.skye` and `chat_agent.skye` finds no error.

```skye title="lib/agent.skye"
---
partial = true
---
prompt "agent" {
  variables = {
    system_prompt = string("")  "Replaces the default system instructions when not empty"
    tools = list({
      name        = string      "Tool name"
      description = string      "What the tool does"
    }, []) "Tools the agent may call"
  }
  message "system" {
    when system_prompt     { text = "{{ system_prompt }}" }
    when not system_prompt { text = "You are an assistant that can use tools." }
    when tools {
      text = "## Tools"
      each t in tools { text = "- {{ t.name }}: {{ t.description }}" }
    }
  }
}
```

```skye title="lib/memory.skye"
---
partial = true
---
prompt "memory" {
  variables = {
    persona_memory = list({
      content = string      "What is known about the user"
      source  = string("")  "Where it comes from"
    }, []) "Who the user is"
    episodic_memory = list({
      content   = string      "What happened"
      timestamp = string("")  "When it happened"
    }, []) "Past events"
  }
  message "system" {
    when persona_memory {
      text = "### Persona"
      each m in persona_memory { text = "- {{ m.content }}" }
    }
    when episodic_memory {
      text = "### Past events"
      each m in episodic_memory { text = "- {{ m.content }}" }
    }
  }
}
```

```skye title="tool_agent.skye"
from "lib/agent.skye"  import system_prompt, tools
from "lib/memory.skye" import persona_memory, episodic_memory

prompt "tool_agent" {
  variables = {
    use system_prompt
    use tools
    input = string("")  "The user's message"
    use persona_memory
    use episodic_memory
  }
  message "system" {
    use system_prompt
    use tools
    when persona_memory or episodic_memory {
      text = "## Memory"
      use persona_memory
      use episodic_memory
    }
  }
  message "user" { text = "{{ input }}" }
}
```

```skye title="chat_agent.skye"
from "lib/agent.skye"  import system_prompt
from "lib/memory.skye" import persona_memory

prompt "chat_agent" {
  variables = {
    use system_prompt
    use persona_memory
    input = string("")  "The user's message"
  }
  message "system" {
    use system_prompt
    when persona_memory {
      use persona_memory
    }
  }
  message "user" { text = "{{ input }}" }
}
```

The same with a whole file: one `include`, and `use memory` in each place.

```skye title="whole.skye"
include "lib/memory.skye" as memory

prompt "chat" {
  variables = {
    use memory
    input = string("")  "The user's message"
  }
  message "system" {
    use memory
    text = "Answer the user."
  }
  message "user" { text = "{{ input }}" }
}
```

The `when persona_memory or episodic_memory { ... }` block stays in each file because it names the memories that file takes; the
build puts the inserted blocks inside it, in the order of the `use` lines.

### Override

`override` changes something that a `use` brought, for example the default of a variable taken from a partial. It stands after the `use`
that brings the name, so the order of the lines is the order of the declarations.

- **In `variables`:** `override name = <definition>` replaces the entry `name` that an earlier `use` of the same map brought. The new
  entry keeps the place of the `use`.
- **In a prompt or message body:** `override when name { ... }` and `override when not name { ... }` replace the first-level block of
  the partial that has exactly that condition. A wider condition such as `when a or b` is replaced by its exact text when a whole-file
  `use` brought it, and cannot be reached by an import by name.
- **Only what a `use` brought.** The name must have been brought by a `use` of your file; a second `override` of the same name, an
  `override` before its `use`, and an `override` in a file with no `use` are errors. A partial may not contain an `override`.
- **The new definition is checked like any other**, and it is reported in your file at the `override` line.

A complete example: a partial that shows ids only when `show_ids` is true (false by default), and a prompt that takes it and turns the
ids on. The two files are one set (the `title` is the path), and `skye check` run on `upkeep.skye` finds no error.

```skye title="lib/memories.skye"
---
partial = true
---
prompt "memories" {
  variables = {
    show_ids = bool(false)  "Show the id of each item and tell the model to refer to it"
    episodic_memory = list({
      id        = string("")  "Item id"
      content   = string      "What happened"
      timestamp = string("")  "When it happened"
    }, []) "Past events"
  }
  message "system" {
    when show_ids { text = "An item that has an id shows it first, in square brackets; refer to the item by that id." }
    when not show_ids { text = "Memories are listed below." }
    when episodic_memory {
      text = "### Past events"
      each m in episodic_memory { text = "- {{ m.content }}" }
    }
  }
}
```

```skye title="upkeep.skye"
include "lib/memories.skye" as memories

prompt "upkeep" {
  variables = {
    use memories
    override show_ids = bool(true)  "Ids are always shown here"
    input = string("")  "The user's message"
  }
  message "system" {
    use memories
    override when not show_ids { text = "Memories are listed below, with their ids." }
  }
  message "user" { text = "{{ input }}" }
}
```

The prompt `upkeep` declares `show_ids` with the default `true`, and its message uses its own text for the `when not show_ids` block; the
rest of the partial is inserted as it is.

The messages of the mistakes (the line and column are those of the `override`):

| Written | Message |
|---|---|
| `override show_ids = ...` before `use memories` | `cannot override "show_ids": no use before this line brought it; brought: none Write the use before the override.` |
| `override nothing = ...` | `cannot override "nothing": no use before this line brought it; brought: show_ids, episodic_memory Write the use before the override.` |
| a second `override show_ids = ...` | `cannot override "show_ids": it is already overridden at line 5 Keep one override.` |
| `override when persona_memory { ... }` with no such block | `cannot override "when persona_memory": no use before this line brought it; brought: when show_ids, when not show_ids, when episodic_memory Write the use before the override.` |
| `override when a { ... }` in a router or a flow | `override is available in prompts only. Write it in a file that has a prompt.` |

Every mistake is reported with the file where it is, its line and column, and the use site (`(used from app.skye:10:5)`; in JSON,
`via`):

| Written | Message |
|---|---|
| `from "lib/memory.skye" import semantic_memory` | `"lib/memory.skye" has no variable "semantic_memory"; it has: persona_memory, episodic_memory` |
| `use memory` with no `include` | `"memory" is not included or imported; the names here are: none` |
| `include "lib/memory.skye"` | `an include needs a name. Write: include "lib/memory.skye" as <name>` |
| `use persona_memory` twice in one body | `"persona_memory" is already used at line 2` |
| an entry written in the file and also brought by a `use` | `"system_prompt" is defined twice: here and at app.skye:2:28. Remove one, or do not use the part that has it.` |
| `from "/etc/x.skye" import a` | `"/etc/x.skye" is not a relative path. An include takes a path relative to the file, such as lib/memory.skye.` |

`skye fmt` keeps these lines where they are, `skye prompt list` skips partials, and `skye.dsl.to_text` writes the expanded text with no
`use`. `skye.load(path)` and `skye check` read the included files from the folder of the entry file; from Python,
`skye.dsl.check_text(text, filename, resolver=...)` takes a `resolver` function instead, because the language itself reads no file.
A prompt builder reads the same lines: `builder.register_template(name, path, from_string=False)` takes the folder of the file as its root
(the files are read again at each registration), `register_template(name, text, resolver=...)` takes a `resolver` for a text, and a folder
loaded with `load_default_templates(builder, folder)` skips the partials. The partials that ship with Skye are private: a file of yours
cannot include them.

A small runnable case, one partial taken by two prompts (one with `from ... import` and `use`, one with `include` and `override`), is
[`examples/prompts/shared_parts.py`](https://github.com/ggiallo28/skye/tree/main/examples/prompts/shared_parts.py).

## Version 1 and version 2

| | Version 1 (built) | Version 2 (reserved) |
|---|---|---|
| Blocks | `router`, `flow`, `prompt` | (none) |
| Sharing | `include`, `from ... import`, `use`, `override` and `partial = true` (version 1.1, see [Include and partial files](#include-and-partial-files)) | (none) |
| Flows | sequence, `choice`, `parallel`, bounded loops, `retry`, `timeout`, `on_error`, `foreach`, `set`, `emit` | `wait`, `on_event` (waiting for events with persistence and resume) |
| Prompts | `variables`, `message`, `placeholder`, `text`, `when`, `each`, `allow_missing`, `output` | `examples`, multimodal `content`, `from`/`bind`, `parts`, type `image` |

A version 2 word in a version 1 file is rejected with "is not available in this version".

## Tools

```bash
skye check app.skye                  # errors as file:line:col message; exit code 1 if there are errors
skye check --registry planner,web_search app.skye
skye check --schema                  # the JSON Schema of the router, flow and prompt blocks
skye new router main                 # a starting file on stdout (templates: shorthand, full)
skye new flow my_flow --template loop -o my_flow.skye   # sequence, branch, parallel, loop, full
skye new prompt my_prompt --template chat               # basic, chat
skye new --list
skye render app.skye --name triage --stdout --fence   # the flow as a Mermaid diagram, ready for Markdown
```

`skye render FILE` draws a flow or a router as a Mermaid `flowchart` and writes `FILE.mmd`; `--stdout` prints it,
`--fence` wraps each diagram in a `mermaid` code fence (and writes `FILE.mmd.md`), `-o` chooses the file, `--direction TD|LR` the
orientation, and `--name` picks one block when the file has several. A step is a box with what it runs, a `choice` a diamond whose edges
carry the `when` text, a `parallel` block a subgraph with its `join` rule, `on_error` and `on_timeout` dotted arrows; a router shows each
route with its strategy and targets and each fallback, in order. From Python: `from skye.dsl import to_mermaid`.

`skye new` refuses to overwrite a file unless you pass `--force`. The text it prints passes `skye check`; it starts with front matter
(`title` is the block name, `version = "0.1.0"`) and the lines to edit, the `description` among them, are marked `CHANGE ME`. `.gitattributes` maps `*.skye` to HCL so that GitHub highlights the files.

### The Claude skill

The package ships a skill for Claude Code that teaches a model the `skye` command, the `.skye` language and the rules of the library.

```bash
skye skill install                    # copies it to ~/.claude/skills/skye/
skye skill install --scope project    # ... or to ./.claude/skills/skye/
skye skill install --dir DIR          # ... or to DIR/skye/
skye skill install --force            # replace files that differ (for example after upgrading the package)
skye skill print [NAME]               # print SKILL.md, or references/NAME.md; skye skill path shows where it is installed
skye skill status                     # up to date, outdated (the package changed) or edited by hand; exit 1 if not up to date
```

After you upgrade the package, `skye skill status` tells you whether the installed copy is behind; `skye skill install` brings it up to date
when nobody edited it (the installer keeps a record of what it wrote in `.skye-skill.json`), and keeps a file you edited unless you pass `--force`.

The skill has the official layout of a Claude skill: a minimal `SKILL.md` that says what to do first and which reference to read, and one
small file per topic in `references/` (`cli`, `language`, `router`, `flow`, `prompt`, `python-api`, `rules`), so a model loads only what the
task needs. The folder is `src/skye/utils/claude_skill/skye/`; its `evals/` folder (`evals.json`, `trigger_evals.json`) holds the test
prompts and is not installed. The files are updated in the same change as the command line, the grammar, the public API or the rules, and a
test fails when one names something that does not exist or shows an example that does not pass `skye check`.

## Writing `.skye` from objects

Skye can also write a model back as `.skye` text: `ModelRouter.to_skye(name)` for a router, `Flow.to_text()` for a flow, and
`skye.dsl.to_text(spec_or_document)` for any spec or a whole document. The text
passes `skye check` and builds an equal model again; defaults are left out and comments are not kept. To tidy a file you wrote, use `skye fmt`
instead: it works on the text, so comments, `"""` strings and the front matter stay (two spaces per open bracket, no trailing spaces, at most
one blank line in a row, exactly one after the front matter), and it refuses to write a result that would build differently. `skye fmt
--check` lists the files that are not formatted (exit 1), for CI. With no path it formats every `.skye` file under the current folder (a folder argument is searched the same way; hidden
folders, `node_modules`, `venv`, `build` and `dist` are skipped); `--exclude GLOB` and a `.skyeignore` file (one glob per line, relative to the
folder searched) leave paths out. A router built in Python or by an older program can be moved to a file:

```python
from pathlib import Path

from skye.router import ModelRouter

router = ModelRouter({"fast": ["openai/gpt-4o-mini", "anthropic/claude-haiku"]})
Path("router.skye").write_text(router.to_skye("main"), encoding="utf-8")     # the router block
config = router.to_config()                                                    # or the dictionary that from_config_dict reads
```

**Secrets are not written.** A key written as `env.NAME` (or `${NAME}`) comes back as `env.NAME`; a key that was given in clear is left out and the
target reads its provider's standard variable (`OPENAI_API_KEY`, ...); pass `include_secrets=True` to write it, for example to a private file.
Only the retry and cooldown policies that differ from the defaults are written, and a route's strategy only when it differs from the router's.

## Loading from Python

```python
import skye
from skye.flows import Flow                      # also skye.Flow
from skye.router import ModelRouter

document = skye.load("app.skye")                  # the Document: routers, flows, prompts; ConfigurationError if the file has mistakes
router = ModelRouter.from_file("app.skye", name="main")
flow = Flow.from_file("app.skye", name="research", registry={"planner": planner})   # `registry.NAME` must be a key of the dictionary
flow.check()                                      # the mistakes now (empty when valid); flow.to_text() writes the block back
```

`skye.load(path, *, registry_names=None)` raises a `ConfigurationError` that lists every mistake as `file:line:column reason fix`. `name` is
optional when the file holds one block of the kind. `Flow.from_text(text, name=None, registry=None, filename=None)` reads a text.
**Running a flow is not built yet:** `flow.run(...)` raises `NotImplementedError` (see [Status and roadmap](../project/roadmap.md)).
There is no `skye.Router`: use `ModelRouter`.

## Loading is cached

Parsing and checking is the costly part of reading a `.skye` file (2 to 6 ms for a real file), so it is done once per process. The
built document is kept in a bounded in-memory cache keyed by the SHA-256 of the text; `skye.load(path)` and the router loader also skip
the read when the file's modification time and size did not change, and keep the document when the time changed but the hash did not.
A cached document is **read-only** and shared. Nothing depends on the cache for correctness: a new process parses once. From
Python, `skye.dsl.build_cached(text)` is `build` through the same cache, `skye.dsl.load_document(path)` reads a file through it and
returns the document with its diagnostics (where `skye.load` raises), and `skye.dsl.clear_cache()` forgets the cached documents. The result is
not kept on disk: it would save about 5 ms per cold container and add a second file to keep consistent.

## See also

- [The .skye language](../concepts/skye-language.md): the overview, with one example per block.
- [CLI reference](cli.md): `skye check`, `fmt`, `render`, `new`, `prompt`, `skill`.
- [Editor support](editor.md): the VS Code extension.
- [skye.dsl](api/dsl.md): `build`, `build_cached`, `clear_cache`, `load_document`, `check_text`, `format_text`, `to_text`,
  `to_mermaid`, `Diagnostic`, `FormatError`, `SkyeSyntaxError`.
