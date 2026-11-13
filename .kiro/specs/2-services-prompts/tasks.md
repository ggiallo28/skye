# Implementation Plan: prompts

## Overview
Milestones in build order for the `prompts` component (codename cirrus): what exists first (builder, registry, engine, loaders),
then the gaps against Requirements 29 to 34, then few-shot, roles, content and schema, then the `.skye` prompts of decision D60, then
the stale examples and the licence notice. Status is judged from the code in `src/skye/prompts` and the tests in
`tests/unit/prompts` and `tests/unit/test_prompts_base.py`, not from the checkboxes of the former `prompts-support` plan, which
described a Jinja2 and pydantic design (see the history at the end of `design.md`). The former checkpoint tasks are dropped: they
produced nothing. Each task cites the steering requirement numbers it satisfies (`Requirement N.k` of `10-requirements.md`) or the
decision it honors. Task IDs cited from other documents are `prompts:N.k` (the former `prompts-support` task 3 is now
`prompts:5`, the former task 18 is now `prompts:4`).

## Tasks
- [x] 1. Builder, registry and engine (what exists)
  - [x] 1.1 Package structure and exports: `PromptBuilderInterface`, `BasePromptBuilder`
    - Evidence: `src/skye/prompts/__init__.py`; `tests/unit/test_exports.py`.
    - _Requirements: 34.2_
  - [x] 1.2 `BasePromptBuilder` implements the Port with a versioned registry (`name:version`), file registration and latest-version lookup
    - Evidence: `src/skye/prompts/messages.py`; `tests/unit/test_prompts_base.py` (`test_register_and_get_template`, `test_template_versioning`, `test_file_template_loading`, `test_nonexistent_template_error`).
    - _Requirements: 29.1, 29.2, 29.4_
  - [x] 1.3 Standard-library template engine (D20): `{{ }}`, `if`/`elif`/`else`, `for` with `loop.*`, filters, whitespace control, custom filters, no `set`/`macro`/`include`
    - Evidence: `src/skye/prompts/engine.py`; `tests/unit/prompts/test_engine.py` (includes `test_no_jinja_imports_in_prompts_package`).
    - _Requirements: 30.8, 30.9, 34.1; D20_
  - [x] 1.4 Defaults, callable defaults, allowed-missing variables and `partial`
    - Evidence: `src/skye/prompts/messages.py`; `tests/unit/prompts/test_callable_defaults.py`; `tests/unit/test_prompts_base.py` (`test_render_with_defaults`, `test_render_with_missing_allowed_variables`, `test_partial_binding`, `test_partial_with_callable`).
    - _Requirements: 30.3, 30.4, 30.6_
  - [x] 1.5 Role sections from the `[SYSTEM]`, `[USER]`, `[ASSISTANT]` markers, one message per section, `UserMessage` by default
    - Evidence: `src/skye/prompts/messages.py` (`_create_messages`); `tests/unit/test_prompts_base.py` (`test_role_based_messages`).
    - _Requirements: 32.1_
  - [x] 1.6 Fixed and random example selectors, example template, composition of templates
    - Evidence: `src/skye/prompts/messages.py`; `tests/unit/test_prompts_base.py` (`test_add_examples`, `test_custom_example_template`, `test_example_selectors`, `test_template_composition`).
    - _Requirements: 31.1, 31.3, 31.4, 30.7_
  - [x] 1.7 Loader for the bundled templates, sample templates and test data
    - Evidence: `src/skye/prompts/loaders.py`; `src/skye/prompts/templates/` (18 files); `tests/unit/prompts/test_data/`; `tests/unit/test_prompts_base.py` (`test_default_templates_work`, `test_agent_templates`).
    - _Requirements: 29.1, 29.4_

