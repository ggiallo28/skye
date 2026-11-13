# Implementation Plan: uxui

## Overview

This plan closes the findings of the 2026-11-03 audit of the public surface (`.agents/tasks/uxui-audit-report.md`), grouped by
mechanism: the import facades (done before this spec), name collisions, Port conformance, naming and vocabulary, the examples, and
docstrings. Each task cites the local requirement it satisfies (`N.k` of `requirements.md`) and, where useful, the steering
requirement or decision directly. A task that depended on an open decision names the decision (D36 to D45, taken by the owner) it follows. Tasks that belong to another spec (`models:8.2`, `prompts:5`) are not repeated here.

## Tasks

- [x] 1. Short public import paths (decision D34, done before this spec)
  - [x] 1.1 Facades `skye.interfaces`, `skye.data`, `skye.messages`, `skye.completion`, `skye.exceptions`, `skye.config`
    - Evidence: `src/skye/interfaces.py`, `data.py`, `messages.py`, `completion.py`, `exceptions.py`, `config.py`; each only imports and re-exports its source in `skye/base`.
    - _Requirements: 1.1, 1.3_
  - [x] 1.2 66 examples and the documentation rewritten to the short paths
    - Evidence: `examples/`, `docs/` import only `skye`, `skye.interfaces`, `skye.data` or a component package; no `skye.base.*`.
    - _Requirements: 1.1_
  - [x] 1.3 `tests/budget/test_public_imports.py`
    - Evidence: scans `examples/`, `docs/`, `README.md`; fails on a path deeper than two levels or through `skye.base`.
    - _Requirements: 1.1, 1.2_
  - [x] 1.4 Facade purity test
    - Evidence: `tests/budget/test_facade_purity.py` (parametrized over the six facades).
    - Add `tests/budget/test_facade_purity.py`: parse each facade module with `ast`; fail on a `def`, a `class`, or an assignment other
      than `__all__`/a lazy-name table; fail when a name in `__all__` is not defined by the module it re-exports from. See
      `design.md` "Facades only re-export".
    - _Requirements: 1.2; D34_

- [x] 2. One name, one home
  - [x] 2.1 Duplicate-name test
    - Evidence: `tests/budget/test_unique_names.py`; `KNOWN_DUPLICATES` holds `CapabilitySchema` (pydantic copy in `tools`, leaves with O4) and `CapabilityInterface` (older copy in `tools`, found by the test).
    - Add `tests/budget/test_unique_names.py`: walk `src/skye` with `ast`, collect public `class` definitions, fail on a name defined
      in two modules except `KNOWN_DUPLICATES` (seeded with `CapabilitySchema`: 3 modules, `CapabilityExecutionError`: 2); the list
      only shrinks, like `known_leaks`.
    - _Requirements: 2.1_
  - [x] 2.2 Resolve `CapabilityExecutionError`
    - Evidence: `CapabilityError` and `CapabilityExecutionError` are defined in `base/exceptions.py`; `tools/exceptions.py` re-exports them; details key is `capability_name`.
    - One definition in `base.exceptions`; `tools.exceptions` re-exports it; update the differential test that imports the `tools`
      one for the reason recorded in the audit (finding 15).
    - _Requirements: 2.1_
  - [x] 2.3 Resolve `CapabilitySchema`
    - Evidence: `base/capability_schema.py` re-exports the `Validated` class of `base/interfaces/capability.py`; only the pydantic copy in `tools/schema.py` remains, tracked in `KNOWN_DUPLICATES` until O4.
    - Three definitions (`base.interfaces.capability`, `base.capability_schema`, `tools.schema`, the last pydantic). Coordinate with
      the pydantic removal of `0-base-structure` (group 14, O4): the pydantic one is retired there, not duplicated here; this task
      makes the other two agree (one dataclass, one re-export) and removes the entry from `KNOWN_DUPLICATES` once the pydantic one
      is gone.
    - _Requirements: 2.1; O4_

