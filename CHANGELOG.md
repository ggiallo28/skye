# Changelog

All notable changes to Skye are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Examples: an Ollama provider example, and plugin and hooks examples.

### Changed

- Examples use a current Claude Sonnet model id in place of the retired Claude 3 Sonnet one.

## [0.2.0] - 2026-11-11

### Added

- `skye render` and `to_mermaid`: draw a router or a flow as a diagram.
- The `skye.dsl` facade for the public functions of the `.skye` language.
- Forced capability choice emulation for providers that do not support it natively.
- An example that packages Skye as a zip for AWS Lambda.

### Changed

- The config file is read outside the `base` component.
- The documentation is reorganized into get started, concepts, guides, reference and project sections.
- Prompts, router and tools are aligned with the updated base and adapters components, and the models and store adapters follow their updated specs.
- Size budgets in `budgets.toml` are updated.

## [0.1.1] - 2026-11-08

### Added

- A Code of Conduct.

### Changed

- PyPI metadata: more classifiers and the documentation URL.
- README: badge order, Python 3.11+, MIT and install size badges, and documentation links that point to Read the Docs.

## [0.1.0] - 2026-11-08

First release after the 0.0.1 preview on PyPI.

### Added

- Prompts and routers written in `.skye` files, with the language tools (`skye check`, `fmt`, `new`).
- The documentation site on Read the Docs (MkDocs Material) and the project URLs.

### Changed

- The core has zero third-party dependencies and uses the standard library only.

### Removed

- YAML configuration. A `.yaml` or `.yml` file is now rejected with an error; use `.skye` or JSON.

### Fixed

- Router fixes.

[Unreleased]: https://github.com/ggiallo28/skye/compare/v0.2.0...main
[0.2.0]: https://github.com/ggiallo28/skye/releases/tag/v0.2.0
[0.1.1]: https://pypi.org/project/skyeai/0.1.1/
[0.1.0]: https://pypi.org/project/skyeai/0.1.0/
