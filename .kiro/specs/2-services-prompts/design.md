Builds on: #[[file:.kiro/steering/11-design.md]] (sections: Layers, Allowed imports, Ports, The `.skye` language, Extras and budgets)

# Design Document: prompts

## Overview
`prompts` is the services layer-2 component (codename cirrus). It implements the `PromptBuilderInterface` Port of `base`: versioned
templates, variable injection, few-shot examples, message roles, multimodal content and output schemas, returning `SkyeMessage`
objects that every provider accepts. It follows the liteprompt design (loaders, role-based messages, registry, truncation) with a
standard-library template engine and needs no third-party library and no extra (Requirement 13; D20; Requirement 34.1). The prompt
text can also be written as a `prompt` block of the `.skye` language (D60). This document describes only the internals of `prompts`;
the layer, the allowed imports (`prompts` imports only `base`), the Ports and the extras policy are in the steering sections named
above and are not restated here. `tools` never imports `prompts` (D17).

It supersedes the design of the former `prompts-support` spec (a `Jinja2PromptBuilder` over a Jinja2 environment, pydantic
configuration models, an optional extra `skyeai[prompts]`). That design is recorded as history at the end of this file.

## Architecture
The package is small on purpose: one builder that holds the state, one engine that renders text, one loader that discovers the
bundled templates. Everything else the old design split into classes is a method or a private helper of the builder, because the
builder is the only caller (no second implementation of the Port exists).

| File | Role |
|---|---|
| `prompts/engine.py` | Standard-library template engine, interpolation only (D76): `{{ expr }}` (names, attributes, comparisons, the conditional expression `a if c else b`), `{# comment #}`, whitespace control with `{{-`/`-}}`, the built-in filters (`join`, `upper`, `lower`, `title`, `capitalize`, `trim`, `length`, `default`, `string`, `list`, `first`, `last`, `int`, `float`, `replace`, `tojson`, `toxml`, `totable`, `map`) and filters added by the caller. A `{% %}` control tag raises `TemplateSyntaxError` naming the tag and its line (`line` attribute) and pointing to `when` and `each`. An undefined variable stays visible and is falsy. Nothing is evaluated with `eval`. Realizes Requirement 30.8 and 30.9. |
| `prompts/messages.py` | `BasePromptBuilder`: registry (`name:version`), variable merge, examples, role sections, content and schema configuration, metadata and validation. Re-exports the message types for peers. |
| `prompts/loaders.py` | `load_default_templates(builder)`: reads the files of `prompts/templates/` and registers them as version `1.0`. |
| `prompts/skye_prompts.py` | The `.skye` renderer: `load_prompt`, `render_prompt` (a `PromptSpec` plus variables gives `SkyeMessage`s with real roles), `render_parts` (the same as a `PromptParts`, D81, D101), `output_json_schema` and `PromptRunnable` (the `Runnable` a flow step `run = prompt.NAME` will reach once the flow runtime exists). |
| `prompts/templates/` | The bundled prompts, all `.skye`: the shared parts in `common/` and 11 prompts (`text_*`, `extraction_*`, `generation_*` and `agent_react`). The other 26 prompts, among them the agent prompts of "Agent prompts" below, are a gallery in `examples/prompts/catalogue/` since 2026-11-13 (D118), not installed. |

Flow of one rendering: look up the latest (or the given) version, extract the variable names, merge defaults, partial variables and
provided variables (the provided ones win, callable defaults are called at each rendering, Requirement 30.4), inject the selected
examples, render with the engine, split the text into role sections, create one message per section (a `UserMessage` when no role is
given, Requirement 32.1).

## Components and Interfaces
### Registry and variables (Requirement 29, 30.1 to 30.6)
`register_template(name, template, version="1.0", from_string=True)` stores the text under `name:version`; a file path with
`from_string=False` raises `FileNotFoundError` with the path. `get_template` returns the latest version or the exact one and raises
`KeyError` for a missing template. A missing required variable raises `ValueError` naming the variable, unless it is in the
allowed-missing set. `partial(**vars)` returns a new builder with those variables bound and leaves the original unchanged.
`compose_templates(name, parts, separator)` joins registered templates into a new one (Requirement 30.7). Version ordering is the
string order of the version (assumption: kept as it is, not changed here).