- [x] 3. Port contracts
  - [x] 3.1 Signature-aware compliance checker
    - Evidence: `port_signature_mismatches`, `validate_port_signatures`, `port_methods` in `src/skye/utils/validation.py`.
    - Extend `utils/validation.validate_interface_compliance` (or add a sibling function) to compare, per Port method: parameter
      names and kinds in order (ignoring `self`/`cls`), `def`/`async def`/async-generator form, and the return annotation by name
      when both sides declare one; accept `Protocol` Ports, not only `ABC`. See `design.md` "Port conformance by signature".
    - _Requirements: 5.2; 16.7 of steering_
  - [x] 3.2 One test for every built-in implementation
    - Evidence: `tests/unit/test_port_signatures.py`; `KNOWN_MISMATCHES` has 8 pairs (seven `ModelInterface` implementations, `BasePromptBuilder`).
    - `tests/unit/test_port_compliance.py`: one parametrized case per (implementation, Port) pair found in `src`, plus a short
      reference implementation for each exported Port that has none; `KNOWN_MISMATCHES` seeded with the three P1 findings below and
      only shrinking.
    - _Requirements: 5.2_
  - [x] 3.3 Fix `ModelInterface.astream` typing
    - Evidence: `ModelInterface.astream` is an async generator typed `AsyncIterator[StreamChunk]`.
    - `async def astream(...) -> Iterator[StreamChunk]` becomes an async generator typed `AsyncIterator[StreamChunk]`; update the
      Port docstring example to `async for`.
    - _Requirements: 5.1; 16.6 of steering_
  - [x] 3.4 Align `select_model` sync/async
    - Evidence: the Port now declares `async def select_model`. Open: `models/base.py` (about lines 551 and 701) calls `router.select_model(messages)` without `await`, a defect that predates this task.
    - `ModelRouterInterface.select_model` and `ModelRouter.select_model` must agree. Check the callers first, then change the one
      that costs less: the audit found the Port sync and the router `async def`, so a caller that follows the Port gets a coroutine
      where it expects a `str`.
    - _Requirements: 5.1; 16.6 of steering_
  - [x] 3.5 The model Port's call shape — decided in D36
    - Evidence: `ModelInterface` and the provider overrides take `messages`/`model`/options or one `CompleteRequest`; no `type: ignore[override]` left; `KNOWN_MISMATCHES` is empty; `_select_with_router` in `models/base.py` awaits `select_model`.
    - D36: `ModelInterface.complete`/`stream`/`acomplete`/`astream` take `messages`, `model` and options, and also accept one `CompleteRequest` as the
      first argument; rename `CompletionRequest`/`CompletionResponse` to `CompleteRequest`/`CompleteResponse` across `src`, `examples`, `docs` and
      tests (the module stays `skye.completion`); remove the `type: ignore[misc,override]` of `custom_providers.py` and `bring_your_own_adapter.py`.
    - _Requirements: 5.1; D36_
  - [x] 3.6 Reconcile six unimplemented Ports — decided in D41
    - Evidence: `TokenCounter` and `CostCalculator` inherit their Ports; `ConfigLoaderInterface` reduced to `load`; `MultimodalHandlerInterface`, `ErrorHandlerInterface`, `RouteRegistryInterface`, `StorageAdapterInterface` removed from `skye.interfaces`, `extending.md` and the tests.
    - D41: make `models.TokenCounter` and `models.CostCalculator` satisfy their Ports; change `ConfigLoaderInterface` to the methods of
      `base.config.ConfigLoader`; remove `MultimodalHandlerInterface`, `ErrorHandlerInterface` and `RouteRegistryInterface` and
      `StorageAdapterInterface` from `__all__` (and the facade, the extension page and the tests that list them); `ModelInterface` does not extend `Runnable`.
    - _Requirements: 7.1; D41_
  - [x] 3.7 Port docstring footer
    - Evidence: footer in the 22 Port modules; `tests/unit/test_port_docstrings.py`. Wording came from Port docstrings and a few implementations; the owner should review it against the code.
    - Add `Raises:`, `Missing:`, `Concurrency:` to each of the 23 Port modules under `base/interfaces/`; a test
      (`tests/unit/test_port_docstrings.py`) fails on a missing label. Content comes from reading each implementation, not guessed.
    - _Requirements: 6.1_
  - [x] 3.8 Reference implementations for untested Ports
    - Evidence: reference implementations for 18 Ports in `tests/unit/test_port_signatures.py`.
    - For `MultimodalHandlerInterface`, `CostCalculatorInterface`, `TokenCounterInterface`, `ErrorHandlerInterface`,
      `ConfigLoaderInterface` (named by neither a test nor an example per the audit) and any Port still bare after 3.6, add the
      small in-memory implementation that 3.2's test exercises.
    - _Requirements: 7.1_
  - [x] 3.9 Split the largest Ports — decided in D41
    - Evidence: `ModelRouterInterface` composes `ModelSelectionInterface`, `ModelHealthInterface`, `RouterConfigurationInterface`; `PromptBuilderInterface` composes `PromptRenderingInterface`, `PromptRegistryInterface`, `PromptSchemaInterface`; combined names still work.
    - D41: split `ModelRouterInterface` into selection, health and configuration parts, and `PromptBuilderInterface` into rendering, registry and
      schema parts; the router and the builders implement all the parts; a caller that needs one role types against it.
    - _Requirements: 7.1; D41_
  - [x] 3.11 One execution primitive — decided in D42, D43, D45
    - Evidence: `src/skye/base/capability_execution.py` (`run_capability_call`, `arun_capability_call`); `CapabilityStatus`; `CapabilityCall.execute()`; `execute_capability_calls` sync and `aexecute_capability_calls`; `tests/unit/test_capability_execution.py`. `CapabilityCallHandler` still returns `CapabilityResult` and shares only the formatter and status (its tests depend on it).
    - D42, D43, D45: add one function in `base`, next to the capability Port, that runs a single call, never raises and returns a
      `CapabilityMessage` whose `status` is `CapabilityStatus` (`str` enum: ok, error, denied, skipped; `is_error` derived); make
      `CompleteResponse.execute_capability_calls` (now sync, with `aexecute_capability_calls`), `CapabilityCall.execute()`, `CapabilityRegistry` and
      `CapabilityCallHandler` delegate to it (`registry.execute` stays the raising path); remove `ExecutableCapabilityCall` and `get_capability_calls()`.
      Also fix the low-level defects: `json.dumps(result, default=str)` so a `datetime` in a result is not the tool's error (L5); accept a name key in
      `argument_overrides` (L6); type `capability_calls` as `list[CapabilityCall]` and `capabilities` as the list-or-registry union (L3); drop the
      `skyeai[capabilities]` try/except (L7); import `CapabilityCall` from the facade path (L8). Test that every path returns an equal message and that
      a tool's `"Error:"` text has the status `ok`. See `design.md` "The execution primitive".
    - _Requirements: 15.1, 15.2; 16.10, 16.12 of steering; D42; D43; D45_
  - [x] 3.12 The `ToolProvider` Port — decided in D44
    - Evidence: `src/skye/base/interfaces/tool_provider.py` (`ToolProvider`, `CapabilityContext`); `CapabilityRegistry` implements it; `tests/unit/test_tool_provider.py`. The gateway client is not done: `skye.gateway` has no code yet.
    - D44: define the Port in `base/interfaces` (list schemas for an operation, run one call with an explicit `context`, optionally close);
      `CapabilityRegistry` and the gateway client implement it; the context carries the scope token and the operation description, never folded into
      the model's arguments. `@capability` registers nothing: `registry.add(fn)` and `create_agent(capabilities=[fn])` take objects, and a name resolves
      only in a registry the user passes. See `design.md` "The `ToolProvider` Port".
    - _Requirements: 16.1, 16.2; 16.11 of steering; D44_
  - [x] 3.10 Protocol-vs-ABC convention — decided in D37
    - Evidence: `ObserverInterface`, `SafetyFilterInterface`, `MemoryInterface` are runtime-checkable `Protocol`s; the rule is in `.kiro/steering/11-design.md`.
    - D37: write the rule in steering (Ports that third parties implement as plain classes are `Protocol`s: authentication, authorizer, decision,
      runnable, observer, safety, memory; Ports with default behaviour to inherit stay abstract bases) and convert `ObserverInterface`,
      `SafetyFilterInterface` and `MemoryInterface` to `Protocol`s. `MCPClientPort` becomes `MCPClientInterface` (D40, task 4.2).
    - _Requirements: 7.1; D37; D40_

