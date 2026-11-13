# Implementation Plan: teams

## Overview
Milestones in build order for the `teams` component (codename front): members and roles, cycle detection, supervisors, the three
strategies, the `Team` runnable, and packaging. Status is judged from the code in `src/skye/teams` (a placeholder) and the `Runnable`
Port in `src/skye/base/interfaces`; nothing of the component is built, so every task but the Port and the matrix is open. Each task
cites the steering requirement numbers it satisfies (`Requirement N.k` of `10-requirements.md`) or the decision it honors. Task IDs
cited from other documents are `teams:N.k`. The names and defaults listed under "Open points" of `design.md` are the owner's to
confirm before task 2.

## Tasks
- [x] 1. What exists
  - [x] 1.1 The `Runnable` Port, the placeholder package and the import-matrix rule that keeps `teams` to `base`
    - Evidence: `src/skye/base/interfaces/runnable.py`, `src/skye/teams/__init__.py`; `tests/budget/test_import_matrix.py`, `tests/unit/test_placeholder_packages.py`.
    - _Requirements: 5.1, 5.4; D40_

- [ ] 2. Members and cycles
  - [ ] 2.1 `TeamMember` (name, role, runnable, metadata) with the role as a free string; unique names; a member that is not a `Runnable` is a validation error naming the field
    - _Requirements: 49.1, 49.2, 5.2; D8_
  - [ ] 2.2 The cycle check: a visited set carried in a `contextvars` variable and a depth bound (default 100), run at construction and at run time, raising an error that names the path
    - _Requirements: 49.5, 5.3_
  - [ ] 2.3 Tests: the same `Runnable` with two roles in two teams, duplicate names, a team inside a team, a direct cycle, a transitive cycle, the bound
    - _Requirements: 49.1, 49.5, 23.2_

- [ ] 3. Supervisors
  - [ ] 3.1 `SupervisorInterface` (async `next_step`, the synchronous form runs it) and the fixed-order supervisor
    - _Requirements: 49.3_
  - [ ] 3.2 The decision supervisor over a decision model received as a `Runnable`, with the model, prompt and threshold given by the caller and a required failure mode; `prompts` is passed in as a callable, never imported
    - _Requirements: 49.3, 9.8; D7_
  - [ ] 3.3 Tests with a fake decision model: a choice, an unknown name, the model unavailable under each failure mode, the threshold
    - _Requirements: 49.3, 23.2_

- [ ] 4. Strategies
  - [ ] 4.1 Parallel: the same input to the selected members under `asyncio.TaskGroup`, outputs in member order, a setting to cancel the others or continue
    - _Requirements: 49.4_
  - [ ] 4.2 Hand-off: members one after another, the supervisor may skip or repeat, a required bound on hand-offs
    - _Requirements: 49.4_
  - [ ] 4.3 Vote: the same input to the members in parallel, majority or a caller function, a tie rule setting, an optional normalizing function
    - _Requirements: 49.4_
  - [ ] 4.4 Tests for order, cancellation, continue, the hand-off bound, a vote and a tie
    - _Requirements: 49.4, 23.2_

- [ ] 5. The team
  - [ ] 5.1 `Team` satisfying `Runnable` (`invoke`, `ainvoke`) with a supervisor and a strategy, returning the output; `TeamResult` and `MemberRun` record who ran and in which order
    - _Requirements: 49.1, 49.3, 5.1_
  - [ ] 5.2 A team as the member of another team, and as the step of a flow built in the test (no import of `flows` in `teams`)
    - _Requirements: 5.1, 5.4_
  - [ ] 5.3 Run errors keep the member name and the cause; configuration errors raise `ConfigurationError` at construction
    - _Requirements: 18.1_

- [ ] 6. Packaging, docs and budgets
  - [ ] 6.1 Make `skye.teams` importable with its real exports (D40: the placeholder `ImportError` goes); standard library only, no extra
    - _Requirements: 7.1, 7.3; D40_
  - [ ] 6.2 Check that `teams` imports only `base` (and `prompts` when enabled) and nothing from `models`, `agents`, `flows` or the four optional services
    - _Requirements: 2.2, 4.1, 5.4_
  - [ ] 6.3 Entry in `budgets.toml` for import time; the docs page `docs/teams/` and a runnable example with fake members under `examples/teams/`
    - _Requirements: 7.5, 15.5, 24.2, 24.4_
  - [ ] 6.4 If a supervisor or a group chat chooses the next member by a call to a model, bring back its prompts (`agent_supervisor_router`, `agent_groupchat_manager` and the others it needs) from `examples/prompts/catalogue/` into `src/skye/prompts/templates/`, as a move of the file with a test; a supervisor that uses a decision model needs none (D118)
    - _Requirements: 49.3; D118_
