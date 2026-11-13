---
component: none (cross-cutting: plugins, the registrar and the provider profile)
---

# Requirements Document

## Introduction

This spec covers how a third party adds an integration to Skye without changing it, and how the knowledge that belongs to one provider or to
the store is kept in one place that the other components read. It follows decision D107 (plugins are wanted), D108 (this spec exists; the
rules are Requirements 56 to 63 of steering) and D111 (the plugin interface, the toolkits and the agent call, taken by writing the examples
in `examples/plugins/`). What D111 left open is in the O-entries of `12-decisions.md` (O65, O68, O69, O70, O71, O72, O73) and is named in
`design.md`; this spec follows the decided part and does not guess the rest. The scan that found the scattered knowledge is
`docs/_notes/extension-points-scan.md`; it is a working note and is not part of the spec.

The work has two halves that share one mechanism. The first is the plugin door: one object, `plugins = skye.Plugins()`, whose methods are
decorators (or direct calls) that register at once, one method per kind of integration, one word to add and to build, discovery through the
entry-point group `skye.plugins` that runs lazily and imports a module, an allowlist in the configuration file, one conformance function per
kind and the command `skye plugins`. The second is the provider profile, registered together with the provider class, which cost, token
counting, the router and `auth` read instead of keeping their own tables, together with the matching rule for the store: the router no longer
knows how a counter is stored or how expiry works. The profile shape of the model entry (`tokenizer`, `message_overhead`, prices) is shared
with the token counter work of `1-adapters-models`.

The kinds `toolkit` and `agent` belong to this spec only as plugin kinds: their registration, their name and their shape. What belongs to the
agent loop (`tools=` and `toolkits=` of an agent, `return_direct`, the hooks) is carried by the `3-runtime-agents` spec, and what belongs to the
tools (the content of each built-in toolkit, the schema of a tool, the wire name of a tool) by the `2-services-tools` spec and by the open
decision O70.

Here each requirement is one user story and each acceptance criterion is a pointer of the form
`THE spec SHALL realize Requirement N.k of #[[file:.kiro/steering/10-requirements.md]]`, never a copy of the criterion. The number after
`Requirement` in a heading below is local to this file; the number in a criterion is the steering one. Fetch a steering requirement with
`grep -n -A25 "^### Requirement 59:" .kiro/steering/10-requirements.md`. The order of work (the provider profile first, then the store, then the
closed kinds, then the new interface) is in D108 and D111 and is kept by the tasks.

## Glossary

- **Plugins**: the class `skye.Plugins`; `plugins = skye.Plugins()` is a handle on the default table of registrations of the process. Its methods are decorators and direct calls, one for each kind (Requirement 56.1).
- **Default table**: the one table of registrations of the process, held by the default registrar; every `Plugins()` handle sees the same one.
- **Registrar**: the concrete object that keeps the tables of registrations (`Registrar`, Port `RegistrarInterface`, Requirement 56.2); a test may build a private one and removes what it registered with `unregister`.
- **Kind**: a category of integration that has a method on the registrar: `provider`, `backend`, `credential_source`, `routing_strategy`, `mcp_client`, `tokenizer`, `template_filter`, `agent` and `toolkit`.
- **Provider function**: what a class registered as a `provider` does, deduced from its method: a language model (`generate`), an embedding (`encode`) or a decision (`decide`) (Requirement 56.12).
- **Provider profile**: the one declaration of everything specific to a provider (`ProviderProfile`, Requirement 59.1); a model entry in it is a `ModelProfile` (Requirement 59.2).
- **Toolkit**: a named set of tools that Skye builds by name and an agent takes in `toolkits=`; a class that extends `skye.Toolkit`, which is a `ToolProvider` (Requirement 62.5).
- **Entry-point group**: the group `skye.plugins` of Python package metadata, whose entry points name a module, scanned lazily with `importlib.metadata` (Requirement 57.1).
- **Conformance function**: the public `check_<kind>` of a kind that tests an implementation offline (Requirement 58.4).

## Requirements

### Requirement 1: One object, one decorator for each kind

**User Story:** As a third-party author, I want to add an integration to Skye with one decorator or one call on one object, so that I change nothing inside Skye.

#### Acceptance Criteria

