---
title: "Write a prompt in .skye"
status: current
---

# Write a prompt in .skye

This guide shows you how to write a prompt as a `prompt` block of a `.skye` file, check it, render it into messages from Python and
send them to a model. It also shows the prompts that ship with Skye.

## What you need

- `pip install skyeai`. Prompts are part of the base install: the template engine is the standard library's, with no Jinja2.
- A text editor; [editor support](../../reference/editor.md) adds highlighting and checks for `.skye` files.

## Step 1: write the prompt

A prompt declares its variables, then lists its messages in order, each with a real role. This file holds one prompt, `greeting`:

```skye
--8<-- "examples/prompts/basic_rendering.skye"
```

The parts of the file:

- **Front matter** between the two `---` lines: `title`, `description`, `version`, `tags`. It is optional; `skye prompt info` and
  `describe_prompt` show it, the renderer ignores it.
- **`prompt "greeting"`**: one prompt. A file may hold several, each with its own name.
- **`variables`**: each variable has a type (`string`, `number`, `bool`, `list`, `map`, or a shape such as
  `list({ role = string, text = string })`). A default in parentheses (`string("")`) makes it optional; without one it is required.
  The string after the type is a description for people, never sent to the model.
- **`message "system"`**, **`message "user"`**, **`message "assistant"`**: one message each. `text` may appear several times in a
  message; the parts are joined with a newline.
- **`when note { ... }`**: a part that appears only when `note` is set and not empty. `when not x` is the opposite.
- **`{{ name }}`**: puts the value of a variable in the text. See [Variables and filters](variables-and-filters.md).

Two more blocks place content that comes at render time:

- **`placeholder "history"`** marks where the earlier turns of a conversation go.
- **`each item in items { ... }`** repeats its body for every item of a list; inside it `loop.index`, `loop.first`, `loop.last` and
  `loop.length` are defined. A `message` inside an `each` gives one message per item, and its role may come from data
  (`message turn.role { ... }`).

```skye
--8<-- "examples/prompts/message_roles.skye"
```

An `output` block declares the shape of the answer; [Output schema](output-schema.md) covers it.

## Step 2: check and format it

```bash
skye check prompts.skye      # every mistake, with line, column and a fix; exit 1 when there is one
skye fmt prompts.skye        # rewrite in the standard layout, keeping comments
```

The checker knows the language: an undeclared variable in `{{ }}`, an unknown type, a role that is not `system`, `user` or
`assistant`, or a `{% %}` tag are errors with the line that holds them. From Python, `skye.dsl.check_text(text)` returns the same
diagnostics.

## Step 3: render it from Python

`load_prompt(text, name)` builds one prompt of a `.skye` text; `render_prompt(spec, variables, history=...)` returns the messages.
`history` maps each placeholder name to its messages, as message objects or as `{"role", "content"}` dictionaries.

```python
--8<-- "examples/prompts/message_roles.py"
```

You can also load a whole file once with `skye.load(path)`, which checks it and keeps the parsed result while the file does not
change, then pick a prompt with `document.prompt("trip")`.

The other way is a [`BasePromptBuilder`](../../reference/api/prompts.md): you register prompt files under a name and render by name.
The builder adds defaults shared by every render, partial builders and few-shot examples.

```python
--8<-- "examples/prompts/basic_rendering.py"
```

A missing required variable raises `ValidationError` (a `ValueError`) whose message starts with `Missing required variable` and
names every missing one. A value that does not match the shape of a structured variable raises `ValidationError` listing each
mistake by path (`notes[0].text: missing`).

## Step 4: send the messages to a model

The result is a list of `SystemMessage`, `UserMessage` and `AssistantMessage` objects, which any client takes as they are:

```python
import os
from pathlib import Path

import skye
from skye.prompts import load_prompt, render_prompt

spec = load_prompt(Path("prompts.skye").read_text(encoding="utf-8"), "greeting")
messages = render_prompt(spec, {"name": "Alice", "product": "Skye"})

client = skye.provider("openai", api_key=os.environ["OPENAI_API_KEY"])
response = client.complete(messages=messages, model="gpt-4o-mini")
print(response.content)
```

A [router](../routing/aliases-and-fallbacks.md) takes the same list: `router.complete(messages=messages, model="fast")`.

## Use a bundled prompt

Skye ships 11 prompts written in `.skye`: the task prompts `text_classification`, `text_explanation`, `text_question_answering` and
`text_summarization`, the extraction prompts `extraction_entities`, `extraction_relations`, `extraction_structured` and `extraction_table`, the
generation prompts `generation_code` and `generation_sql`, and the ReAct agent prompt `agent_react`. A `BasePromptBuilder()` loads them all. The
other prompts written for Skye (chat, tool, planner, procedure, reasoning, supervisor, group chat, memory upkeep and more) are a
[gallery of files to copy](https://github.com/ggiallo28/skye/tree/main/examples/prompts/catalogue): they are not installed, you copy one next to your
code and change it, or register it from its path with `register_template(name, path, from_string=False)`. A prompt joins the package when a part of
the library needs it.

```bash
skye prompt list                      # name, title, version and description of each bundled prompt
skye prompt info text_classification       # its inputs, history placeholders, messages and output
skye prompt info prompts.skye --name greeting   # the same for a prompt of your own
```

`skye prompt info` prints each input with its type, `required` or its default, and its description; `--json` prints the same as
data. From Python, `describe_prompt(spec, metadata)` returns it as a `PromptInfo`, and `prompt_help(spec, metadata)` as text.

```python
from skye.prompts import BasePromptBuilder

builder = BasePromptBuilder()
messages = builder.render("text_classification", {
    "text": "The app crashes when I upload a photo.",
    "categories": [{"name": "bug"}, {"name": "question"}, {"name": "feature request"}],
})
print(builder.help("text_classification"))
```

A prompt of your own that shares parts with other files (`include`, `from ... import`, `use`, see the [language reference](../../reference/skye-language.md))
is registered from its path: `builder.register_template("chat", "prompts/chat.skye", from_string=False)` reads the files it includes from
the folder of `chat.skye`. A text has no folder, so `register_template("chat", text, resolver=my_resolver)` takes the function that reads them.

Every bundled prompt that takes tools or memories declares them with the same shapes, and the conversation history is always the
placeholder `history`. The sample variables of every bundled prompt, the ones of a call that renders, are in `examples/prompts/bundled/`
(one JSON file each; `examples/prompts/bundled_templates.py` renders them all), and `skye prompt export DIR` writes the prompts out to edit.

## What you get

A prompt that lives in a file next to your code, checked before it runs, with typed inputs that `skye prompt info` documents, and
rendered into messages with real roles for any provider.

## See also

- [Variables and filters](variables-and-filters.md), [Few-shot examples](few-shot.md), [Output schema](output-schema.md)
- [The `prompt` block in the .skye language reference](../../reference/skye-language.md#prompt) and the
  [`skye.prompts` API reference](../../reference/api/prompts.md)
- Examples: [examples/prompts](https://github.com/ggiallo28/skye/blob/main/examples/prompts/README.md), in reading order
