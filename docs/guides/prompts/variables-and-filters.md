---
title: "Variables and filters"
status: current
---

# Variables and filters

This guide shows you how to declare the inputs of a `.skye` prompt, give them defaults, put their values into the text with
`{{ }}`, transform them with filters and add filters of your own.

## What you need

- A prompt in a `.skye` file (see [Write a prompt in .skye](write-a-prompt.md)).

## Step 1: declare the variables

Every value a prompt reads is declared in `variables`, with a type and, when it is optional, a default in parentheses. A string after
the type describes the variable for people (`skye prompt info` shows it); the model never sees it.

```skye
prompt "ticket" {
  variables = {
    customer = map({ name = string, plan = string("free") })  "Who opened the ticket"
    tags     = list(string, [])                                "Labels on the ticket"
    body     = string                                          "The ticket text"
    order    = map({})                                         "The order, as data"
    tone     = string("neutral")                               "How to answer"
    urgent   = bool(false)                                     "True for a paying customer who is blocked"
  }

  message "system" {
    text = "You answer support tickets in a {{ tone }} tone."
    when urgent { text = "This ticket is urgent: answer first with a workaround." }
  }

  message "user" {
    text = "Customer: {{ customer.name | title }} (plan {{ customer.plan | upper }})"
    text = "Labels: {{ tags | join(', ') | default('none', true) }}"
    text = "Order: {{ order | tojson }}"
    text = "{{ body | trim }}"
  }
}
```

| Declaration | Meaning |
|---|---|
| `body = string` | Required string |
| `tone = string("neutral")` | Optional, `"neutral"` when not given; also `number(100)`, `bool(false)` |
| `tags = list(string, [])` | Optional list of strings, empty by default |
| `customer = map({ name = string, plan = string("free") })` | Required map with a shape: `name` required, `plan` optional |
| `order = map({})` | A plain map with an empty default, any keys |

A variable with a shape is checked at render time: a missing field or a value of the wrong type raises one `ValidationError` that
lists every mistake by path (`customer.name: missing`). A missing optional field gets its default in a copy; your data is never
changed.

## Step 2: interpolate with `{{ }}`

`{{ name }}` writes the value of a variable. Inside the braces you can use:

- dotted access to a field of a map or an object: `{{ customer.name }}`, or `{{ data['key'] }}`;
- the loop variables inside an `each`: `{{ loop.index }}`, `{{ item.text }}`;
- literals, comparisons, `and`, `or`, `not`, and the conditional form `{{ 'Block' if strict else 'Comment' }}`;
- filters, after a `|`, one after the other.

The checker accepts only names that are declared (or loop variables): `skye check` reports `variable "b" is not declared. Declared:
a, strict.` with its line and column. A value of `None` writes nothing.

For whole parts that appear or repeat, use blocks instead of expressions: `when urgent { ... }`, `when not urgent { ... }` and
`each item in items { ... }`.

!!! note "No `{% %}` tags"
    A `.skye` prompt has no `{% if %}` or `{% for %}` tags: `skye check` rejects them (`control tags "{% %}" are not used in a prompt
    block. Use a when or each block.`). A plain-text template registered on `BasePromptBuilder` does interpolation only too:
    `register_template` rejects a tag with a `ValidationError` that names the tag and its line, and every variable it reads is
    required unless it has a default, is allowed missing or goes through `default(...)`.

## Step 3: use the built-in filters