1. THE spec SHALL realize Requirement 56.1 of #[[file:.kiro/steering/10-requirements.md]].
2. THE spec SHALL realize Requirement 56.2 of #[[file:.kiro/steering/10-requirements.md]].
3. THE spec SHALL realize Requirement 56.3 of #[[file:.kiro/steering/10-requirements.md]].
4. THE spec SHALL realize Requirement 56.4 of #[[file:.kiro/steering/10-requirements.md]].
5. THE spec SHALL realize Requirement 56.5 of #[[file:.kiro/steering/10-requirements.md]].
6. THE spec SHALL realize Requirement 56.6 of #[[file:.kiro/steering/10-requirements.md]].
7. THE spec SHALL realize Requirement 56.7 of #[[file:.kiro/steering/10-requirements.md]].
8. THE spec SHALL realize Requirement 56.8 of #[[file:.kiro/steering/10-requirements.md]].
9. THE spec SHALL realize Requirement 56.9 of #[[file:.kiro/steering/10-requirements.md]].
10. THE spec SHALL realize Requirement 56.10 of #[[file:.kiro/steering/10-requirements.md]].
11. THE spec SHALL honor decision D107 of #[[file:.kiro/steering/12-decisions.md]].
12. THE spec SHALL honor decision D108 of #[[file:.kiro/steering/12-decisions.md]].
13. THE spec SHALL honor decision D110 of #[[file:.kiro/steering/12-decisions.md]].
14. THE spec SHALL honor decision D111 of #[[file:.kiro/steering/12-decisions.md]].

### Requirement 2: Plugins found when needed and loaded when allowed

**User Story:** As a user, I want installed plugins found without code, and I want to choose which ones load, so that I control what runs in my function.

#### Acceptance Criteria

1. THE spec SHALL realize Requirement 57.1 of #[[file:.kiro/steering/10-requirements.md]].
2. THE spec SHALL realize Requirement 57.2 of #[[file:.kiro/steering/10-requirements.md]].
3. THE spec SHALL realize Requirement 57.3 of #[[file:.kiro/steering/10-requirements.md]].
4. THE spec SHALL realize Requirement 57.4 of #[[file:.kiro/steering/10-requirements.md]].
5. THE spec SHALL realize Requirement 57.5 of #[[file:.kiro/steering/10-requirements.md]].
6. THE spec SHALL realize Requirement 57.6 of #[[file:.kiro/steering/10-requirements.md]].
7. THE spec SHALL realize Requirement 57.7 of #[[file:.kiro/steering/10-requirements.md]].
8. THE spec SHALL realize Requirement 57.8 of #[[file:.kiro/steering/10-requirements.md]].
9. THE spec SHALL realize Requirement 57.9 of #[[file:.kiro/steering/10-requirements.md]].

### Requirement 3: Every kind open, every plugin testable

**User Story:** As a plugin author, I want every kind of integration open to me and a test that tells me my plugin works, so that I know it is ready before I publish it.

#### Acceptance Criteria

1. THE spec SHALL realize Requirement 58.1 of #[[file:.kiro/steering/10-requirements.md]].
2. THE spec SHALL realize Requirement 58.2 of #[[file:.kiro/steering/10-requirements.md]].
3. THE spec SHALL realize Requirement 58.3 of #[[file:.kiro/steering/10-requirements.md]].
4. THE spec SHALL realize Requirement 58.4 of #[[file:.kiro/steering/10-requirements.md]].
5. THE spec SHALL realize Requirement 58.5 of #[[file:.kiro/steering/10-requirements.md]].
6. THE spec SHALL realize Requirement 58.6 of #[[file:.kiro/steering/10-requirements.md]].
7. THE spec SHALL realize Requirement 58.7 of #[[file:.kiro/steering/10-requirements.md]].

### Requirement 4: A provider declared once

**User Story:** As a provider author, I want to declare everything that is specific to my provider once, together with its class, so that cost, token counting, routing and authentication need no edit of mine.

#### Acceptance Criteria