### Examples (Requirement 31)
`add_examples(name, examples, example_template=None, *, as_messages=False)` stores the examples (D79, Requirement 31.6 to 31.8):
with no example template each example is written from its own keys, one `Key: value` line per key in order (`user_query` gives
`User query`, a list or map value is JSON); with an example template every key it reads (not through `default`) must be in every
example, else `add_examples` raises `ValidationError` with the index of the example and the missing keys; with `as_messages=True`
each selected example becomes a `UserMessage` and an `AssistantMessage` (`input`/`output` when both exist, else the first and the last
key; fewer than two keys is a `ValidationError`), inserted before the last user message, and `examples` is not passed as a variable.
`set_example_selector(name, type, max_examples)` chooses `fixed` or
`random` or `semantic` (similarity, with an embedder callable passed in, never an import of `models`); one default limit (`DEFAULT_MAX_EXAMPLES`) serves with and without a selector (tasks 3.1, 3.2). For a `.skye` prompt that declares `examples` as a list, `add_examples` passes the selected list of dictionaries and not a formatted string; a prompt that declares `examples = string` still gets formatted text (D74, Requirement 31.5).

### Roles and placeholders (Requirement 32.1 to 32.3)
A rendered text is split into sections at the markers `[SYSTEM]`, `[USER]`, `[ASSISTANT]` (today a text convention). The `.skye`
`prompt` block replaces the markers with real `message "<role>"` blocks (D60). An unknown role raises a validation error. `add_message_placeholder` marks where a conversation history is inserted (at the marker line, or before the last user message); in a `.skye` prompt `placeholder "history"` does it (tasks 3.3, 4.2).

### Multimodal content (Requirement 32.4 to 32.6)
`add_image_content` and `add_multimodal_content` record which variables carry content and of which kind. The messages are built with
the typed content blocks of `base` (D46), not with provider-specific dictionaries. Images (URL, base64, file path) go to `UserMessage.images`, a bad URL or format raises a validation error that lists the supported ones, and content types are recorded. Audio, video and files are only recorded: the typed blocks of D46 do not exist in `base` yet, so task 3.4 stays open (Requirement 32.7).

### Output schema (Requirement 33)
`set_output_schema(name, schema)` takes a dataclass or a JSON-schema dictionary (D24: no pydantic) and `get_output_instructions`
returns the text for the model, or an empty text without a schema. A dataclass and a dictionary both give instructions that name every field, and an invalid schema raises a validation error (task 3.5).

The `.skye` output block (D70, Requirement 33.5). A prompt declares the shape of the answer once, and nobody writes the
structure by hand: `output "json" | "table" | "xml" { field = type, ... }` (no label is `json`), or `output "<format>" { schema = VAR }`
to read the fields from a declared `map` variable at render time. `base` parses and checks it into `OutputSpec` (`format`, `fields`
of `OutputFieldSpec`, `schema_from`) in `PromptSpec.output`; `to_text` writes it back. This component renders it:
`prompts/output_format.py` turns the fields into a JSON Schema (`required` = the fields without a default, `default` kept) and the
schema into the text of the format (json: "Answer with a single JSON object and nothing else.", the schema in a fenced block and a
one-line example; table: the header and separator rows and one line per column with its type, scalar columns only; xml: a skeleton
whose root is the prompt name in snake_case, lists as repeated `<item>`, the type as the text of each leaf).
`skye.prompts.output_instructions(spec, variables)` returns it and `render_prompt` appends it as the last text of the last user
message (a new user message when there is none). The builder reuses the same writer: `set_output_schema(name, schema,
output_format="json")` keeps today's JSON text for `json` and uses the `table` / `xml` text otherwise (the Port has the same
parameter), and `get_output_instructions(name, variables=None)` returns the `.skye` block's text when no schema was set. The engine
filters `toxml` and `totable`, next to `tojson`, are for the other direction: putting data into a prompt.

Prompt parts (D81, D101, Requirement 33.9). The names are `render_parts` and `PromptParts`. `PromptParts` and `OutputSchema` are
frozen dataclasses in `base` (`skye/base/prompt_parts.py`), exported by the `prompt` Port module and re-exported by `skye.prompts`.
`skye.prompts.render_parts(spec, variables, *, history=None, filters=None)` renders like `render_prompt` but does not append the
output instructions: the system messages become `system` (joined with a blank line), the other messages stay in order, the active
`json` output block becomes `OutputSchema(name, schema)` (the prompt name with every character outside letters, digits, `_` and `-`
replaced by `_`), and its instructions become `fallback_text`; a `table` or `xml` output gives only `fallback_text`.
`BasePromptBuilder.render_parts(name, variables)` does the same for a registered template, with the schema of `set_output_schema` (a
`json` one) or of the `.skye` block, named after the template. The Port `PromptRenderingInterface.render_parts` is concrete: its
default splits the system messages out of `render` and has no output, so other builders keep working. `output_json_schema(spec,
variables)` gives the JSON Schema of the active block alone. The model side (`1-adapters-models` task 11) chooses native fields or the
fallback text.

