# Implementation Plan: tools

## Overview

Milestones in build order for the `tools` component (codename updraft): the capability interface and schema first, then the
registry and the capability kinds (local function, remote API, decorator), the call handler and errors, the tri-faceted MCP
client with its single conversion boundary and its built-in/`fastmcp` implementations, and finally the open conformance work
left by the migration. Status is judged from the code in `src/skye/tools` and the tests in `tests/unit/tools` and
`tests/differential/test_mcp_differential.py`, not from the former `capability-support` checkboxes. Each task cites the
steering requirement numbers it satisfies (`Requirement N.k` of `10-requirements.md`) or the decision it honors. Task IDs
cited from other documents are `tools:N.k`.

## Tasks

- [x] 1. Capability interface and schema
  - [x] 1.1 `CapabilityInterface` (get_schema, execute, aexecute)
    - Evidence: `src/skye/base/interfaces/capability.py` (the base Port, re-exported by `skye.tools` since 8.1); `tests/unit/tools/test_capability_interface.py`.
    - _Requirements: 16.1, 16.2_
  - [x] 1.2 `CapabilitySchema` (name, description, parameters, returns)
    - Evidence: `src/skye/base/interfaces/capability.py` (frozen, name and description stripped, blank rejected; `src/skye/tools/schema.py` removed in 8.1); `tests/unit/tools/test_capability_schema.py`.
    - _Requirements: 16.1_
  - [x] 1.3 Move `CapabilitySchema` / `CapabilityResult` / `CapabilityCall` off pydantic to dataclasses (D24)
    - Evidence (2026-11-08): `CapabilitySchema`, `CapabilityResult` and `CapabilityCall` are `Validated` dataclasses and no module of `src/skye/tools` imports pydantic; `tests/unit/tools/test_mcp_conformance.py::test_no_module_of_tools_imports_pydantic`, `test_capability_types_are_validated_dataclasses`, `test_invalid_data_raises_validation_error_with_field_context`.
    - _Requirements: 16.1; D24_

- [ ] 2. Registry and capability kinds
  - [x] 2.1 `CapabilityRegistry` behind the registry Port (register, get, list, namespaces, search)
    - Evidence: `src/skye/tools/registry.py`; `tests/unit/tools/test_capability_registry.py`.
    - _Requirements: 6.1, 6.2, 16.2_
  - [x] 2.2 `LocalFunctionCapability` (signature + docstring -> schema)
    - Evidence: `src/skye/tools/local_function.py`; `tests/unit/tools/test_local_function_capability.py`.
    - _Requirements: 6.1, 6.2_
  - [x] 2.3 `RemoteAPICapability` over `base/http.py` (no third-party HTTP client)
    - Evidence: `src/skye/tools/remote_api.py` (imports `skye.base.http`); `tests/unit/tools/test_remote_api_capability.py`.
    - _Requirements: 6.1, 6.2, 7.3, 10.7_
  - [x] 2.4 `@capability` decorator
    - Evidence: `src/skye/tools/decorator.py`; `tests/unit/tools/test_capability_decorator.py`.
    - _Requirements: 6.1, 22.1_

- [ ] 3. Capability call handling and errors
  - [x] 3.1 `CapabilityCallHandler` (provider-agnostic parse/validate/execute/format)
    - Evidence: `src/skye/tools/capability_call_handler.py`, `src/skye/tools/capability_models.py` (`CapabilityResult`); `tests/unit/tools/test_capability_call_handler.py`, `test_capability_models.py`.
    - _Requirements: 9.10, 16.2_
  - [x] 3.2 `CapabilityError` hierarchy on `SkyeError` with kept context
    - Evidence: `src/skye/tools/exceptions.py`; `tests/unit/tools/test_exceptions.py`.
    - _Requirements: 18.1_
  - [x] 3.3 Capability terminology ("Capability", not "Tool") in types and exports
    - Evidence: `src/skye/tools/__init__.py` exports (`CapabilityInterface`, `CapabilityCall`, `CapabilityResult`, ...); `tests/unit/tools/test_capability_exports.py`.
    - _Requirements: 22.1, 22.2_
  - [x]* 3.4 Structured events for capability calls, results and errors
    - Evidence: structured `logger.info/error(..., extra={...})` in `src/skye/tools/registry.py` and `capability_call_handler.py`.
    - _Requirements: 18.3_

