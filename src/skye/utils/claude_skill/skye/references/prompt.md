# Prompts

A prompt block declares its variables and builds messages with real roles. Conditions and loops are blocks (`when`, `each`), not template
tags; only `{{ name }}` (with the filters of the template engine) appears in the text.

```skye
prompt "chat" {
  variables = { persona = string("a helpful AI assistant"), domain = string(""), guidelines = list(string, []), user_message = string }

  message "system" {
    text = "You are {{ persona }}."
    when domain { text = "Specialized in {{ domain }}." }
    when guidelines {
      text = "Please follow these guidelines:"
      each guideline in guidelines { text = "- {{ guideline }}" }
    }
  }

  placeholder "history"                     # the conversation history is inserted here at run time

  message "user" { text = "{{ user_message }}" }
}
```

## Rules

- `variables = { name = type }` or `name = type(default)` (`string`, `number`, `bool`, `list`, `map`; `list([])` is an empty default). A
  variable without a default is required. `allow_missing = ["name"]` lists variables the caller may leave out.
- Describe a variable with a string right after its type: `task = string "What the agent must achieve"`,
  `phase = string("plan") "plan, execute or replan"`. `skye prompt info` shows it (not sent to the model). Not a `#` comment.
- **Structured variables** take the field syntax of `output`: `tags = list(string)`, `owner = map({ team = string, email = string("") })`,
  `categories = list({ name = string "Name", description = string("") "What it means" })` (or `[string]`, `[{ ... }]`, `{ ... }`).
  A field with a default is optional. The variable is required; for an empty default put it after the shape: `list({ ... }, [])`
  (not `list([])`, which loses the shape). `render_prompt` checks the value (`categories[1].name: missing`) and fills field defaults.
  In Python a `VariableSpec` holds the shape in `item_type` and `fields`.
- **Shared shapes** (the prompts of the package and of the gallery; reuse them, with a description on each field): `tools = list({ name = string, description = string,
  parameters = map({}), returns = string("") }, [])`; `persona_memory` and `semantic_memory` = `list({ content = string, source = string("") }, [])`;
  `episodic_memory` adds `timestamp = string("")`; `procedural_memory = list({ name = string(""), content = string(""), steps = list(string, []) }, [])`;
  `working_memory = list({ content = string }, [])`. Conversation history is always `placeholder "history"`, never a variable: `chat_history`,
  `conversation_history`, `declarative_memory`, `procedural_memories` and `procedures` are removed (no aliases).
- Comments: `/** ... **/` documents, `#` a short note, never a plain `/* */`. End each teaching file `examples/prompts/*.skye` with `/** Example: builder.render("name",
  {...}) **/`, the dict in Python literals only and valid for the declared types (a test renders it in every example file); the bundled and gallery prompts carry no comment and keep their sample variables in `examples/prompts/bundled/` and `examples/prompts/catalogue/`.
- Before calling a prompt you did not write, run `skye prompt info NAME|FILE` (cli.md) or `BasePromptBuilder().help(name)` (python-api.md).
- `message "role" { ... }`: the roles are `system`, `user` and `assistant`. A role can come from data: `message turn.role { ... }` inside `each`.
- Inside a message, `text = "..."` may appear several times, interleaved with `when` and `each` blocks; the parts are joined in order, one per line.
  Variables are written bare (not `context.x`); one that is not declared is an error.
- Inside `each`, `loop.index` (from 1), `loop.index0`, `loop.first`, `loop.last`, `loop.length` exist. An `each` over a map gives entries
  `{key, value}`: `each entry in data { text = "{{ entry.key }}: {{ entry.value }}" }`. There is no `each key, value in ...` and no `.items()`.
- A list on one line (each `text` is its own line): `{{ tools | map('name') | join(', ') }}`.
- **Convert a Jinja template**: `{% if x %}` becomes `when x { text = "..." }`, `{% for x in xs %}` `each x in xs { ... }` (`.items()`: `each entry in d`),
  `[SYSTEM]` / `[USER]` `message "system"` / `message "user"`. Do not leave `{% %}` tags in the text. A plain-text template on
  `BasePromptBuilder` is interpolation only too: `register_template` rejects a `{% %}` tag (`ValidationError` with the line).
- Tool parameters in an agent prompt are shown as JSON Schema: `text = "Parameters: {{ tool.parameters | tojson }}"`, never one line
  per parameter.

## The answer format: `output`

To get JSON, a table or XML back (or to let a variable choose the shape with conditional outputs), read
[output.md](output.md): an `output` block generates the instructions, never write the schema by hand in a `text`.

## From Python

```python
from skye.prompts import load_prompt, render_prompt, PromptRunnable

spec = load_prompt(open("prompts.skye").read(), "chat")      # ValidationError with the diagnostics if the file has mistakes
messages = render_prompt(spec, {"user_message": "Hi"}, history={"history": past_messages})
```

`render_prompt` returns `SystemMessage` / `UserMessage` / `AssistantMessage` objects with real roles. A missing required variable
raises `ValueError` naming every missing one. A `placeholder "name"` takes `history["name"]` (or the variable `name`). `PromptRunnable(spec)`
wraps a prompt as a `Runnable` (`invoke(variables)` returns the messages). `BasePromptBuilder().render("text_summarization", {...})` renders the bundled
`.skye` templates the same way. `output_instructions(spec, variables)` (from `skye.prompts`) returns the text of the `output` block alone;
`builder.set_output_schema(name, MyDataclass, output_format="table")` does the same for a dataclass or a JSON-schema dict (`"json"` by
default). For a native provider call use `render_parts(spec, variables)` (or `builder.render_parts(name, variables)`): it returns a
`PromptParts` (system text apart, messages, the `json` output as an `OutputSchema`, the instructions as `fallback_text`, not appended
to the messages) for `client.complete(parts, model=...)`. `output_json_schema(spec, variables)` is the JSON Schema of the `output` block.
`builder.register_filter("money", fn)` adds a filter for every template of the builder.

## Not available yet (version 2)

A native `examples { ... }` block, multimodal `content`, and `from` / `bind` / `parts` / `separator` (partial and composed prompts) are rejected with
"not available in this version". Say so and keep that part in Python: `builder.add_examples(name, examples)` writes each example
from its own keys (`Question: ...` / `Answer: ...`), `example_template=` chooses the layout (a missing key is a `ValidationError`), and
`as_messages=True` gives user/assistant message pairs (`input`/`output`, else the first and the last key).