- [x] 4. Naming and vocabulary
  - [x] 4.1 Naming convention and vocabulary in the wiki
    - Evidence: "Words used in the code and the documentation" in `docs/glossary.md`.
    - Add the convention of Requirement 22.5 (verbs/nouns, `x`/`ax`, `get_`/`list_`/`set_`/`register`) and the Port/Interface and
      capability/tool/function-call glossary lines (22.1, 22.3) to `docs/glossary.md`.
    - _Requirements: 3.1, 4.1, 4.2_
  - [x] 4.2 `MCPClientPort` naming — decided in D40
    - Evidence: `MCPClientInterface` in `src`, tests and docs.
    - D40: rename `MCPClientPort` to `MCPClientInterface` in `src`, tests, docs and examples.
    - _Requirements: 3.1; D40_
  - [x] 4.3 Guessability aliases — decided in D39
    - Evidence: `CompleteResponse.text`, `CapabilityRegistry.list()`, `ainvoke` on `BaseModelProvider` and `ReActAgent`; the `Runnable` Protocol still requires only `invoke`, so a user class with only `invoke` keeps working.
    - D39: add `CompleteResponse.text` (read-only, returns `content`), `CapabilityRegistry.list()` (returns `list_all()`) and `ainvoke` beside
      `Runnable.invoke`; each a thin alias with no new behaviour. Nothing else is added.
    - _Requirements: 3.1; D39_
  - [x] 4.4 File naming in `models/` and `tools/`
    - Evidence: `google_provider.py` is now `google.py`; the old `openai_compatible.py` is split into `openai_compatible.py` (`OpenAICompatibleProvider`, the shared wire format), `openai.py` (`OpenAIProvider`) and `azure.py` (`AzureOpenAIProvider`), so every vendor file of `models/llm` is named after its provider (`anthropic.py` beside `anthropic_compatible.py`, `bedrock.py`, `openai.py`, `azure.py`, `google.py`); imports, budget tests, docs and the `1-adapters-models` and `0-base-structure` specs follow. `skye.auth.openai_compatible` is a different module and keeps its name.
    - _Requirements: 3.2_
  - [x] 4.5 `skye.router` storage re-exports — decided in D40
    - Evidence: `tests/unit/router/test_router_exports.py`.
    - D40: remove the six storage re-exports from `skye.router`; examples and docs import them from `skye.store`.
    - _Requirements: 2.1; D40_
  - [x] 4.6 Placeholder packages raise a clear error — decided in D40
    - Evidence: `tests/unit/test_placeholder_packages.py`.
    - D40: add a module-level `__getattr__` to `skye.flows`, `skye.gateway`, `skye.teams`, `skye.policy`, `skye.observe` and `skye.guard` that raises
      `ImportError("skye.<name> is planned, not available yet")` for an unknown attribute.
    - _Requirements: 3.2; D40_
  - [x] 4.7 Router shorthand
    - Evidence: `expand_route_shorthand` and the `routes` dict form in `src/skye/router/model_router.py`; `tests/unit/router/test_router_shorthand.py`. The `routing/` examples are rewritten under 5.7/5.8.
    - `ModelRouter({"alias": ["provider/model", ...]})` builds the same `RouteConfig`, `ModelTarget` and `FallbackConfig` (first entry
      primary, the rest fallbacks), reads the provider from the string and the API key from the provider's standard variable, and leaves
      the full form first-class; one syntax only (no `from_list`). A test asserts the shorthand and the explicit form build an equal router
      and that an explicit field is never overwritten by a default. Rewrite the `routing/` examples to start with the shorthand (feeds 5.7,
      5.8). See `design.md` "The router shorthand".
    - _Requirements: 17.1; 22.8 of steering_
  - [x] 4.8 Typed `provider()` — the combined client type is not added (D40)
    - Evidence: `@overload`s in `src/skye/__init__.py` and `src/skye/models/registry.py`; `tests/unit/test_provider_typing.py` (mypy run is skipped when mypy is absent).
    - Add `@overload` so the default call returns the model client and `provider_type="embedding"` the embedding client, and a type-checker
      test over the quickstart lines (no cast, no `ignore`). The larger "one combined client exposing `complete` and `encode`" option waits
      for D40.
    - _Requirements: 18.2; 22.9 of steering; D40_
  - [x] 4.9 Guessability aliases and their test — decided in D39
    - Evidence: `tests/budget/test_guessable_names.py`.
    - D39: the test `tests/budget/test_guessable_names.py` records `text`, `list()` and `ainvoke` as `exists` and `tool_choice`/`tools`, `kind=`,
      `skye.Router`, `skye.tool` and the Pydantic-style methods as `known_missing` (documented, not added); the list only shrinks.
    - _Requirements: 18.1, 18.2; 22.7 of steering; D39_