- [x] 2. Registry, variables and validation: close the gaps
  - [x] 2.1 Extract variables with the engine's parser, so `{{ name }}`, `if` conditions and `for` sources are found (today `_extract_variables` reads single braces)
    - Note: `src/skye/prompts/messages.py` `_extract_variables` uses the pattern `\{([^}]+)\}`; for a block template it returns expressions and not names, which also affects metadata and the required-variable check.
    - Evidence (2026-11-08): `_extract_variables` in `src/skye/prompts/messages.py` uses the engine parser; `tests/unit/prompts/test_builder_registry.py::test_block_variables_include_if_conditions_and_for_sources`, `test_metadata_lists_exactly_the_variables_found`. Since task 9.1 the first test is `test_block_variables_include_conditions_and_filter_operands` (no `if` or `for` left).
    - _Requirements: 30.5, 29.5_
  - [x] 2.2 Validate a template with the engine's parser: syntax errors with the engine's details at registration, validation results without raising
    - Note: `validate_template` counts braces; `register_template` does not parse the template.
    - Evidence (2026-11-08): `tests/unit/prompts/test_builder_registry.py::test_registration_rejects_bad_syntax_with_the_engine_details`, `test_validate_template_never_raises`.
    - _Requirements: 29.3, 29.6_
  - [x] 2.3 Raise `ValueError` naming every missing required variable for block templates too (today an undefined variable stays visible in the output)
    - Evidence (2026-11-08): `tests/unit/prompts/test_builder_registry.py::test_block_template_names_every_missing_variable_sorted`, `test_single_missing_variable_message`, `test_defaults_partials_and_allowed_missing_satisfy_requirements`. The rule for which variables are required lapses with the control tags (D76).
    - _Requirements: 30.2_
  - [x] 2.4 Errors in the `SkyeError` hierarchy with context, structured logging instead of `print` in `loaders.py`, `${VAR}` substitution in configuration
    - Evidence (2026-11-08): `tests/unit/prompts/test_builder_registry.py::test_defaults_substitute_environment_variables`, `test_missing_environment_variable_is_a_configuration_error`, `test_loader_logs_instead_of_printing`.
    - _Requirements: 34.3_
  - [x] 2.5 Compile at registration and reuse the compiled template; cache the variable list and the formatted examples; keep memory bounded for many templates
    - Note: `render_template` parses the text at every call; there is no cache.
    - Evidence (2026-11-08): `tests/unit/prompts/test_builder_registry.py::test_rendering_reuses_the_compiled_template`, `test_fixed_examples_are_formatted_once_and_cache_is_bounded`, `test_partial_shares_compiled_entries`.
    - _Requirements: 34.4, 34.5, 34.6_
  - [x] 2.6 Remove `register_jinja_macro` (macros are not supported) and rename `register_jinja_filter` to `register_filter` (D77, task 9.2)
    - Note (2026-11-08): `register_jinja_macro` is removed from the Port and the builder (`tests/unit/prompts/test_builder_registry.py::test_register_jinja_macro_is_gone`). `register_jinja_filter` keeps its name until the owner decides (open decision O40), so the task stays unticked.
    - Evidence (2026-11-11): renamed in task 9.2.
    - _Requirements: 30.8, 30.9; D20_
  - [x]* 2.7 Property tests: registry round trip, variable merge precedence, partial immutability (properties 1, 2, 10 of `design.md`)
    - Evidence (2026-11-08): `tests/unit/prompts/test_builder_registry.py::test_property_1_registry_round_trip`, `test_property_2_merge_precedence`, `test_property_10_partial_leaves_the_original_unchanged`.
    - _Requirements: 29.2, 30.4, 30.6_

