# Implementation Plan: memory

## Overview
Milestones in build order for the `memory` component (codename dew): the entry model that exists, conversation memory, state memory,
entry memory with retrieval, and packaging. Status is judged from the code in `src/skye/memory` (only the `MemoryEntry` model) and the
Ports in `src/skye/base/interfaces`. Each task cites the steering requirement numbers it satisfies (`Requirement N.k` of
`10-requirements.md`) or the decision it honors. Task IDs cited from other documents are `memory:N.k`. Three open points of
`design.md` (the storage Port, the async names, the `memory` extra) are settled in steering before the tasks that depend on them.

## Tasks
- [x] 1. What exists
  - [x] 1.1 `MemoryEntry` (id, content, type, embedding, metadata, created_at) as a validated dataclass satisfying `MemoryEntryLike`
    - Evidence: `src/skye/memory/__init__.py`; `tests/unit/test_port_signatures.py`.
    - _Requirements: 52.1; D24_
  - [x] 1.2 The memory Port and the storage Port
    - Evidence: `src/skye/base/interfaces/memory.py`, `src/skye/base/interfaces/storage.py`; `tests/unit/test_port_docstrings.py`.
    - _Requirements: 52.1, 12.1_

- [ ] 2. Conversation and state memory
  - [ ] 2.1 `ConversationMemory`: append the messages of a session with an atomic position, load the last N or a token budget, namespaced keys, over any `StorageBackend`
    - _Requirements: 52.1, 12.1_
  - [ ] 2.2 `StateMemory`: read and write a JSON document per name and session, with a version to detect a concurrent write
    - _Requirements: 52.1_
  - [ ] 2.3 Tests against `InMemoryBackend` and `FileSystemBackend`: order, window, concurrent appends, namespace isolation, a new instance over the same backend sees the same data
    - _Requirements: 52.1, 23.2_

- [ ] 3. Entry memory
  - [ ] 3.1 Settle the storage Port question in steering (delete and prefix listing, or the index document), then record the decision
    - Note: blocked on the first open point of `design.md`; steering is changed before this spec.
    - _Requirements: 12.3, 52.1_
  - [ ] 3.2 `EntryMemory` implementing `MemoryInterface`: `store`, `get_by_id`, `delete`, with the async forms as the real ones
    - _Requirements: 52.1; D37_
  - [ ] 3.3 Keyword retrieval with a capped index and filters by memory type and metadata
    - _Requirements: 52.1_
  - [ ] 3.4 Embedding at store time and similarity retrieval when a `VectorEncoderInterface` is given; no vector database
    - _Requirements: 52.1, 25_
  - [ ] 3.5 Port-compliance test through the shared checker, and tests for the unknown id, the empty result and the cap
    - _Requirements: 16.7, 23.2_

- [ ] 4. Packaging and budgets
  - [ ] 4.1 Make `skye.memory` importable with its real exports (D40: the placeholder `ImportError` goes where it exists); lazy imports only
    - _Requirements: 7.3; D40_
  - [ ] 4.2 Correct the `memory` extra in steering (Requirement 52.2 against D30) with a decision line, then make `pyproject.toml` and `budgets.toml` agree
    - Note: steering first; blocked on the third open point of `design.md`.
    - _Requirements: 52.2, 7.1; D30_
  - [ ] 4.3 Check that `memory` imports only `base`, `store` and `auth`, and that no runtime component imports it
    - _Requirements: 2.2, 52.3, 4.1_
  - [ ] 4.4 Entry in `budgets.toml` for import time and size; a docs page `docs/memory/` and a runnable example
    - _Requirements: 7.5, 15.5, 24.2_
  - [ ] 4.5 If the memory component calls a model to keep the memories (add, change, forget, tidy, working notes), bring back its prompts (`agent_memory_maintenance` or the ones it needs) from `examples/prompts/catalogue/` into `src/skye/prompts/templates/`, as a move of the file with a test; a memory that does not call a model needs none (D118)
    - _Requirements: 30.14; D118_
