# Implementation Plan: agents

## Overview
Milestones in build order for the `agents` component (codename cyclone): state and operations first, then hooks, then the loop, the
toolset and concurrency, resumption, the default agent with its providers, and packaging and tests. Status is judged from the code in
`src/skye/agents` (the agent-type registry and a `ReActAgent` stub) and the Ports in `src/skye/base/interfaces`, not from the former
`agent-runtime` text, which had no design or tasks. Each task cites the steering requirement numbers it satisfies
(`Requirement N.k` of `10-requirements.md`) or the decision it honors. Task IDs cited from other documents are `agents:N.k`. Open
decision O12 stays open: a task that depends on it takes the value as an argument. O11 and O13 are settled by D84, D85, D86 and D90.

## Tasks
- [x] 1. What exists
  - [x] 1.1 Agent-type registry (`register_agent_type`, `get_agent_type`) and the `ReActAgent` stub that satisfies `Runnable`
    - Evidence: `src/skye/agents/registry.py`; `tests/unit/agents/test_registry.py`.
    - _Requirements: 6.1, 39.4_
  - [x] 1.2 Ports the agent needs: `Runnable`, `ToolProvider` with `CapabilityContext`, authorizer, safety, observer, memory, event handler, and the capability primitive with `CapabilityStatus`
    - Evidence: `src/skye/base/interfaces/runnable.py`, `tool_provider.py`, `authorizer.py`, `safety.py`, `observer.py`, `memory.py`, `event_handler.py`; `src/skye/base/messages.py` (`CapabilityStatus`); `tests/unit/test_port_signatures.py`.
    - _Requirements: 4.1, 4.2, 16.10, 16.11; D42, D45_

- [ ] 2. State and operations
  - [ ] 2.1 `Operation` enumeration of the nine operations (run, step, toolset selection, model call, tool call, memory read, memory write, safety check, policy check)
    - _Requirements: 39.5, 39.8_
  - [ ] 2.2 `AgentState`, `RunResult`, `EndReason` and `Suspended` as dataclasses; the state round-trips through `json` and holds no live object
    - _Requirements: 42.4, 39.3, 43.1; D24, D45_
  - [ ] 2.3 Token and cost counting per run from the model responses, in the result
    - _Requirements: 42.13_

- [ ] 3. Hooks
  - [ ] 3.1 `HookContext` (state, operation, payload), the four pre outcomes (continue, modify, skip, deny) and the four post outcomes (keep, replace, retry, stop)
    - _Requirements: 39.7, 40.1, 40.2_
  - [ ] 3.2 `HookRegistry`: register and remove by operation name; pre hooks in registration order, post hooks in reverse; synchronous and asynchronous functions
    - _Requirements: 40.3, 40.4, 40.7_
  - [ ] 3.3 Fail open and fail closed per hook, with the defaults (closed for safety, policy and limits; open for observers); retry limit and per-hook time limit as arguments with the defaults of D84 (2 retries, 5 seconds)
    - _Requirements: 40.5, 40.6; D84_
  - [ ] 3.4 Restrict a hook to tools or models by name or tag
    - _Requirements: 40.8_
  - [ ] 3.5 Hook providers that register several hooks together, and the documented order: subclass override, instance hooks, providers
    - _Requirements: 40.7, 40.9_

- [ ] 4. The loop
  - [ ] 4.1 `AgentLoop` with model, `ToolProvider`, optional memory and optional hook providers; `invoke` (async, the `Runnable` method) and `run` (synchronous), one end reason per run
    - Note: maximum steps default 20 (D84).
    - _Requirements: 39.1, 39.2, 39.3; D43, D84, D90_
  - [ ] 4.2 Pre, post and error points around each operation, calling the error hooks when an operation fails
    - _Requirements: 39.5, 39.6_
  - [ ] 4.3 Event-handler calls at model calls, tool calls, steps and completion, handled as observers (errors swallowed, no payload change)
    - _Requirements: 40.10, 40.11_
  - [ ] 4.4 Model call through the model or router Port, using the router's fallbacks and retries before failing the operation
    - _Requirements: 42.10_
  - [ ] 4.5 Tool failure returned to the model as a `CapabilityMessage` with status `error`, a hook point that can stop the run, and a stop after a configurable number of consecutive failed steps
    - Note: per error type (D85): invalid arguments, tool exception, timeout and policy denial go back to the model; an exceeded limit or a configuration or credentials error stops the run; a hook can change either. Consecutive-failure limit default 3 (D84).
    - _Requirements: 42.11, 42.12; D84, D85_
  - [ ] 4.6 Streaming with checkpoints of the text: buffer, safety and policy hooks every window (default 500 characters) on all the text so far and on the complete answer; modes "hold" (default) and "show and retract" with a `retract` event; an `on_chunk` observer
    - _Requirements: 40.12; D86_