- [ ] 3. Few-shot examples, roles, content and output schema: close the gaps
  - [x] 3.1 Format and inject examples with the example template at rendering; no selector uses all examples up to a default limit
    - Note: `render` injects examples as the variable `examples`; the default limit is 3 in `_select_examples` and 5 in `set_example_selector`; make it one value.
    - Evidence (2026-11-08): `tests/unit/prompts/test_builder_examples.py::test_one_default_limit_for_no_selector_and_selector` (`DEFAULT_MAX_EXAMPLES`), `test_examples_are_injected_for_both_template_kinds`.
    - _Requirements: 31.1, 31.4_
  - [x] 3.2 Semantic example selector by similarity, with the embedder passed in as a Port callable (no import of `models`)
    - Evidence (2026-11-08): `tests/unit/prompts/test_builder_examples.py::test_semantic_selector_needs_an_embedder`, `test_semantic_selector_picks_the_most_similar`, `test_semantic_selector_input_and_example_keys`.
    - _Requirements: 31.2_
  - [x] 3.3 Insert a conversation history at a message placeholder; reject an invalid role with a validation error
    - Note: `add_message_placeholder` records the placeholder and nothing reads it at rendering; an unknown role falls back to a user message.
    - Evidence (2026-11-08): `tests/unit/prompts/test_builder_messages.py::test_history_goes_at_the_placeholder_line`, `test_history_with_an_invalid_role_is_rejected`, `test_invalid_roles_are_rejected_at_configuration`.
    - _Requirements: 32.2, 32.3_
  - [ ] 3.4 Multimodal content: process image URL, base64 and file path into the typed content blocks of `base` (D46), keep the content type, reject an invalid format listing the supported ones
    - Note: `add_image_content` and `add_multimodal_content` record the configuration only.
    - Done so far (2026-11-08): image URL, base64 and file path become `UserMessage.images`, an invalid URL or format lists the supported ones, content types are recorded (`tests/unit/prompts/test_builder_messages.py`). Open: audio, video and files are only recorded, because the typed content blocks of D46 do not exist in `base` yet (Requirement 32.7); the task stays unticked until they do.
    - _Requirements: 32.4, 32.5, 32.6; D46_
  - [x] 3.5 Output schema from a dataclass or a JSON-schema dictionary; instructions list every field; invalid schema raises a validation error
    - Note: `get_output_instructions` returns a generic text for anything that is not a dictionary.
    - Evidence (2026-11-08): `tests/unit/prompts/test_builder_schema.py::test_dataclass_schema`, `test_no_schema_no_instructions`, `test_invalid_schema_raises`.
    - _Requirements: 33.1, 33.2, 33.3, 33.4; D24_
  - [x] 3.6 Create and format `CapabilityMessage` objects when the builder is used with capabilities
    - Evidence (2026-11-08): `tests/unit/prompts/test_builder_messages.py::test_capability_section_makes_a_capability_message`, `test_capability_message_helper`.
    - _Requirements: 34.2_
  - [x]* 3.7 Property tests: fixed and random selectors, one message per role section, composition equals join, schema instructions (properties 4, 5, 7, 8 of `design.md`)
    - Evidence (2026-11-08): `tests/unit/prompts/test_builder_examples.py::test_property_4_fixed_is_stable_random_is_bounded`, `tests/unit/prompts/test_builder_messages.py::test_property_5_one_message_per_role_section`, `test_property_7_composition_equals_join`, `tests/unit/prompts/test_builder_schema.py::test_property_8_instructions_name_every_field`.
    - _Requirements: 31.3, 32.1, 30.7, 33.3_