1. THE spec SHALL realize Requirement 59.1 of #[[file:.kiro/steering/10-requirements.md]].
2. THE spec SHALL realize Requirement 59.2 of #[[file:.kiro/steering/10-requirements.md]].
3. THE spec SHALL realize Requirement 59.3 of #[[file:.kiro/steering/10-requirements.md]].
4. THE spec SHALL realize Requirement 59.4 of #[[file:.kiro/steering/10-requirements.md]].
5. THE spec SHALL realize Requirement 59.5 of #[[file:.kiro/steering/10-requirements.md]].
6. THE spec SHALL realize Requirement 59.6 of #[[file:.kiro/steering/10-requirements.md]].
7. THE spec SHALL realize Requirement 59.7 of #[[file:.kiro/steering/10-requirements.md]].
8. THE spec SHALL realize Requirement 59.8 of #[[file:.kiro/steering/10-requirements.md]].
9. THE spec SHALL realize Requirement 59.9 of #[[file:.kiro/steering/10-requirements.md]].
10. THE spec SHALL realize Requirement 59.10 of #[[file:.kiro/steering/10-requirements.md]].
11. THE spec SHALL realize Requirement 59.11 of #[[file:.kiro/steering/10-requirements.md]].
12. THE spec SHALL realize Requirement 59.12 of #[[file:.kiro/steering/10-requirements.md]].

### Requirement 5: Provider and storage knowledge in one place

**User Story:** As a maintainer, I want the knowledge that belongs to one provider, and the knowledge that belongs to the store, each in exactly one place, so that adding a component edits one class and the other components call that logic.

#### Acceptance Criteria

1. THE spec SHALL realize Requirement 60.1 of #[[file:.kiro/steering/10-requirements.md]].
2. THE spec SHALL realize Requirement 60.2 of #[[file:.kiro/steering/10-requirements.md]].
3. THE spec SHALL realize Requirement 60.3 of #[[file:.kiro/steering/10-requirements.md]].
4. THE spec SHALL realize Requirement 60.4 of #[[file:.kiro/steering/10-requirements.md]].
5. THE spec SHALL realize Requirement 60.5 of #[[file:.kiro/steering/10-requirements.md]].
6. THE spec SHALL realize Requirement 60.6 of #[[file:.kiro/steering/10-requirements.md]].
7. THE spec SHALL realize Requirement 60.7 of #[[file:.kiro/steering/10-requirements.md]].
8. THE spec SHALL realize Requirement 60.8 of #[[file:.kiro/steering/10-requirements.md]].
9. THE spec SHALL realize Requirement 60.9 of #[[file:.kiro/steering/10-requirements.md]].
10. THE spec SHALL realize Requirement 60.10 of #[[file:.kiro/steering/10-requirements.md]].
11. THE spec SHALL realize Requirement 60.11 of #[[file:.kiro/steering/10-requirements.md]].
12. THE spec SHALL realize Requirement 60.12 of #[[file:.kiro/steering/10-requirements.md]].
13. THE spec SHALL honor decision D97 of #[[file:.kiro/steering/12-decisions.md]].
14. THE spec SHALL honor decision D98 of #[[file:.kiro/steering/12-decisions.md]].
15. THE spec SHALL honor decision D104 of #[[file:.kiro/steering/12-decisions.md]].

### Requirement 6: Easy to learn, light to load

**User Story:** As a user who wants to extend Skye, I want one example, one page and an up-to-date skill, so that I write my first plugin in minutes.

#### Acceptance Criteria

1. THE spec SHALL realize Requirement 61.1 of #[[file:.kiro/steering/10-requirements.md]].
2. THE spec SHALL realize Requirement 61.2 of #[[file:.kiro/steering/10-requirements.md]].
3. THE spec SHALL realize Requirement 61.3 of #[[file:.kiro/steering/10-requirements.md]].
4. THE spec SHALL realize Requirement 61.4 of #[[file:.kiro/steering/10-requirements.md]].
5. THE spec SHALL honor decision D27 of #[[file:.kiro/steering/12-decisions.md]].

### Requirement 7: One word to add and to build, one provider, async only

**User Story:** As a plugin author, I want the word that registers a kind to be the word that builds it, one kind for every provider and one version of each method to write, so that a plugin is short and I learn one pattern.

#### Acceptance Criteria