- [x] 5. Examples
  - [x] 5.1 Delete the empty example
    - Evidence: `examples/providers/router_example.py` removed.
    - Remove `examples/providers/router_example.py` (0 bytes); routing is already covered by `examples/routing/`.
    - _Requirements: 9.3_
  - [x] 5.2 Guard the four tracebacks
    - Evidence: the four examples print guidance instead of a traceback.
    - `capabilities/mcp_client.py`, `tools/mcp_fastmcp.py` (check for a server first, print how to start one or set
      `MCP_SERVER_URL`), `serverless/serverless_router_example.py` (catch the `${VAR}` `ConfigurationError`),
      `routing/yaml_config_example.py` (stop after showing the loaded router instead of making a real call with a placeholder key).
    - _Requirements: 8.1, 8.2_
  - [x] 5.3 Offline demo provider — decided in D38
    - Evidence: `examples/_offline.py` (scripted model or the real provider when a key exists), used by the examples named in the task.
    - D38: one scripted model in `examples/` (a shared helper, not in the package) replaces the "skipping" branches of `basic/quickstart.py`,
      `async_and_streaming.py`, `models/cost_tracking.py`, `advanced/function_calling.py`, `advanced/streaming.py`,
      `advanced/structured_output.py` and `routing/fallbacks_and_health.py`; with a provider key the example uses the real provider; each prints which mode ran.
    - _Requirements: 8.1; D38_
  - [x] 5.4 Offline-run test
    - Evidence: `tests/examples/test_examples_offline.py` (written, not yet run).
    - `tests/examples/test_examples_offline.py`: run each example in a subprocess with provider environment variables unset and
      outbound sockets refused; fail on a non-zero exit or on `Traceback` in the output.
    - _Requirements: 8.1_
  - [x] 5.5 Install-line test and fix
    - Evidence: `tests/budget/test_install_lines.py`; `KNOWN_STALE` holds `docs/getting-started.md` and `docs/models/provider-guide.md`, to fix next.
    - `tests/budget/test_install_lines.py`: find every `pip install skyeai[...]` in `examples/`, `docs/`, `README.md`; fail when the
      extra does not exist or is in `known_empty`. Fix `examples/README.md` (lines about `[openai]`, `[openai,anthropic,bedrock]`),
      `providers/openai_example.py`, `providers/google_example.py`, `capabilities/mcp_server.py` (the `fastmcp` version range),
      and the package docstring (6.1 also touches this file).
    - _Requirements: 10.1, 10.2_
  - [x] 5.6 README-matches-folder test and fix
    - Evidence: `tests/budget/test_example_readmes.py`; a README in each folder; reading order in `examples/README.md`.
    - `tests/budget/test_example_readmes.py`: a folder's README lists exactly its `*.py` files; fails on `basic/README.md`'s
      `streaming_example.py` reference and on folders with no README (`auth/`, `base/`, `memory/`, `models/`, `prompts/`, `store/`,
      `tools/`). Add the missing READMEs (five lines: what you learn, the command, what you see, what you need) and a numbered
      reading order in `examples/README.md`.
    - _Requirements: 11.1, 11.2_
  - [x] 5.7 Merge or cut duplicate examples
    - Evidence: kept `advanced/function_calling.py` and `routing/yaml_config_example.py`; the three duplicates are deleted.
    - Keep the short one of each pair and link the long one as "reference" or delete it: `advanced/function_calling.py` over
      `capabilities/function_calling_example.py` and `providers/function_calling_example.py`; `routing/yaml_config_example.py` over
      `routing/yaml_config.py`; the short `prompts/` duplicates are handled by `prompts:5`, not here.
    - _Requirements: 9.3_
  - [x] 5.8 Size test and split
    - Evidence: `tests/budget/test_example_size.py`; every example is at most 80 lines except `advanced/custom_providers.py` (90, the only `KNOWN_LONG` entry).
    - `tests/budget/test_example_size.py`: fail above about 80 lines unless listed in `KNOWN_LONG` (seeded with the nine files over
      300 lines named in the audit); split or cut each, moving exhaustive variants to the docs wiki.
    - _Requirements: 9.1_
  - [x] 5.9 Plain-output test and fix
    - Evidence: `tests/budget/test_example_output_style.py`; only `prompts/` is allowlisted.
    - `tests/budget/test_example_output_style.py`: fail on a `"=" * N` banner row or an emoji character in a `print` literal, unless
      listed; remove the banners and emoji rows, aligning labels as `basic/configuration.py` already does.
    - _Requirements: 9.2_
  - [x] 5.10 The value-proposition example — decided in D38
    - Evidence: `examples/advanced/value_proposition.py`.
    - D38: `examples/advanced/value_proposition.py`: one prompt, run against two or three providers, with a fallback when one fails; real
      providers when keys exist, the scripted model otherwise.
    - _Requirements: 9.3; D38_

- [x] 6. Docstrings and discoverability
  - [x] 6.1 Fix the package docstring
    - Evidence: `src/skye/__init__.py` docstring already uses `response.content` and no `skyeai[bedrock]` line.
    - `src/skye/__init__.py`: `response.text` → `response.content`; the stale `pip install skyeai[bedrock]` line.
    - _Requirements: 12.1_
  - [x] 6.2 Docstring doctest gate
    - Evidence: `tests/unit/test_docstrings.py`.
    - `tests/unit/test_docstrings.py`: run `doctest` on the package docstring and each Port module docstring, with
      `# doctest: +SKIP` on network-needing lines.
    - _Requirements: 12.1_
  - [x] 6.3 Extension page
    - Evidence: `docs/base/extending.md`; completeness test in `tests/docs/test_docs.py`.
    - `docs/base/extending.md` (or similar, in the `base` wiki section): one table, kind of extension / Port / registry / example
      file / status, seeded from "Extension points" of `11-design.md` and extended to every exported Port; a docs test fails when a
      name in `skye.interfaces.__all__` has no row.
    - _Requirements: 13.1, 13.2_
  - [x] 6.4 Document import cost per package
    - Evidence: `docs/budgets.md`.
    - `docs/budgets.md`: one line per component package stating whether it loads pydantic, until the pydantic removal (O4) makes
      this moot.
    - _Requirements: 7.4 of steering; O4_

- [x] 7. Checkpoint (run by a reviewer, not by the implementer)
  - [x] 7.1 Run the whole test suite and fix what fails; ask the user if questions arise
    - Evidence (2026-11-07, offline, on the regenerated `uv.lock`): `uv run pytest tests -q` gave 2295 passed, 3 skipped, 0 failed; `uv run pytest tests/budget -q` gave 290 passed.
      Failures found and fixed: `examples/serverless/lambda_handler.py` created a Bedrock client at import with no credentials (it also failed on the clean HEAD; it now uses
      `provider_or_scripted` like `bedrock_example.py`); `tests/stress/test_rate_limiting.py::test_rate_limit_tracking_accuracy` counted requests per fixed one-minute window and failed when
      the 50 requests crossed a minute boundary (proved by moving the clock; the test now fixes the window, the code is unchanged). Allowlists: empty are `KNOWN_MISMATCHES`,
      `KNOWN_STALE`, `known_leaks`, `known_import_failures`, `known_compiled`; non-empty with a named debt are `KNOWN_DUPLICATES` (the two older `tools` copies of `CapabilitySchema` and
      `CapabilityInterface`), `KNOWN_LONG` (`advanced/custom_providers.py`, 90 lines, because `BaseModelProvider` has 11 abstract hooks; proposal S5.5, not yet a task) and
      `KNOWN_FOLDERS` (`prompts/`, `prompts:5`).
    - The reviewer runs `uv run pytest tests/ -q` and `uv run pytest tests/budget -q`. The implementation of the other tasks was written without
      running the suite, so expect to repair failures in the new tests and in the code they guard: do that here, one failure at a time.
    - Confirm every new allowlist (`KNOWN_DUPLICATES`, `KNOWN_MISMATCHES`, `KNOWN_LONG`) is non-empty only where a real, named debt remains.
    - Report which tasks are still unticked: after D36 to D45 only the split of long examples in 5.8 may remain.
    - _Requirements: all_