- [x] 4. Prompts in the `.skye` language (decision D60)
  - [x] 4.1 The reduced `prompt` block of version 1 is parsed, checked and written back: `variables` (typed, with defaults), `message "<role>"`, `text`, `when`, `each`, `placeholder`, `allow_missing`, interpolation `{{ expr }}`
    - Evidence: `src/skye/base/dsl/specs.py` (`PromptSpec`); `src/skye/base/dsl/emit.py`; `tests/unit/dsl/test_emit.py`, `tests/unit/dsl/test_conformance.py`.
    - _Requirements: 30, 31, 32, 33; D60_
  - [x] 4.2 Renderer in `skye.prompts` (not in `base`): `PromptSpec` plus variables gives a list of `SkyeMessage` with real roles, a `placeholder` replaced by the history the caller passes, `when` and `each` evaluated with `skye.base.dsl.evaluate`, `{{ }}` rendered by `prompts/engine.py`, required and default variables as in 30.2 and 30.4; a flow step reaches it as `run = prompt.NAME`
    - Evidence (2026-11-08): `src/skye/prompts/skye_prompts.py` (`load_prompt`, `render_prompt`, `PromptRunnable`); `tests/unit/prompts/test_skye_prompts.py` (roles, placeholder history, every branch of `chat`, `PromptRunnable`), `tests/unit/prompts/test_prompt_loops.py`. The flow runtime that calls `run = prompt.NAME` is `3-runtime-flows` and is not built.
    - _Requirements: 30.1, 30.2, 30.4, 32.1; D60_
  - [x] 4.3 Convert the 18 bundled templates in `src/skye/prompts/templates/` from `.jinja` to `.skye`, one by one (`chat`, `classification`, `agent_code`, `generation_code`, `explanation`, `agent_form`, `agent_memory_assistant`, `agent_memory_recall`, `agent_multimodal`, `ner`, `agent_procedure`, `question_answering`, `agent_reasoning`, `extraction_relations`, `sql_generation`, `summarization`, `extraction_table`, `agent_tool`); what version 1 cannot say is listed in `design.md` as version 2 and stays `.jinja` until the language grows
    - Evidence (2026-11-08): all 18 templates are `.skye` files in `src/skye/prompts/templates/` and no `.jinja` file is left there (the last three, `agent_form`, `agent_multimodal` and `agent_tool`, were converted once D69 gave `loop.*`, `{key, value}` entries and `map`); each passes `skye check` and `skye fmt --check`.
    - _Requirements: 30, 31, 32, 33; D60_
  - [x] 4.4 Equivalence test: render each old and each new prompt with the same data (variable combinations that cover every `if` and `for` branch) and compare the messages after normalising spaces and blank lines; list each intended difference (real roles instead of text markers) in the test
    - Evidence (2026-11-08): `tests/unit/prompts/test_equivalence.py` with 18 case files in `tests/unit/prompts/equivalence_cases/` and the frozen legacy texts in `tests/unit/prompts/legacy_templates/` (since task 9.1 the frozen legacy output, `tests/unit/prompts/legacy_renderings/`, one text per case, because the engine no longer runs `{% %}`); the intended differences are listed in `INTENDED_DIFFERENCES` (real roles, history as messages, whitespace, glued lines, renamed inputs).
    - _Requirements: 30.1, 32.1; D60_
  - [x] 4.5 Keep `prompts/engine.py` for user `.jinja` templates and for the `{{ }}` interpolation of the new blocks; once 4.4 passes, decide with the owner open decision O35 (restrict the engine to interpolation only, control tags declared obsolete)
    - Note (2026-11-08): the engine is kept. 4.4 passes for all 18 converted templates; none of them uses control tags any more, but user templates and `examples/advanced/prompt_engineering.py` do, so O35 stays open for the owner and the task stays unticked.
    - Note (2026-11-09): settled by D76, control tags removed; done in task 9.1.
    - Evidence (2026-11-11): the engine does interpolation only (task 9.1).
    - _Requirements: 30.8; D20; D76_
  - [x] 4.6 `loaders.py` discovers `.skye` prompt files next to the `.jinja` ones; remove the `.jinja` copies of the bundled templates when 4.4 passes
    - Evidence (2026-11-08): `discover_templates` and `load_default_templates` in `src/skye/prompts/loaders.py` prefer `.skye` and register the front matter `version`; `tests/unit/prompts/test_builder_registry.py::test_discover_prefers_skye`, `tests/unit/prompts/test_builder_skye.py::test_loader_registers_skye_over_jinja`; the `.jinja` copies are gone from `src/`.
    - _Requirements: 29.1, 29.4; D60_
  - [x] 4.7 Update the existing prompt tests and the docs section `docs/prompts/` to the new files
    - Evidence (2026-11-08): `docs/prompts/index.md` rewritten for the `.skye` prompts, the help and the bundled families; the prompt tests are `tests/unit/prompts/` (builder, skye, bundled).
    - _Requirements: 15.5; D60_