Field descriptions (D70). A string right after a field's type is its description: `total = number "Total amount including VAT"`,
at every level (`list({ amount = number "Amount" }) "One entry per line"`) and in the comma form. The parser reads it only inside an
`output` block (`Attribute.description` / `MapEntry.description`; elsewhere a value followed by a string stays an error), the builder
puts it in `OutputFieldSpec.description` (an empty one is an error; `schema = VAR` takes none) and `to_text` writes it back, one field
per line in a map that has descriptions. The writer carries it to the model: json, the `"description"` of the property (right after
`"type"`, nested too); table, `- total: number — Total amount including VAT`; xml, `<total>number — ...</total>` for a leaf and an XML
comment after the opening tag of a list or map (`<lines> <!-- One entry per line -->`); the example line has none. In a
`schema = VAR` map a field may be `{"type": T, "description": "..."}` (a map with a `type` key and no key but `type`, `description`,
`items`, `properties`; `items` gives a list's item type, `properties` a map's fields). A dataclass field's
`metadata={"description": ...}` and a JSON-schema dictionary's own `description`s reach the table and xml text the same way.

Format from a variable (D70). `output VAR { ... }` (a bare name) takes the format from a declared `string` variable: the checker wants
it declared ("Did you mean"), of type string, and a default (if any) among json, table, xml; `OutputSpec.format_from` holds its name.
`output_instructions` resolves the value (or the default) at render time and raises `ValidationError` for a value that is not one of
the three, or for `table` with a list or map field (static fields too, since they cannot be checked at load time). The bundled prompt
`structured_output` uses it (`format = string("json")`, `output format { ... }`); the fixed-format `structured_output_json`, `_table` and `_xml`
were removed on 2026-11-13 (task 24.10 of `0-base-plugins`).

Conditional outputs (D70). An `output` block may also sit inside a `when` at the top of the prompt (or a `when` nested in one; never
inside a `message` or an `each`): the builder reads it into a `PromptPartSpec(kind="output", output=OutputSpec)` among the parts of
that `when`, with every check of the plain block; a prompt with an unconditional `output` and a conditional one is an error naming
both lines, and `schema = VAR` stays the only entry of its block. `PromptSpec.output` keeps the unconditional block;
`PromptSpec.output_variants()` lists every block with the conditions of its `when` blocks. `skye.prompts.active_output(spec,
variables)` evaluates the conditions (a missing variable takes its default) and returns the active block, `None` when none holds, or
raises `ValidationError` naming the conditions when more than one does; `output_instructions`, `render_prompt` and the builder's
`get_output_instructions` use it. `describe_prompt` puts the conditional blocks in `PromptInfo.outputs` (each `OutputInfo` with its
`condition`), and `prompt_help` / `skye prompt info` print one `Output (when <condition>): <format>` section per block. The four
bundled `structured_output*` prompts declare `schema = map({})` (optional) and end with
`when schema { output F { schema = schema } }` and `when not schema { output F { name = string "...", value = string "..." } }`,
so a call without `schema` asks for a `name` and a `value` per item, in json by default.

### Metadata and validation (Requirement 29.4 to 29.6)
`get_template_metadata` returns required and optional variables, examples, content types, roles and the schema; `validate_template`
returns a result without raising. The variable extraction and the syntax check use the engine's parser, so the names read in `{{ }}` are found and a bad template is rejected at registration with the engine's details (tasks 2.1, 2.2). Text templates do interpolation only (D76): a `{% %}` tag is rejected with a `ValidationError` that names the tag and its line (`details["line"]`) and points to `when` and `each` in `.skye`, and a variable read by interpolation is required unless it has a default (a builder default, a partial variable or the `default` filter) or is allowed missing (O39 lapsed with the tags).

Help for every kind of block (D83, Requirement 34.9): `describe(spec, metadata=None)` in `skye/base/dsl/info.py`, public in
`skye.dsl`, returns a `PromptInfo` for a prompt (as `describe_prompt`), a `RouterInfo` (routes with their targets as
`provider/model`, strategy and fallbacks) for a router and a `FlowInfo` (context fields as inputs, the start and one `NodeInfo` per
step, parallel or choice) for a flow, and raises `TypeError` for anything else. `skye.prompts` keeps `describe_prompt` and
`prompt_help`.