- [ ] 5. Toolset and concurrency
  - [ ] 5.1 Obtain tools only through the `ToolProvider`, at the toolset operation, at the start of a run, and when a hook or the model asks for different tools; the operation description is an argument or a callable
    - _Requirements: 42.1; O12_
  - [ ] 5.2 Work with the local `CapabilityRegistry` as `ToolProvider`, with no gateway
    - _Requirements: 42.2_
  - [ ] 5.3 Carry the scope token in the `AgentState` and send it with every call in the `CapabilityContext`, with the operation description
    - _Requirements: 42.3_
  - [ ] 5.4 Run several tool calls of one step concurrently with `asyncio` under a configurable limit, results in the order the model asked; no multiprocessing, no work after return
    - _Requirements: 42.9, 42.8_

- [ ] 6. Checkpoint, suspension and resumption
  - [ ] 6.1 Save a checkpoint through the `storage` Port at configurable points, after each step by default, when the caller turns checkpointing on (opt-in, also in Lambda)
    - _Requirements: 42.5; D85_
  - [ ] 6.2 Remaining-time function and margin: stop before the next step and return `Suspended` with the checkpoint identifier
    - _Requirements: 42.6_
  - [ ] 6.3 Resume from a checkpoint identifier
    - _Requirements: 42.7_

- [ ] 7. Default agent and providers
  - [ ] 7.1 Limits provider (steps, tokens, cost, time), on by default
    - _Requirements: 41.1, 41.2_
  - [ ] 7.2 Safety provider (the `safety` Port) and policy provider (the `authorizer` Port: principal, tool name as action, tool identifier as resource), each on automatically when its service is configured, failure mode closed
    - _Requirements: 41.1, 41.3, 40.5_
  - [ ] 7.3 Observability provider (event handler and observer Ports) and checkpointing provider
    - _Requirements: 41.1_
  - [ ] 7.4 `Agent` as an `AgentLoop` subclass with no copy of the loop and `hooks()` listing the active hooks in execution order; decide with the owner whether `ReActAgent` of the registry becomes this class
    - _Requirements: 39.4, 41.4_

- [ ] 8. Packaging, budgets and tests
  - [ ] 8.1 Standard library only for state, hooks and results; no third-party import at module level; `agents` stays in `known_empty` of `budgets.toml`; make the public surface importable (D40: `skye.agents` loses its placeholder where one exists)
    - _Requirements: 43.1, 43.2; D40_
  - [ ] 8.2 Entry in `budgets.toml` for import time and module count; values measured after the implementation, then fixed (D84)
    - _Requirements: 43.3; D84_
  - [ ] 8.3 Scripted model for tests in `tests/fixtures/` (returns prepared responses and tool calls)
    - Note: Requirement 43.4 says the library provides it and D38 keeps the demo model in `examples/`; the fixture goes in `tests/fixtures/` until the owner settles which rule wins.
    - _Requirements: 43.4; D38_
  - [ ] 8.4 Tests: each hook outcome, hook order, fail open and closed, suspension and resumption, concurrent tool calls, state round-trip, event handlers as observers, and the eight correctness properties of `design.md`
    - _Requirements: 43.5, 39, 40, 41, 42_
  - [ ] 8.5 Example `examples/agents/` that shows the loop with a hook and a local registry, runnable offline
    - _Requirements: 24.2, 24.4, 24.5_
  - [ ] 8.6 Bring back the prompts that the loop needs (for example `agent_tool`, and `agent_planner` if the loop plans) from `examples/prompts/catalogue/` into `src/skye/prompts/templates/`, as a move of the file with a test that it renders and passes `skye check`; no other prompt is bundled (D118)
    - _Requirements: 30.14; D118_