- [x] 5. Rewrite the stale `examples/prompts/` set off Jinja2 (found 2026-11-03 in the example-coverage review)
  - [x] 5.1 Rewrite the twelve files under `examples/prompts/` against the standard-library engine (`{{ }}`, `if`/`elif`/`else`, `for`, filters; no macros, inheritance, include or variable assignment), drop the Jinja2 wording, import normally without `sys.path` changes
    - Note: they use a `MockPromptBuilder` alias and manipulate `sys.path`.
    - Evidence (2026-11-08): `examples/prompts/` holds `basic_rendering`, `message_roles`, `control_flow`, `few_shot`, `output_schema`, `agent_prompt`, `group_chat` and `validation` (each a `.py` with, for five of them, a `.skye` file beside it) and a README; no `sys.path` change, no Jinja2 wording, each at most 80 lines (`tests/budget/test_example_size.py`, `test_example_readmes.py`). Left over: `examples/advanced/prompt_engineering.py` still writes `{% %}` text templates and uses `register_jinja_filter` (task 5.4).
    - _Requirements: 24.4, 24.5, 30.9; D20_
  - [x] 5.2 Remove the `MockPromptBuilder` alias from `skye.prompts` once no example uses it
    - Evidence (2026-11-08): `MockPromptBuilder` no longer exists in `src`, `tests`, `examples` or `docs` (`grep`).
    - _Requirements: 24.5_
  - [x] 5.3 Make each example runnable under `tests/examples` and remove `prompts` from `KNOWN_FOLDERS` and `EXEMPT_FOLDERS` of the example budget tests (`test_example_output_style.py`, `test_example_readmes.py`, `test_example_size.py`) and from the skip list of `test_examples_offline.py`; a budget list may only shrink
    - Evidence (2026-11-08): `KNOWN_FOLDERS`, `EXEMPT_FOLDERS` and `SKIPPED_FOLDERS` are empty sets in `tests/budget/test_example_output_style.py`, `test_example_readmes.py`, `test_example_size.py` and `tests/examples/test_examples_offline.py`; `uv run pytest tests -q` passes (3461 passed, 3 skipped on 2026-11-08).
    - _Requirements: 24.3, 24.4_
  - [x] 5.4 Rewrite `examples/advanced/prompt_engineering.py` in `.skye` (or cut it): it still uses `{% %}` text templates and `register_jinja_filter`
    - Note (2026-11-09): O35 and O40 settled by D76 and D77; the rewrite is part of task 9.1.
    - Evidence (2026-11-11): rewritten in task 9.1: few-shot examples as messages, composition of text templates, and a `.skye` prompt with `when`, a callable default and `register_filter`; it runs under `tests/examples` and fits the 80-line limit.
    - _Requirements: 24.9, 24.10; D74_

- [ ] 6. Licence and attribution
  - [ ] 6.1 Check whether anything in `prompts` was taken from prompt-poet (MIT); if so add the notice file and a comment at the copied code, otherwise record in the task that ideas and API shapes only were reused
    - Result (2026-11-08): nothing in `prompts` was taken from prompt-poet; only ideas and API shapes were reused, so no notice is needed. The bundled templates were also compared with Promptify 0.1.5 (Apache-2.0): two sentences of `ner` (the default system sentence and the output-format line) paraphrased `ner_openai.jinja` and were rewritten; the other templates share only the generic "You are an intelligent X system" opening. The new agent prompts are written for Skye (smolagents was read for its structure only).
    - Note: no prompt-poet notice exists in the repository today. liteprompt is the owner's own earlier project (private repo `ggiallo28/liteprompt`, MIT), so reusing its code needs no third-party notice; it is a source for the gaps in milestones 2 and 3 (registry, loaders, truncation, example selectors), to be read when those tasks start.
    - _Requirements: 14.2, 14.3_