- [x] 8. The `.skye` language: public surface (spec only until the parser exists)
  - Note: nothing here is built and no example has been run through a parser. The parser itself (text in, syntax tree out, standard library, in
    `base`) is a task of `0-base-base`, to be added when it is designed; the tasks below follow it. The syntax, the error table and the scope are in
    `design.md`, "The `.skye` language". The decisions are D49 to D61; the delivery guarantee for persistence (D87) and the fate of
    `prompts/engine.py` (D76) were settled on 2026-11-09.
  - [x] 8.1 The conformance suite of the parser
    - Turn the reference examples (four routers, seven prompts, nine flows; drafted in `.agents/tasks/uxui-dsl-examples.md`) into fixtures under
      `tests/fixtures/skye/`, and the table of load-time errors of `design.md` into a parametrized test: every version 1 example must parse and
      validate, every version 2 example must be rejected with the "not available in this version" message, and every row of the error table must give
      the stated message with the file, line and column.
    - Evidence: `tests/fixtures/skye/` (`routers.skye` R1-R4, `prompts.skye` P0-P2, `flows.skye` F1-F5 and F8, `f7.skye`, `f9.skye` the version 1 variant, `v2/` F6 and P3-P6), `tests/unit/dsl/test_conformance.py`. The error table is a Python table in that test (source, line, column, message); the "Wirte" typo replaces the table's `"B"`, and the run-time row (`env.X is not set`) is not a check-time error.
    - _Requirements: 19.1, 19.2; D50; D51_
  - [x] 8.2 The grammar, as a wiki page
    - Write the grammar in EBNF from the syntax page of `design.md` as `docs/base/skye-language.md` (front matter, linked from the `base` section index),
      with the block kinds, the references and prefixes, the expression grammar and the allowed functions; a `.skye` example in it passes `skye check`.
    - Evidence: `docs/base/skye-language.md` (linked from `docs/base/index.md`); `tests/unit/dsl/test_docs_examples.py` runs `check_text` over every `skye` block of `docs/` and `README.md`.
    - _Requirements: 19.1; D50; D55; D57_
  - [x] 8.3 `skye check` and the JSON Schema of the blocks
    - Provide `skye check <file>` (an entry point that reads the file, calls the parser and the block validators and prints every error with file, line,
      column, reason and fix, written to be pasted back to a model) and ship the JSON Schema of the `router`, `flow` and `prompt` blocks generated from the
      block dataclasses. A test runs `skye check` over every `.skye` block in `docs/`, `examples/` and `README.md` (Property 17).
    - Evidence (parser and command line side): `src/skye/utils/cli.py` (`skye check FILE...`, `--registry`, `--schema`; console script `skye = "skye.utils.cli:main"` in `pyproject.toml`), `src/skye/base/dsl/schema.py`; `tests/unit/dsl/test_skeletons_cli_schema.py`. `tests/unit/dsl/test_docs_examples.py` runs `skye check` over the blocks of `docs/` and `README.md` and over every `.skye` file of `examples/` (`router_config.skye`, `router_config_simple.skye`).
    - _Requirements: 19.2, 19.4; D61_
  - [x] 8.4 The loading API
    - `skye.load(path)`, `Flow.from_file(path, name=..., registry=...)` and the router's `from_file(path, name=...)`: the same `path`, errors with file, line
      and column, and `name` optional when the file holds one block of the kind (Property 16). The class names (`Router` against `ModelRouter`, `Flow`
      at the top level or in `skye.flows`) are settled with the owner first; see `design.md`, "Loading".
    - Done without a runtime (owner's answer on D61: the flow runtime is not built now): `skye.load(path, *, registry_names=None)` returns the `Document` or raises `ConfigurationError` with every `file:line:column reason fix`; `skye.flows.Flow` has `from_file(path, *, name=None, registry=None)`, `from_text(text, *, name=None, registry=None, filename=None)`, `.spec`, `.name`, `.registry`, `.check()`, `.to_text()` and `.run(...)`, which raises `NotImplementedError` that says the runtime is not built and points to `3-runtime-flows`. `skye.load` and `skye.Flow` are lazy names of `skye/__init__.py`. `ModelRouter.from_file(path, name=...)` already existed. `skye.Router` is not added: D39 keeps it out and `test_guessable_names.py` lists it as `known_missing`; the docs name `ModelRouter`.
    - Evidence: `src/skye/utils/skye_files.py` (`load`, `diagnostics_error`), `src/skye/flows/flow.py`, `src/skye/flows/__init__.py`, `src/skye/__init__.py`; `tests/unit/flows/test_loading.py` (load ok and with errors, name optional with one flow and required with several, registry names, `from_text`, `run` pointer, no import of another runtime component, `import skye` loads neither `skye.flows` nor `skye.base.dsl`); skill `references/python-api.md` ("Loading a file"; "Not built yet" keeps only running a flow) and `docs/base/skye-language.md` ("Loading from Python"). Still open here: the runtime itself (`3-runtime-flows`).
    - _Requirements: 19.2, 19.5; D61_
  - [x] 8.5 `.gitattributes`
    - Add `.gitattributes` with `*.skye linguist-language=HCL` so GitHub highlights the files until a dedicated grammar exists.
    - Evidence: `.gitattributes` (`*.skye linguist-language=HCL`).
    - _Requirements: 19.1; D61_
  - [x] 8.6 Convert the router examples and the YAML tests to `.skye`
    - When the parser exists, rewrite the router examples under `examples/routing/` and the YAML router tests as `.skye` files (the `router` block is the
      reference format; JSON and YAML files stay readable), including the shorthand `route "x" = [...]`, the fallback written inside the route and the
      renamed duration fields (`cooldown`, `retry_after`). Examples stay within the size and plain-output tests of group 5.
    - Evidence: `examples/routing/router_config.skye` and `router_config_simple.skye` (`skye check` ok; shorthand and the fallback inside the route are covered by `tests/fixtures/skye/routers.skye`, `retry_after` is kept with a comment that the router does not apply it yet), `examples/routing/skye_config_example.py` (offline, 25 lines), `tests/unit/router/test_router_examples_equivalence.py` (the old YAML as data in `tests/fixtures/legacy_router_yaml/*.json` against the router built from the `.skye`: routes, targets, strategies, fallbacks, retry and allowed-fails policies, cooldown, pre-call checks equal; only `priority` and `cost_per_1k_*` were dropped, the router never read them), `tests/unit/router/test_router_config_model.py`, `test_router_from_config.py`, `test_sample_configs.py`; `tests/examples`, `tests/budget/test_example_*` pass.
    - _Requirements: 17.2, 17.3, 19.3; D59_

  - [x] 8.7 Skeleton generators and `skye new`
    - `skye new router|flow|prompt NAME [--template T] [-o file.skye] [--force]` and `skye new --list`, on top of `skye.base.dsl.skeleton` (text only): small starting files derived from the reference examples, each passing `skye check`, with `# CHANGE ME` marks and no version 2 syntax.
    - Evidence: `src/skye/base/dsl/skeletons.py`, `src/skye/utils/cli.py`; `tests/unit/dsl/test_skeletons_cli_schema.py`; documented in `docs/base/skye-language.md`.
    - _Requirements: 19.1; D61_

  - [x] 8.8 The Claude skill that ships with the package (decision D64; Requirement 54.14)
    - The skill is in the official layout of the skill-creator: a minimal `SKILL.md` (33 lines: what to do first, a table that says which reference to read) and small files in `references/` (`cli`, `language`, `router`, `flow`, `prompt`, `python-api`, `rules`), with `evals/evals.json` (7 test prompts with expectations) and `evals/trigger_evals.json` (16 trigger queries, 8 that should trigger and 8 near misses). `skye skill install [--scope user|project] [--dir DIR] [--force]` copies `SKILL.md` and `references/` (not `evals/`, as the official packager does), `skye skill print [NAME]` and `skye skill path` (`src/skye/utils/skill.py`, `src/skye/utils/cli.py`); the rule to update it with every change of the command line, the grammar, the public API or the rules is in `.kiro/steering/00-rules.md`.
    - Evidence: `src/skye/utils/claude_skill/skye/` (`SKILL.md`, `references/`, `evals/`), `src/skye/utils/skill.py`; `tests/unit/dsl/test_claude_skill.py` (the layout and the frontmatter follow the official rules and the official `quick_validate.py` accepts the skill; `SKILL.md` stays minimal and links every reference; the evals follow the official schema; the references name only commands, block kinds, strategies, prefixes and functions that exist and their `skye` examples pass `skye check`; install is idempotent, skips `evals/` and refuses to replace a different file without `--force`; the rule is written in the steering file).
    - The skill must change when Skye changes: tests read the live command line, the block models, the language keywords and the public functions and fail when `references/` lacks one (`test_every_command_line_option_is_in_the_cli_reference`, `test_every_router_field_is_in_the_router_reference`, `test_every_flow_field_and_branch_is_in_the_flow_reference`, `test_every_prompt_field_and_kind_is_in_the_prompt_reference`, `test_every_version_2_word_is_named_as_not_available`, `test_every_public_function_of_the_parser_package_is_in_the_python_reference`); the installer records the version and a hash of each file in `.skye-skill.json`, replaces an unedited skill when the package changes, keeps an edited file unless `--force`, removes files that a newer package dropped, and `skye skill status` reports up to date, outdated or edited (exit 1); `CONTRIBUTING.md` has the paragraph. When they first ran, these tests found three real gaps in the skill (`-t`/`--output`, `backoff`, `separator`), now fixed.
    - Not run yet: the official eval loop (each prompt with the skill and without it, graded, shown in the review viewer) and the trigger-description optimisation (`run_loop.py`); both need the skill-creator scripts and many model calls, so they are left to run on request.
    - Keep it current: when 8.4 (the loading API) and the flow runtime are built, remove the "not built yet" line of the skill and show `Flow.from_file` and `skye.load` with an example.
    - _Requirements: 54.14; D64_

  - [ ] 8.9 `skye new plugin <kind> <name>` (O74, option a): writes the Python skeleton of a plugin of one of the nine kinds from the examples in `examples/plugins/`, with the `pyproject.toml` of its entry point; planned and not started (owner, 2026-11-13: not now)
    - _Requirements: 19.1; D111_

- [x] 9. Remove YAML (decision D62)
  - Note: the library reads no YAML. The router must read a `.skye` file first (8.4) so the YAML files can be rewritten; PyYAML leaves last, because the tests read YAML until they are converted.
  - [x] 9.1 The router reads a `.skye` block
    - Add `ModelRouter.from_file(path, name=...)`: read the text, call the parser in `base/dsl`, turn the `RouterSpec` into the router configuration
      (`RouteConfig`, `ModelTarget`, `FallbackConfig`, retry and allowed-fails policies), expanding the shorthand `route "x" = [...]` and
      `env.NAME`. Same errors as the parser (file, line, column). This is the router half of 8.4.
    - Evidence: `ModelRouter.from_file`, `load_router_config`, `router_spec_to_config` in `src/skye/router/skye_file.py`; `tests/unit/router/test_router_file.py` (positions of errors, shorthand, `env.NAME`).
    - _Requirements: 19.5, 20.3; D59; D62_
  - [x] 9.2 Rewrite the three YAML files
    - `examples/routing/router_config.yaml` and `router_config_simple.yaml` become `.skye` files; `tests/fixtures/sample_config.yaml` becomes JSON
      (it is a library configuration, not a router); `examples/routing/yaml_config_example.py` becomes `skye_config_example.py`. The pre-conversion
      files are the equivalence cases: the router built from each `.skye` file equals the one built from the old YAML (compare once, then delete the YAML).
    - Evidence: the two router files are `.skye` (see 8.6) and the YAML files are deleted; `tests/fixtures/sample_config.yaml` is JSON (`sample_config.json`); `skye_config_example.py` replaces `yaml_config_example.py`; the equivalence was proved by `tests/unit/router/test_router_examples_equivalence.py` before the deletion and stays as a test.
    - _Requirements: 17.2, 20.3; D62_
  - [x] 9.3 Reject YAML with a clear error
    - `ConfigLoader.load`, the router loader and the gateway reject a `.yaml` or `.yml` file with a `ConfigurationError` that names `.skye` and JSON and
      says the file must be rewritten; a test per loader. Remove `_yaml()`, `load_router_config`, the YAML branch of `ConfigLoader` and
      `ModelRouter.from_yaml`; the gateway reads OpenAPI in JSON only.
    - Evidence: `reject_yaml` in `src/skye/base/config.py` (used by `ConfigLoader.load`, `ConfigLoader._load_from_file` and `load_router_config`); `tests/unit/config/test_no_yaml.py` and `test_config_loader.py::test_config_loader_rejects_yaml` (ConfigLoader), `tests/unit/router/test_router_file.py` (router: `.yaml`, `.yml`, `.YAML` name `.skye` and JSON); `_yaml()`, the YAML branch and `from_yaml` are gone (`rg` finds no YAML import or call in `src/skye`); `tests/unit/config/test_yaml_extra.py` is deleted, `test_config_loader.py` and `test_env_var_substitution.py` use JSON. The gateway has no loader yet (`skye.gateway` is a stub that raises `ImportError`), so there is nothing to reject: the gateway spec reads OpenAPI in JSON only and adds its test with its loader.
    - _Requirements: 20.1; 54.12 of steering; D62_
  - [x] 9.4 Remove the extra and the dependency
    - Remove the extra `yaml` and `pyyaml` from `all` and from the dev group of `pyproject.toml`, `[extras.yaml]` and the `yaml` entries of `budgets.toml`, the
      `yaml` mapping in `tests/budget/test_extras_footprint.py`, the YAML job of `.github/workflows/budgets.yml`, and the `skyeai[memory,yaml]` line of the
      package docstring. A test fails when `yaml` is imported anywhere in `src/skye`.
    - Evidence: `pyproject.toml` (no `yaml` extra, no `pyyaml` or `types-PyYAML` in `all` or `dev`), `budgets.toml` (no `[extras.yaml]`; `yaml` stays in `forbidden_at_import`), `tests/budget/test_extras_footprint.py` (mapping removed; it passes), `.github/workflows/budgets.yml` (job removed), `src/skye/__init__.py` (docstring); `tests/unit/config/test_no_yaml.py` fails when any module of `src/skye` imports `yaml` and when `import skye` loads it; `tests/budget` passes. `uv.lock` was not regenerated (no network): run `uv lock`.
    - _Requirements: 20.2; 7.12 of steering; D62_
  - [x] 9.5 Documentation and tests
    - Rewrite the YAML sections of `docs/getting-started.md`, `docs/base/configuration.md`, `docs/router/overview.md`, `README.md`, `examples/README.md`,
      `examples/routing/README.md` and `examples/basic/configuration.py` for `.skye` and JSON; convert `tests/unit/router/test_yaml_router_config.py`,
      `test_router_yaml_integration.py` and `tests/unit/config/test_yaml_extra.py` (the last is replaced by the rejection test of 9.3); `.skye` blocks in
      the documentation pass `skye check` (Property 17).
    - Evidence: `docs/getting-started.md`, `docs/base/configuration.md` (JSON), `docs/router/overview.md` (a `skye` block that passes `skye check`), `docs/router/routing-guide.md`, `README.md`, `examples/README.md`, `examples/routing/README.md`, `examples/basic/configuration.py` (JSON), `tests/README.md`, `tests/fixtures/README.md` and the READMEs under `tests/`; `tests/unit/dsl/test_docs_examples.py`, `tests/budget/test_install_lines.py` pass.
    - _Requirements: 20.1; 24.3 of steering; D62_
  - [x] 9.6 Write objects back: `to_text`, `ModelRouter.to_config` and `ModelRouter.to_skye` (decision D65; Requirement 54.15)
    - `skye.base.dsl.to_text(spec_or_document)` writes routers, flows and prompts as `.skye` text (`src/skye/base/dsl/emit.py`; `format_duration` in `specs.py`); `ModelRouter.to_config(include_secrets=False)` and `to_skye(name=None, include_secrets=False)` (`src/skye/router/model_router.py`, `config_to_router_spec` in `src/skye/router/skye_file.py`). A way out of the YAML files and of a router built in Python: write `router.to_skye("main")` to a file. Secrets are not exported: `ModelTarget.env_refs` remembers a field written as `${NAME}`, an API key given in clear is left out unless `include_secrets=True`, and `ModelRouter.from_file` keeps `${NAME}` in the target string fields (`load_router_config(..., keep_target_references=True)`) so that the reference survives. Only retry and cooldown policies that differ from the defaults are written.
    - Evidence: `tests/unit/dsl/test_emit.py` (every fixture of the language, router, flow and prompt, survives the round trip and a second writing gives the same text, the text passes `skye check`, strings are escaped, `format_duration` and `parse_duration` are inverse); `tests/unit/router/test_router_export.py` (the text passes the checker and builds the same router, `to_config` rebuilds the router, no secret in the text or the dictionary by default, `env.NAME` comes back as `env.NAME`, `include_secrets` writes a key given in clear, defaults are left out, a router built in Python is written too); the skill (`references/python-api.md`) names them and the coverage test of the skill passes.
    - Use it for 9.2: convert the three YAML files with it once (build the router from the old file, write `to_skye`, check the equivalence, delete the YAML).
    - _Requirements: 54.15; D65_

- [x] 10. Language tools: comments, front matter, `skye fmt`, `skye prompt`, the editor (decisions D71 to D74; Requirements 54.16 to 54.20 and 55)
  - [x] 10.1 Comments `#`, `/* */`, `/** **/` and front matter in TOML, in the lexer, parser, `to_text` and the prompt loader
    - Evidence (2026-11-08): `src/skye/base/dsl/lexer.py`, `parser.py`, `metadata.py`, `tree.py`, `emit.py`; `tests/unit/dsl/test_comments.py`, `tests/unit/dsl/test_metadata.py`; `tests/unit/prompts/test_bundled_conventions.py` (comment convention in the bundled files).
    - _Requirements: 54.16, 54.17; D71_
  - [x] 10.2 `skye fmt` (text formatter, `--check`, `-`, recursive search, `--exclude`, `.skyeignore`) and formatted `skye new`
    - Evidence (2026-11-08): `src/skye/base/dsl/fmt.py` (`format_text`), `src/skye/utils/cli.py` (`_skye_files`, `_ignore_globs`, `SKYEIGNORE`), `.skyeignore`; `tests/unit/dsl/test_fmt.py` (including `test_cli_fmt_searches_the_current_folder_recursively`, `test_cli_fmt_takes_a_folder_argument`); `uv run skye fmt --check src/skye/prompts/templates examples` exits 0.
    - _Requirements: 54.18; D71_
  - [x] 10.3 `skye check --format json` and standard input with `--stdin-filename`
    - Evidence (2026-11-08): `src/skye/utils/cli.py` (`_check`); `tests/unit/utils/test_vscode.py`.
    - _Requirements: 54.19; D72_
  - [x] 10.4 Described and structured prompt variables in the grammar, the checker and `to_text`; `skye prompt list|info`
    - Evidence (2026-11-08): `src/skye/base/dsl/parser.py`, `build.py`, `specs.py`, `emit.py`, `shapes.py`, `info.py`; `tests/unit/dsl/test_variable_descriptions.py`, `test_structured_variables.py`, `tests/unit/utils/test_cli_prompt.py`. The form of the default is confirmed by D83.
    - _Requirements: 54.20; D73_
  - [x] 10.5 The VS Code extension and `skye vscode`
    - Evidence (2026-11-08): `src/skye/utils/vscode_extension/` (`extension.js`, `package.json`, grammar, README), `src/skye/utils/vscode.py`; `tests/unit/utils/test_vscode.py`, `tests/unit/test_vscode_extension_files.py`; `docs/base/editor.md`. Not verified here: the extension running inside VS Code (the tests read its files and the CLI, not the editor).
    - _Requirements: 55.1, 55.2, 55.3, 55.4; D72_
  - [x] 10.6 Docs and skill follow the language
    - Evidence (2026-11-08): `docs/base/skye-language.md` (comments, front matter, `skye fmt`, `output`), `docs/base/editor.md`; skill `references/cli.md`, `language.md`, `output.md`, `prompt.md`, `router.md`, `python-api.md`; `tests/unit/dsl/test_claude_skill.py`, `tests/unit/dsl/test_docs_examples.py`.
    - _Requirements: 54.14; D64_
  - [x] 10.7 A public import for the checker and the formatter, so an example can show a mistake and a fix without `skye.base.*`
    - Note (2026-11-09): settled by D78, a `skye.dsl` facade (`check_text`, `format_text`, `Diagnostic`, `FormatError`); then `examples/prompts/validation.py` imports it instead of its workaround. Before: `examples/prompts/validation.py` works around it with the `ValidationError` of `load_prompt`. No code before it is decided.
    - Evidence (2026-11-09): `src/skye/dsl.py` (re-exports `check_text`, `format_text`, `Diagnostic`, `FormatError`, `to_mermaid`; added to the facades of `tests/budget/test_facade_purity.py` and to the map of `tests/budget/test_import_matrix.py`); `examples/prompts/validation.py` uses `check_text` and `format_text` instead of its workaround.
    - _Requirements: 7.14, 7.15; D34, D78_
  - [x] 10.8 `to_mermaid(spec) -> str` in `base/dsl` for flows and routers (deterministic; every step, edge, `choice` branch with its `when` text, `parallel` branches and `join`, dotted `on_error` and `on_timeout`, routes and fallback chains) and `skye render FILE [--name] [--stdout] [--fence] [-o] [--direction]`; tests on the structure of the text, no Mermaid library; public in `skye.dsl`; the skill names the command
    - Evidence (2026-11-09): `src/skye/base/dsl/mermaid.py` (`to_mermaid`, exported by `skye.base.dsl` and `skye.dsl`); `skye render` in `src/skye/utils/cli.py`; `tests/unit/dsl/test_mermaid.py` (nodes, edges, choice labels, parallel subgraph and join, escaping, determinism, routers and fallbacks, every fixture renders, a prompt is refused) and `tests/unit/utils/test_cli_render.py`; skill `references/cli.md` and `python-api.md`; `docs/base/skye-language.md`.
    - _Requirements: 54.21, 54.14; D88, D64_

## Notes

- Specs outside this one name the things D36 to D45 rename or remove: `CompletionRequest`/`CompletionResponse` (`0-base-base`, `1-adapters-models`,
  `0-base-structure`, steering `11-design.md`, `00-rules.md`), `MCPClientPort` (`2-services-tools`), `StorageAdapterInterface` and the other removed
  Ports (`0-base-structure`), `ExecutableCapabilityCall` and `get_capability_calls` (`0-base-base`, `2-services-tools`). The change that does 3.5,
  3.6, 3.11 and 4.2 updates those lines in the same commit; their evidence of work already done keeps the old name with a "renamed in D3x" note.
- The open decisions O24 to O33 are taken (D36 to D45 of `.kiro/steering/12-decisions.md`); each task cites its decision. Where a task
  text still says "once O.. is decided", read the decision as taken and follow it.
- `models:8.2` (pydantic structured-output examples) and `prompts:5` (stale `examples/prompts/`) are tracked in their
  own specs and are not duplicated here, even though they appear in the audit (findings behind Requirement 24's pydantic/D20
  contradictions).
- Group 1 is done; its evidence is the committed facades and `tests/budget/test_public_imports.py`.
- Group 8 (the `.skye` language) is not built: it waits for the parser. D49 (no third-party dependency) is taken; the code that still imports pydantic
  and tenacity is migrated in a separate task, and the budget tests fail by design until it is done.

## Task Dependency Graph

See `design.md`, "Task Dependency Graph", for the wave ordering (facades and the first tests run first; allowlist-clearing repairs
follow; decision-blocked tasks are the last wave before the checkpoint).