| Filter | Example | Result |
|---|---|---|
| `upper`, `lower`, `title`, `capitalize` | `{{ plan | upper }}` | `FREE` |
| `trim` | `{{ body | trim }}` | the text without leading and trailing spaces |
| `replace(old, new)` | `{{ name | replace('_', ' ') }}` | `ada lovelace` from `ada_lovelace` |
| `join(sep)` | `{{ tags | join(', ') }}` | `billing, login` |
| `map('field')` | `{{ tools | map('name') | join(', ') }}` | one field of each item |
| `length` (or `count`) | `{{ tags | length }}` | `2` |
| `first`, `last` | `{{ steps | first }}` | the first item |
| `default(value)` | `{{ note | default('none') }}` | `none` when `note` is not defined |
| `default(value, true)` | `{{ tags | join(', ') | default('none', true) }}` | `none` when the value is empty too |
| `int`, `float`, `string`, `list` | `{{ count | int }}` | a conversion |
| `tojson` | `{{ order | tojson }}` | `{"id": 7, "items": ["lamp"]}` |
| `toxml(root)` | `{{ order | toxml('order') }}` | the value as XML under `<order>`, text escaped |
| `totable` | `{{ rows | totable }}` or `totable(['name', 'price'])` | a list of maps as a Markdown table |

`tojson`, `toxml` and `totable` put data into the prompt. To ask the model to answer in one of those formats, use an `output` block
instead (see [Output schema](output-schema.md)).

## Step 4: give defaults from Python

Besides the defaults written in the file, you have three ways to fill variables when you render:

- **`allow_missing`** in the prompt lists required variables that may be left out; they write nothing:

    ```skye
    prompt "note" {
      variables     = { author = string, text = string }
      allow_missing = ["author"]
      message "user" { text = "{{ text }} ({{ author }})" }
    }
    ```

- **`builder.set_default_values({...})`** on a `BasePromptBuilder` applies to every render of that builder. A callable value is called
  at each render, and `${NAME}` in a string is replaced by the environment variable.
- **`builder.partial(name=value)`** returns a new builder with some variables fixed; the original is unchanged.

```python
--8<-- "examples/prompts/basic_rendering.py:24:31"
```

## Step 5: add a filter of your own

A filter is a function that takes the value (and the arguments written in parentheses) and returns the new value. Pass it to
`render_prompt` with `filters=`:

```python
from pathlib import Path

from skye.prompts import load_prompt, render_prompt


def money(value, currency="EUR"):
    return f"{float(value):,.2f} {currency}"


spec = load_prompt(Path("invoices.skye").read_text(encoding="utf-8"), "invoice")
messages = render_prompt(spec, {"total": 1234.5}, filters={"money": money})
```

In the prompt you write `{{ total | money }}` or `{{ total | money('USD') }}`. To use a filter in every prompt of every builder, add it
as a plugin with the decorator `@plugins.template_filter("money")` on the function (after `plugins = skye.Plugins()`): it is there as
soon as the decorator runs, with no line of setup, and it applies to text templates too. To keep a filter local, register it on one
`BasePromptBuilder` with `builder.register_filter("money", money)`. `PromptRunnable(spec, filters={...})` takes them too.

`skye check` does not know your filters, so it accepts any name after `|`. An unknown filter fails at render time with
`Unknown filter: 'money'`: render your prompts in a test.

## What you get

Typed inputs with defaults that `skye prompt info` documents, text built from them with filters, and errors that name every missing
or malformed variable before a request reaches the model.

## See also

- [Write a prompt in .skye](write-a-prompt.md), [Few-shot examples](few-shot.md), [Output schema](output-schema.md)
- [The `prompt` block in the .skye language reference](../../reference/skye-language.md#prompt)
- [`skye.prompts` API reference](../../reference/api/prompts.md)
- Examples: [plugins/template_filter.py](https://github.com/ggiallo28/skye/blob/main/examples/plugins/template_filter.py) (filters as plugins),
  [control_flow.py](https://github.com/ggiallo28/skye/blob/main/examples/prompts/control_flow.py) with
  [control_flow.skye](https://github.com/ggiallo28/skye/blob/main/examples/prompts/control_flow.skye) (`when`, `each`, filters) and
  [basic_rendering.py](https://github.com/ggiallo28/skye/blob/main/examples/prompts/basic_rendering.py) (defaults and partials)