- [x] 7. The `.skye` prompt language in the renderer (decisions D69, D70, D73; owner requests of 2026-11-08)
  - [x] 7.1 `each` with `loop.*`, `{key, value}` entries for a map, and the engine filter `map(attribute)`
    - Evidence (2026-11-08): `src/skye/prompts/skye_prompts.py`, `src/skye/prompts/engine.py`; `tests/unit/prompts/test_prompt_loops.py`, `tests/unit/prompts/test_engine.py`.
    - _Requirements: 30.11; D69_
  - [x] 7.2 Described and structured variables checked at render time: one `ValidationError` with the path of each mistake, defaults of optional fields filled in a copy, extra keys kept
    - Evidence (2026-11-08): `src/skye/base/dsl/shapes.py` (`conform`) used by `render_prompt`; `tests/unit/dsl/test_structured_variables.py`, `tests/unit/dsl/test_variable_descriptions.py`, `tests/unit/prompts/test_skye_prompts.py`. The form of the default (`list({ ... }, [])`) is confirmed by D83.
    - _Requirements: 30.10; D73_
  - [x] 7.3 The `output` block: `json`, `table`, `xml`, `schema = VAR`, field descriptions, the format from a variable, instructions appended to the last user message
    - Evidence (2026-11-08): `src/skye/prompts/output_format.py`, `output_instructions` in `src/skye/prompts/skye_prompts.py`, `set_output_schema(..., output_format=)` and `get_output_instructions` in `src/skye/prompts/messages.py`, the engine filters `toxml` and `totable`; `tests/unit/prompts/test_output_instructions.py`, `tests/unit/dsl/test_output_block.py`.
    - _Requirements: 33.5, 33.6, 33.7; D70_
  - [x] 7.4 Conditional outputs inside `when` (`active_output`, one active block, an error for two), also in the builder's `get_output_instructions`
    - Evidence (2026-11-08): `active_output` in `src/skye/prompts/skye_prompts.py`, `_skye_output_instructions` in `src/skye/prompts/messages.py` (uses `spec.output_variants()`); `tests/unit/dsl/test_conditional_output.py`, `tests/unit/prompts/test_structured_output_prompts.py`.
    - _Requirements: 33.8; D70_
  - [x] 7.5 Prompt help: `describe_prompt`, `prompt_help`, `BasePromptBuilder.describe` and `.help`, and the commands `skye prompt list` and `skye prompt info`
    - Evidence (2026-11-08): `src/skye/base/dsl/info.py` (re-exported by `skye.prompts`), `src/skye/prompts/messages.py`, `src/skye/utils/cli.py`; `tests/unit/prompts/test_prompt_help.py`, `tests/unit/utils/test_cli_prompt.py`. The place of the code is confirmed by D83.
    - _Requirements: 34.7; D73_
  - [x] 7.6 Front matter read by the loader and registered as the template version; `add_examples` passes the selected list of dicts to a `.skye` prompt
    - Evidence (2026-11-08): `src/skye/prompts/loaders.py`, `_wants_example_list` in `src/skye/prompts/messages.py`; `tests/unit/prompts/test_builder_skye.py`, `tests/unit/prompts/test_builder_examples.py::test_skye_list_examples_get_the_selected_dicts`, `test_skye_string_examples_are_still_formatted`.
    - _Requirements: 30.13, 31.5; D71, D74_
  - [x] 7.7 Prompts as parts for a native provider call (system, content blocks, output schema): `render_parts` or `to_request`
    - Note (2026-11-09): settled by D81 (parts with no provider in them; the model side translates them through a Port in `base`); done in task 9.6. Few-shot (D79), tool parameters (D80) and named types (D82, version 2) are settled too.
    - Evidence (2026-11-11): `render_parts` (task 9.6).
    - _Requirements: 33.5, 33.9; D81_