- [x] 4. Tri-faceted MCP client and the boundary
  - [x] 4.1 `MCPClientInterface` and `SkyeMCPClient` (stdlib JSON-RPC over HTTP, consume-only)
    - Evidence: `src/skye/tools/mcp_client.py` (`MCPClientInterface`, `SkyeMCPClient`, `MCPToolCapability`); `tests/unit/tools/test_mcp_client.py`, `test_mcp_stdlib_prototype.py`.
    - _Requirements: 10.1, 10.2_
  - [x] 4.2 Single conversion boundary `mcp_boundary.py` (stdlib only, reject malformed)
    - Evidence: `src/skye/tools/mcp_boundary.py`; `tests/budget/test_boundary_rule.py` (`test_mcp_boundary_has_no_third_party_import`, `test_mcp_boundary_returns_skye_types_for_dict_and_library_objects`).
    - _Requirements: 10.1, 10.6_
  - [x] 4.3 `create_mcp_client` explicit `impl`; `FastMCPClient` behind the same Port (lazy fastmcp)
    - Evidence: `src/skye/tools/mcp_client.py` (`create_mcp_client`), `src/skye/tools/mcp_fastmcp.py` (`FastMCPClient`, lazy `missing_extra("fastmcp", extra="mcp")`).
    - _Requirements: 10.2, 10.3, 10.4; D15, D16_
  - [x]* 4.4 Differential tests keep both clients equal
    - Evidence: `tests/differential/test_mcp_differential.py` (skips when `fastmcp` absent).
    - _Requirements: 10.4_

- [ ] 5. Checkpoint
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Migration conformance
  - [x] 6.1 Move `Resource` behind a new resource Port in `base` (D26)
    - Evidence (2026-11-08): `src/skye/base/interfaces/resource.py` (`ResourceProviderInterface`, `Resource`), exported by `skye.base.interfaces` and `skye.interfaces`; `MCPClientInterface` inherits the Port (`src/skye/tools/mcp_client.py`) and `src/skye/tools/mcp_resource.py` re-exports it; `tests/unit/tools/test_mcp_conformance.py::test_resource_is_the_base_type_everywhere`, `test_every_mcp_client_implements_the_resource_port`, `test_a_plain_class_satisfies_the_resource_port`.
    - _Requirements: 10.5; D26_
  - [x] 6.2 MCP prompt facet returns `base` messages, not `PromptBuilderInterface` (D26)
    - Evidence (2026-11-08): `tests/unit/tools/test_mcp_conformance.py::test_get_prompt_returns_base_messages`, `test_tools_imports_no_prompts_module`, `test_no_tools_class_implements_a_prompt_port`.
    - _Requirements: 10.5, 10.1; D26_
  - [x] 6.3 Remove the legacy MCP probes (`LEGACY_TOOLS_PROBES`)
    - Evidence (2026-11-08): `src/skye/tools/mcp_capability.py` and `mcp_server_client.py` are deleted, their exports are gone from `src/skye/tools/__init__.py` (`tests/unit/tools/test_capability_exports.py` asserts `MCPCapability` and `MCPServerClient` are absent) and `LEGACY_TOOLS_PROBES` is removed from `tests/budget/test_boundary_rule.py`; `tests/unit/tools/test_mcp_conformance.py::test_only_mcp_fastmcp_imports_fastmcp`.
    - _Requirements: 10.7_
  - [x] 6.4 Fix the order-dependent MCP unit tests
    - Evidence (2026-11-08): the two test modules that set `sys.modules["fastmcp"]` (`test_mcp_capability.py`, `test_mcp_server_client.py`) are deleted with the modules they tested; `grep` finds no module-level `sys.modules["fastmcp"]` assignment in `tests/`.
    - _Requirements: 10.4_
  - [x] 6.5 Stop gating CI on the size of the `mcp` extra (D67, closes O23)
    - Evidence: `budgets.toml` (no `[extras.mcp]`; `not_gated = ["mcp"]` in `[extras_policy]`), `.github/workflows/budgets.yml` (no `mcp` footprint job), `tests/budget/test_policy.py` (`not_gated` accepted, never with a budget), `tests/budget/test_workflow_matrix.py` (unchanged, passes), `docs/budgets.md`; `tests/budget/test_boundary_rule.py` still allows `fastmcp` only in `tools/mcp_fastmcp.py`. Done before 6.3, which is still open.
    - _Requirements: 7.10, 7.11, 15.1; D67_