### The `.skye` renderer (version 1 and 2 of the `prompt` block)
What exists: the `prompt` block of version 1 is parsed and checked in `base` (`PromptSpec`: `variables`, `message "<role>"`, `text`,
`when`, `each`, `placeholder`, `allow_missing`) and can be written back. It is not rendered yet.

Version 1, to build in this component (`base` has no template engine): `PromptSpec` plus the variables gives a list of `SkyeMessage`
with real roles, a `placeholder` replaced by the history the caller passes, conditions and loops evaluated with
`skye.base.dsl.evaluate`, `{{ }}` rendered by `prompts/engine.py`; a missing required variable raises the `ValueError` of
Requirement 30.2, defaults and `allow_missing` as in 30.4. A flow step reaches it as `run = prompt.NAME`. The owner decided that the
whole of Jinja is not needed to start: the first thing built is the part an agentic workflow needs, the rest is version 2.

Version 2, measured on the 18 templates (what the language cannot say yet): `else` and `elif` for `when` (28 uses each, `elif` mostly
`X == "value"`); loop variables in `each` (`loop.index` 3 uses, `loop.last` 1 use, plus `first` and `length`; done by D69); a loop
over a dictionary (`for key, value in collected_data.items()`, 2 uses; done by D69 as `{key, value}` entries); a condition inside a line (20 lines in
11 files, for example `- {{ memory.content }}{% if memory.timestamp %} ({{ memory.timestamp }}){% endif %}`; options are a conditional
expression in `{{ }}` or an inline `when`); an inline loop with a separator (`agent_tool.jinja`; done by D69 with the filter `map`). Still version 2: `else`/`elif` and a condition inside a line (written today as `when not` chains and pairs of `when` blocks).
Measured again by the conversion (task 4.3): `else`/`elif` were written as `when not x` and `==`/`!=` chains in all 15
converted files (18 with the last three), and a condition inside a line as two `when` blocks (four for two conditions in `summarization`); both work but
are verbose. Two more needs: a falsy test of a missing key (`x.key` on a map without `key` is an error in an expression, falsy in
Jinja; written `"key" in x and x.key`), and a `when` that can test the history given to a `placeholder` (the old templates print a
"Recent conversation" heading only with history, so those prompts loop over a `chat_history` variable instead). The last three
(`agent_form`: `for key, value in collected_data.items()`; `agent_multimodal`: `loop.index`; `agent_tool`: an inline list with a
separator) were converted once D69 added, without new syntax, `loop.*` inside `each`, `{key, value}` entries when an `each` goes
over a map, and the engine filter `map(attribute)`. The equivalence test (task 4.4) lists the intended differences: real
roles, history as messages, whitespace, empty messages omitted, and lines the old templates glued together because an
`{% endif %}` swallowed the newline (`agent_memory_assistant`, `agent_memory_recall`, `sql_generation`, `extraction_relations`,
`extraction_table`). The old engine cannot render the legacy `{% %}` templates any more (D76), so their output for every case was
rendered once and frozen in `tests/unit/prompts/legacy_renderings/` (task 9.1); the test compares against those texts.
Already enough in the engine: the filters `default`, `join`, `upper`, nested `each`, attribute access (`table.columns`). Not to be
added (D20): macros, inheritance, include, variable assignment. `prompts/engine.py` keeps only `{{ }}` interpolation with filters
(D76, task 9.1); custom filters are registered with `register_filter` (D77).

### Agent prompts (written in `.skye`, 2026-11-08)
Bundled prompts written directly in `.skye`, all with the same optional inputs: `tools` (a list of `{name, description,
parameters, returns}`), the memory lists `episodic_memory`, `semantic_memory`, `procedural_memory`, `persona_memory`,
`working_memory` (a section per non-empty kind, nothing when all are empty), `system_prompt` to replace the role sentence, and a
`placeholder "history"`. Every agent prompt shows the parameters of a tool as its JSON Schema, `Parameters: {{ tool.parameters | tojson }}`
(D80, the four smolagents-style prompts converted in task 9.4). smolagents-style (`agent_smol_code`, `agent_smol_tool_calling`, `agent_smol_planning`, `agent_smol_managed`);
reasoning (`agent_reasoning_self_reflection`, `agent_reasoning_chain_of_thought`, `agent_reasoning_tree_of_thoughts`, `agent_planner`); supervisors
(`agent_supervisor_router`, `agent_supervisor_planner`, `agent_supervisor_reviewer`, `agent_supervisor_hierarchical`); shared conversation of several
agents (`agent_groupchat_participant`, which answers a pass token unless its triggers match or it is mentioned, `agent_groupchat_manager`,
which picks the next speakers, and `agent_groupchat_summarizer`); memory upkeep (`agent_memory_update`, `agent_memory_consolidation`, `agent_memory_working`, which return JSON operations a memory store applies). The older agent templates (`agent_code`, `agent_memory_assistant`, `agent_memory_recall`, `agent_procedure`, `agent_reasoning` and the three `.jinja` ones) take the same optional inputs, with their own variables kept. Their text is written for Skye (Requirement 14.3): smolagents
(Apache-2.0) and the other libraries were read for their structure only.