- [ ] 8. Bundled agent prompts written in `.skye` (decision D74; Requirement 30.12 to 30.14)
  - [x] 8.1 The new families, with original text: smolagents (`agent_smol_code`, `agent_smol_tool_calling`, `agent_smol_planning`, `agent_smol_managed`), reasoning (`agent_reasoning_chain_of_thought`, `agent_reasoning_tree_of_thoughts`, `agent_reasoning_self_reflection`, `agent_planner`), supervisors (`agent_supervisor_router`, `agent_supervisor_planner`, `agent_supervisor_reviewer`, `agent_supervisor_hierarchical`), group chat (`agent_groupchat_participant`, `agent_groupchat_manager`, `agent_groupchat_summarizer`), memory upkeep (`agent_memory_update`, `agent_memory_consolidation`, `agent_memory_working`) and structured output (`structured_output`, `structured_output_json`, `_table`, `_xml`)
    - Amended (2026-11-13, D118): of these families only `agent_react` (the former `agent_smol_tool_calling`) stays bundled; the other prompts moved to `examples/prompts/catalogue/` (task 24.11 of `0-base-plugins`), with their tests reading the gallery.
    - Evidence (2026-11-08): the 40 `.skye` files in `src/skye/prompts/templates/`; `tests/unit/prompts/test_smol_prompts.py`, `test_reasoning_prompts.py`, `test_planner_prompt.py`, `test_supervisor_prompts.py`, `test_group_chat_prompts.py`, `test_memory_update_prompts.py`, `test_structured_output_prompts.py`.
    - _Requirements: 30.14; D74_
  - [x] 8.2 One shape for `tools` and the five memories in every agent prompt, `placeholder "history"` everywhere, the old input names removed, front matter and a usage comment in every template
    - Evidence (2026-11-08): `tests/unit/prompts/test_bundled_conventions.py` (identical shapes, front matter, formatted, comment convention, the `Example:` comment is extracted and rendered), `tests/unit/prompts/test_agent_prompt_inputs.py`, `tests/unit/prompts/test_jinja_agent_inputs.py`; `uv run skye check` and `uv run skye fmt --check` on `src/skye/prompts/templates` and `examples` were clean on 2026-11-08.
    - _Requirements: 30.12, 30.13, 24.10; D71, D74_