- [ ] 7. Final checkpoint
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Fixes found by the documentation review (2026-11-11)
  - [x] 8.1 One `CapabilityInterface`/`CapabilitySchema` pair: the base Port, re-exported by `skye.tools`
    - Evidence (2026-11-11): `src/skye/tools/interface.py` and `src/skye/tools/schema.py` are removed; `src/skye/tools/__init__.py` re-exports the classes of `src/skye/base/interfaces/capability.py`, whose `CapabilitySchema` now carries the guarantees of the removed copy (frozen, name and description stripped, blank rejected); the `CapabilitySchema` and `CapabilityInterface` entries are gone from `KNOWN_DUPLICATES` (`tests/budget/test_unique_names.py`) and the two files from `tests/budget/test_extras_footprint.py`; `tests/unit/tools/test_doc_review_fixes.py::test_tools_reexports_the_base_port_types`, `test_registry_accepts_a_schema_built_from_skye_interfaces`, `test_list_schemas_returns_base_capability_schema`, `test_base_schema_keeps_the_tools_guarantees`.
    - _Requirements: 16.1, 16.11, 22.4_
  - [x] 8.2 `CapabilityRegistry.execute` and `aexecute` raise `CapabilityExecutionError` when the capability fails
    - Evidence (2026-11-11): `src/skye/tools/registry.py` (a `CapabilityError` from the capability, such as a validation error for bad arguments, passes through unchanged; any other exception becomes `CapabilityExecutionError` with the original as `__cause__`); `tests/unit/tools/test_doc_review_fixes.py::test_execute_failure_is_an_execution_error`, `test_aexecute_failure_is_an_execution_error`, `test_invalid_arguments_stay_a_validation_error`; `tests/unit/tools/test_capability_registry.py` (the two tests that expected `CapabilityValidationError` now expect `CapabilityExecutionError`).
    - _Requirements: 18.1, 18.2_
  - [x] 8.3 `@capability` schemas follow nested types, `Optional`, `Union`, `Literal` and the `Args:` section; no call argument in the logs
    - Evidence (2026-11-11): `src/skye/tools/local_function.py` (`_type_to_json_schema`: `list[X]`, `set[X]`, `tuple`, `dict[str, X]` nested, `X | None` is `X` and not required, other unions `anyOf`, `Literal` `enum`; `_docstring_args` reads the Google-style `Args:` section into each parameter's `description`; with `schema_override` the capability and its errors use the overridden name; the logs of `LocalFunctionCapability` and `CapabilityRegistry` carry the capability name and the outcome, never the arguments); `tests/unit/tools/test_doc_review_fixes.py::test_nested_container_types`, `test_optional_is_the_inner_type_and_not_required`, `test_union_is_any_of`, `test_literal_is_enum`, `test_args_section_descriptions`, `test_schema_override_errors_name_the_overridden_capability`, `test_local_function_does_not_log_arguments`.
    - _Requirements: 6.1, 16.1, 18.3_
  - [x] 8.4 Documentation and example follow the fixes
    - Evidence (2026-11-11): the warnings about the two schema classes are removed from `docs/guides/extend/custom-capability.md` and `docs/guides/extend/index.md`; `docs/guides/tools/local-functions.md` documents the type mapping, the `Args:` descriptions, `CapabilityExecutionError` and the logs without arguments; `examples/capabilities/remote_api.py` reads the `error` status of the returned messages instead of catching an `OSError` that `aexecute_capability_calls` never raises (`docs/guides/tools/remote-apis.md` snippet range updated); `uv run mkdocs build --strict`, `tests/docs`, `tests/examples`.
    - _Requirements: 6.1, 16.10_

## Notes

- Tasks marked with `*` are optional (tests/observability) and can be skipped for a faster path.
- Status reflects the code in `src/skye/tools` and `tests/` at migration time, not the former `capability-support` checkboxes.
- `tools` carries no third-party library; `fastmcp` is the separate `mcp` extra, imported lazily only in `mcp_fastmcp.py`
  (design "Extras and budgets"; Requirement 10.7, 7.3).
- The open items at migration (1.3, 6.1 to 6.4) were closed on 2026-11-08 and ticked with their evidence. Milestones 2, 3, 5 and 7 stay
  unticked only because they hold the checkpoints, which are run in the final verification (the suite passes: see the final report of that day).

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["2.1", "2.2", "2.3", "2.4", "1.3"] },
    { "id": 2, "tasks": ["3.1", "3.2", "3.3", "3.4"] },
    { "id": 3, "tasks": ["4.1", "4.2"] },
    { "id": 4, "tasks": ["4.3", "4.4"] },
    { "id": 5, "tasks": ["6.1", "6.2", "6.3", "6.5"] },
    { "id": 6, "tasks": ["6.4"] },
    { "id": 7, "tasks": ["8.1", "8.2", "8.3", "8.4"] }
  ]
}
```