Note (2026-11-13, D118): of the agent prompts listed above only `agent_react` (the former `agent_smol_tool_calling`) is bundled; the others are in the gallery `examples/prompts/catalogue/` and come back into the library when a component uses them.

## Data Models
No class of the old design survives as a public type. The state of the builder is private dictionaries keyed by template name.
New public data structures (a template entry, a content configuration) are dataclasses, never pydantic (D24), and are added only
when a second caller needs them.

## Error Handling
Errors use the `SkyeError` hierarchy with context (`raise ... from e`). The Requirements fix the visible types: `FileNotFoundError`
with the path (29.1), `KeyError` for a missing template (29.2), `ValueError` naming a missing variable (30.2), a validation error for
bad syntax with the engine's details (29.3), for an invalid role (32.3), for an invalid content format that lists the supported
formats (32.6) and for an invalid schema (33.4). Validation of a template never raises (29.6). The engine's `TemplateSyntaxError` is a
`ValueError` and is wrapped with the template name. Logging is structured (message plus `extra`), not f-strings; the loader's
`print` calls move to the logger (task 2.4).

## Testing Strategy
Tests are in `tests/unit/prompts/` (engine, callable defaults) and `tests/unit/test_prompts_base.py` (builder); the example set is in
`examples/prompts/` and runs under `tests/examples` once rewritten (task 5). Property-based tests use Hypothesis where it is already
a dev dependency and stay optional.

## Correctness Properties
Carried over from the former plan, restated for the current design; each is checked by a test named in the task that owns it.
1. Registering then retrieving a template returns the same text for the same name and version (29.1, 29.2).
2. Variable merging: provided variables win over partial variables, which win over defaults; callable defaults are called per rendering (30.4).
3. Rendering the same template with the same variables gives the same messages when no random selector is used (30.1).
4. A fixed selector always returns the same examples; a random one never returns more than the maximum (31.3).
5. Each role section yields exactly one message of the matching type (32.1).
6. An invalid content format is rejected with the supported formats listed (32.6).
7. Composing templates equals joining their texts with the separator (30.7).
8. The output instructions are empty without a schema and name every field of the schema with one (33.1 to 33.3).
9. Metadata lists exactly the variables found in the template (29.5).
10. A partial builder leaves the original unchanged (30.6).
11. Rendering a `.skye` prompt and its old `.jinja` template gives the same messages after normalising spaces, apart from the real roles (D60; task 4.4).

## History: design of the former `prompts-support` spec (superseded)
Kept as a record; nothing below is a source of truth.
- A `Jinja2PromptBuilder` over a configured Jinja2 environment with macros, inheritance and includes. Superseded by D20 and Requirement 30.9.
- `TemplateRegistry` with an LRU cache of compiled Jinja2 templates, `VariableValidator` (using `meta.find_undeclared_variables`),
  `ExampleSelector` with fixed, random, semantic (embedding) and length-based strategies, `MessageFormatter`, `ContentHandler`,
  `SchemaValidator` as separate classes. Replaced by one builder (see Architecture); the strategies and the cache remain as tasks.
- `PromptBuilderConfig` and `Jinja2Config` as pydantic models, an exception family under `PromptBuilderError` (`TemplateNotFoundError`,
  `TemplateValidationError`, `VariableValidationError`, `ContentValidationError`, `SchemaValidationError`). Superseded by D24 and by the
  error types fixed in Requirements 29 to 33.
- An optional extra `skyeai[prompts]`. Superseded: the extra is empty (`known_empty` in `budgets.toml`).
- A `Pydantic` model as the output schema. Superseded by D24 (Requirement 33.1).