- [x] 9. Decisions of 2026-11-09 (D76 to D83)
  - [x] 9.1 Text templates do interpolation only: remove the `{% %}` control tags from `prompts/engine.py` (keep `{{ }}` and the filters), reject a tag with a `ValidationError` naming the line and pointing to `when` and `each`; move `docs/prompts/index.md`, `docs/base/skye-language.md` and `examples/advanced/prompt_engineering.py` to `.skye`; drop the required-variable rule for tags
    - Evidence (2026-11-11): `src/skye/prompts/engine.py` (the `if`/`for` parser is gone; `_lex` raises `TemplateSyntaxError` with the tag and `line` for any `{% %}`; `required_variables` are the names not read through `default`), `_compile_text` in `src/skye/prompts/messages.py` (the error names the template and the line, `details["line"]`); `tests/unit/prompts/test_interpolation_only.py`, `tests/unit/prompts/test_engine.py`, `tests/unit/prompts/test_builder_registry.py`, `tests/unit/test_prompts_base.py::TestBasePromptBuilder::test_text_template_with_a_control_tag_points_to_skye` (the old tag tests there are rewritten in `.skye`). The equivalence test of task 4.4 compares with the legacy output frozen before the tags were removed (`tests/unit/prompts/legacy_renderings/`; the `.jinja` copies are deleted). `examples/advanced/prompt_engineering.py` uses a `.skye` prompt; the pages that replaced `docs/prompts/index.md` and `docs/base/skye-language.md` (`docs/guides/prompts/variables-and-filters.md`, `docs/reference/skye-language.md`) say that text templates are interpolation only.
    - _Requirements: 30.2, 30.8, 24.9; D76_
  - [x] 9.2 Rename `register_jinja_filter` to `register_filter` on the Port and in `BasePromptBuilder`, with no alias; update the tests, the example and the skill
    - Evidence (2026-11-11): `src/skye/base/interfaces/prompt.py`, `src/skye/prompts/messages.py`; `tests/unit/prompts/test_builder_registry.py::test_register_filter_replaces_register_jinja_filter_with_no_alias`, `tests/unit/test_interfaces.py`, `tests/unit/prompts/test_builder_skye.py`, `tests/unit/prompts/test_public_names.py::test_the_old_jinja_name_is_gone`; `examples/advanced/prompt_engineering.py`, `docs/guides/prompts/variables-and-filters.md` and the skill reference `prompt.md` use the new name. The old name is left only in the decision log, the history of this file and the tests that check it is gone.
    - _Requirements: 30.8; D77_
  - [x] 9.3 Few-shot: the text of an example from its own keys when no example template is given; `add_examples(..., as_messages=True)` gives user/assistant pairs; a key missing from an example is a `ValidationError` (today such an example renders as nothing)
    - Evidence (2026-11-11): `add_examples`, `_format_examples`, `_insert_example_messages`, `_keys_text` and `_example_turns` in `src/skye/prompts/messages.py`, the `as_messages` keyword on the Port; `tests/unit/prompts/test_builder_examples.py::test_without_an_example_template_each_example_is_written_from_its_own_keys`, `test_a_key_the_example_template_reads_is_required`, `test_a_key_read_through_default_may_be_missing`, `test_as_messages_gives_user_and_assistant_pairs_before_the_last_user_message`, `test_as_messages_works_for_a_skye_prompt_and_follows_the_selector`, `test_as_messages_needs_two_keys`, `test_as_messages_and_an_example_template_do_not_mix`. The missing key is caught in `add_examples` (index and keys in `details`), not at the first render.
    - _Requirements: 31.6, 31.7, 31.8; D79_
  - [x] 9.4 Show tool parameters as JSON Schema in the four smolagents-style prompts too (`each param in tool.parameters` becomes `tool.parameters | tojson`)
    - Evidence (2026-11-11): `agent_smol_code.skye`, `agent_smol_tool_calling.skye`, `agent_smol_planning.skye`, `agent_smol_managed.skye` in `src/skye/prompts/templates/` write `Parameters: {{ tool.parameters | tojson }}`; `tests/unit/prompts/test_smol_prompts.py::test_tool_parameters_are_shown_as_json_schema`, `test_tools_and_every_memory_type`; `uv run skye check` and `uv run skye fmt --check` on the templates are clean.
    - _Requirements: 30.12; D80_
  - [x] 9.5 `describe(spec)` in `base/dsl/info.py` for prompt, router and flow blocks, public in `skye.dsl` (with the `0-base-uxui` facade); `skye.prompts` keeps `describe_prompt` and `prompt_help`
    - Evidence (2026-11-11): `describe`, `RouterInfo`, `RouteInfo`, `FlowInfo` and `NodeInfo` in `src/skye/base/dsl/info.py`; `skye.dsl` exports `describe`, `PromptInfo`, `RouterInfo` and `FlowInfo`; `tests/unit/dsl/test_describe.py`, `tests/budget/test_facade_purity.py`. The command `skye help FILE` of D83 is not part of this task.
    - _Requirements: 34.9; D83_
  - [x] 9.6 Prompt parts: the provider-agnostic parts type in the `prompt` Port of `base`, produced by the renderer; the model side translates it (`1-adapters-models` task 11)
    - Note: names (`render_parts`, `PromptParts`) are fixed in the design before code.
    - Note (2026-11-11): `PromptParts` and `OutputSchema` now exist in `base` (`src/skye/base/prompt_parts.py`, D101) and the model side is done (`1-adapters-models` task 11). This task only adds `render_parts`, which returns a `PromptParts` (the output schema of a `.skye` prompt as `OutputSchema`, its output instructions as `fallback_text`).
    - Evidence (2026-11-11): the names are in `design.md` ("Prompt parts"); `render_parts`, `output_json_schema` and `split_system` in `src/skye/prompts/skye_prompts.py`, `BasePromptBuilder.render_parts` in `src/skye/prompts/messages.py`, a concrete default `PromptRenderingInterface.render_parts` on the Port; `tests/unit/prompts/test_render_parts.py`. `skye.prompts` also exports `PromptSpec`, `PromptPartSpec`, `OutputSpec`, `PromptParts`, `OutputSchema` and `output_json_schema` (docs finding 22; `tests/unit/prompts/test_public_names.py`). Docs: `docs/guides/prompts/output-schema.md` (Step 5), `docs/guides/models/structured-output.md`.
    - _Requirements: 33.9; D81, D101_