1. THE spec SHALL realize Requirement 56.11 of #[[file:.kiro/steering/10-requirements.md]].
2. THE spec SHALL realize Requirement 56.12 of #[[file:.kiro/steering/10-requirements.md]].
3. THE spec SHALL realize Requirement 56.13 of #[[file:.kiro/steering/10-requirements.md]].
4. THE spec SHALL honor decision D111 of #[[file:.kiro/steering/12-decisions.md]].

### Requirement 8: Tools, toolkits and the agent call

**User Story:** As an agent developer, I want my own tools apart from the tools that ship with Skye, and one call to build an agent, so that an agent has only the tools I gave it.

#### Acceptance Criteria

1. THE spec SHALL realize Requirement 62.1 of #[[file:.kiro/steering/10-requirements.md]].
2. THE spec SHALL realize Requirement 62.2 of #[[file:.kiro/steering/10-requirements.md]].
3. THE spec SHALL realize Requirement 62.5 of #[[file:.kiro/steering/10-requirements.md]].
4. THE spec SHALL realize Requirement 62.6 of #[[file:.kiro/steering/10-requirements.md]].
5. THE spec SHALL realize Requirement 62.7 of #[[file:.kiro/steering/10-requirements.md]].
6. THE spec SHALL realize Requirement 62.8 of #[[file:.kiro/steering/10-requirements.md]].
7. THE spec SHALL realize Requirement 62.9 of #[[file:.kiro/steering/10-requirements.md]].
8. THE spec SHALL honor decision D111 of #[[file:.kiro/steering/12-decisions.md]].

### Requirement 9: The `include` of the `.skye` language

**User Story:** As a template author, I want to write once the entries and the text that many prompts repeat, in a partial file, and bring them in exactly where they belong, so that a schema or a section of a prompt is changed in one place.

#### Acceptance Criteria

1. THE spec SHALL realize Requirement 63.1 of #[[file:.kiro/steering/10-requirements.md]].
2. THE spec SHALL realize Requirement 63.2 of #[[file:.kiro/steering/10-requirements.md]].
3. THE spec SHALL realize Requirement 63.3 of #[[file:.kiro/steering/10-requirements.md]].
4. THE spec SHALL realize Requirement 63.4 of #[[file:.kiro/steering/10-requirements.md]].
5. THE spec SHALL realize Requirement 63.5 of #[[file:.kiro/steering/10-requirements.md]].
6. THE spec SHALL realize Requirement 63.6 of #[[file:.kiro/steering/10-requirements.md]].
7. THE spec SHALL realize Requirement 63.7 of #[[file:.kiro/steering/10-requirements.md]].
8. THE spec SHALL realize Requirement 63.8 of #[[file:.kiro/steering/10-requirements.md]].
9. THE spec SHALL realize Requirement 63.9 of #[[file:.kiro/steering/10-requirements.md]].
10. THE spec SHALL realize Requirement 63.10 of #[[file:.kiro/steering/10-requirements.md]].
11. THE spec SHALL realize Requirement 63.11 of #[[file:.kiro/steering/10-requirements.md]].
12. THE spec SHALL realize Requirement 63.12 of #[[file:.kiro/steering/10-requirements.md]].
13. THE spec SHALL realize Requirement 63.13 of #[[file:.kiro/steering/10-requirements.md]].
14. THE spec SHALL realize Requirement 63.14 of #[[file:.kiro/steering/10-requirements.md]].
15. THE spec SHALL realize Requirement 63.15 of #[[file:.kiro/steering/10-requirements.md]].
16. THE spec SHALL realize Requirement 63.16 of #[[file:.kiro/steering/10-requirements.md]].
17. THE spec SHALL realize Requirement 63.17 of #[[file:.kiro/steering/10-requirements.md]].
18. THE spec SHALL realize Requirement 63.18 of #[[file:.kiro/steering/10-requirements.md]].
19. THE spec SHALL realize Requirement 63.19 of #[[file:.kiro/steering/10-requirements.md]].
20. THE spec SHALL realize Requirement 63.20 of #[[file:.kiro/steering/10-requirements.md]].
21. THE spec SHALL realize Requirement 63.21 of #[[file:.kiro/steering/10-requirements.md]].
22. THE spec SHALL honor decision D116 of #[[file:.kiro/steering/12-decisions.md]].
23. THE spec SHALL honor decision D117 of #[[file:.kiro/steering/12-decisions.md]].
