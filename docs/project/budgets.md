---
title: "Size and load budgets"
status: current
---

# Size and load budgets

Skye is meant for serverless, where every dependency is paid at install time (package size), at cold start (import time and memory) and at build time (a compiled wheel needs a container for the right architecture). The limits live in `budgets.toml` and are checked by tests and by the `budgets` workflow on every pull request.

## Principles

For everything Skye imports, in this order:

1. the Python standard library;
2. libraries the AWS Lambda Python runtime already contains (`boto3`, `botocore`, `s3transfer`, `jmespath`, `python-dateutil`, `six`, `urllib3`; listed in `[lambda]`);
3. pure-Python packages (wheel tagged `py3-none-any`), only when 1 and 2 cannot do the job;
4. never a compiled package (C or Rust extension) in the core. The library is I/O bound, so speed is not a reason to accept one.

Provider SDKs and optional libraries are imported inside the function that uses them (`LazyImporter`), never at module level.

## What is checked

| Check | Where | Needs |
|---|---|---|
| Core dependency list equals `[core] allowed_dependencies` | `tests/budget/test_policy.py` | nothing |
| Every extra has a budget, an empty extra is listed, bundles are listed | `test_policy.py` | nothing |
| Third-party imports at module level in `src/skye` match `[imports.max_files]` | `test_policy.py` | nothing |
| `import skye` imports no provider SDK or optional library (known leaks are listed) | `test_load_budget.py` | nothing |
| Core install: packages, size, compiled packages, every subpackage imports | `test_footprint_budget.py` | `uv`, network |
| `import skye` in a clean core install: modules, time, memory | `test_footprint_budget.py` | `uv`, network |
| Each extra: size added over the core, compiled packages added | `test_footprint_budget.py` | `uv`, network |
| Serverless profile (core + `bedrock`) stays far below the 250 MB Lambda limit | `test_footprint_budget.py` | `uv`, network |
| Tokens Skye adds to what the caller wrote, on a direct model call (reported in the job summary, not enforced yet) | `test_token_overhead.py` | nothing |
| Size of the package by component and by kind (code, docstrings, comments, data); reports and never enforces | `size_report.py`, `test_size_report.py` | nothing (`--source`), `uv` (wheel) |
| The wheel has no comment: `hatch_build.py` strips the comments of the Python files and of the bundled templates at build (same AST, same line numbers, same objects); the repository, the sdist and an editable install keep them; the wheel packs the templates into one reproducible `templates.zip` that the loader reads by name (`test_wheel_templates_archive.py`) | `test_wheel_comments.py` | `uv` |

Run them:

```bash
make budget-fast    # policy and import checks, a second
make budget         # installs Skye in clean environments, about a minute
make size           # where the bytes are, by component and by kind; run it at the end of a wave
```

Sizes exclude the libraries Lambda already ships. Time is the best of five fresh interpreters. Measurements were taken on Python 3.13; the workflow runs the fast checks on 3.11 (the minimum, D49) and 3.13 and the footprint checks on 3.13.

**Sizes are Linux sizes.** The footprint jobs run on a Linux x86_64 runner, which is also the serverless target, and the compiled wheels (`asyncpg`, `tiktoken`, ...) are larger there than on macOS: the compiled extras are larger there (the core has no compiled file any more: it is the same 1.9 MB everywhere). The limits in `budgets.toml` are the Linux ones. To check the sizes from any machine, without a Linux runner:

```bash
uv pip install --target /tmp/skye-linux --python-platform x86_64-manylinux_2_28 --python-version 3.13 "skyeai[memory] @ file:///path/to/skyeai.whl"
```

and measure the folder as `tests/budget/measure.py` does. The footprint jobs of the workflow are one per extra that has a budget; `tests/budget/test_workflow_matrix.py` keeps that list in step with `budgets.toml`.

## No external-library type outside its Component

`tests/budget/test_boundary_rule.py` (part of `make budget-fast`) checks the boundary rule (Requirement 9.5 in `.kiro/steering/10-requirements.md`): provider SDKs (`openai`, `anthropic`, `boto3`, `vertexai`/`google.cloud.aiplatform`, `cohere`) and `fastmcp`/`mcp` are imported only by the files that own them, only inside a function, `tools/mcp_boundary.py` imports no third-party library, no public annotation in `models`/`tools` names an external type, and the provider and MCP conversions return Skye types only. A new external backend (for `observe`, `store`, `prompts`, `agents`) adds its owning file to `SDK_OWNERS` in that test; no new Component or Port. `tests/differential/test_boundary_leak.py` runs the same check on both MCP clients (needs `fastmcp`, dev group).

## Changing a budget

A budget only goes down. When a PR fixes something (removes a dependency, moves an import behind `LazyImporter`), the matching test fails until the list in `budgets.toml` is updated, so the number follows the code. Raising a number needs a reason in the PR and a review from the owner of `budgets.toml` (`.github/CODEOWNERS`).

To make the check blocking, require the `budgets / fast checks` and `budgets / footprint` jobs in the repository's branch protection rules. This is a GitHub setting, not part of the repository.

## Debt recorded today (2026-11-02)

Checked against `budgets.toml` and `pyproject.toml`.

| Item | Why it matters | Target |
|---|---|---|
| Core dependencies: none since decision D49 (`pydantic` and `tenacity` are gone); one distribution, 1.9 MB, nothing compiled (measured 2026-11-11, below) | nothing to carry | done |
| Extras with no dependency of their own: `agents`, `guard`, `prompts`, `tools`, `teams`, `flows`, `observe`, and the provider extras `anthropic`, `bedrock`, `google`, `cohere` | they are modules, not extras (the provider extras stay so `pip install skyeai[...]` keeps working) | remove the ones that are not provider extras from `pyproject.toml` |
| Extra sizes over the core, on Linux: `auth` 0.5 MB (`rsa`), `memory` 2.6 MB (`redis`), `tokens` 8.4 MB (`tiktoken`, compiled; decision D33), `postgres` 14.0 MB (`asyncpg`, compiled), `mcp` about 50 MB (`fastmcp`, 7 compiled distributions; not gated since decision D67: an optional third-party library is not part of Skye's budget, and the built-in MCP client is the default) | the compiled ones | only who installs an extra pays for it |
| `skyeai[all]` size | it includes `mcp` and `memory` | not advertised for Lambda |

### What the core weighs (2026-11-07, task 14.4 of `0-base-structure`)

Measured on a real install: `uv build --wheel` (the wheel is `skyeai-0.1.0-py3-none-any.whl`, pure Python), then `uv pip install --no-deps` into a fresh
venv, Python 3.13.2, macOS arm64. The wheel has no compiled file, so the files (and the size) are the same on Linux; the CI runner measures them again. Not measured here: the extras (they need the network to download their libraries; the limits of the extras are unchanged) and Linux x86_64.

| Measure | Before (D49, estimates and the pydantic stack) | Measured now | Limit in `budgets.toml` (was) |
|---|---|---|---|
| Distributions in the core install | 10 to 12 | 1 (`skyeai`) | 1 (2) |
| Installed size | 8.9 MB on Linux, 8.5 MB on macOS | 1.13 MB | 2 MB (3) |
| Compiled distributions | `pydantic-core` | none | none |
| `import skye` in a clean core install: modules | 293 | 58 | 80 (340) |
| `import skye`: time, best of 10 | about 91 ms | 16 ms | 100 ms (250) |
| `import skye`: memory added | about 24 MB | 5 MB | 16 MB (32) |
| Cold path (import, router, one target, one request), best of 10 | about 95 ms | 56 ms (median 69, worst 152) | 200 ms (300); target 100 ms (150) |
| Serverless profile (core + `bedrock`, which has no library of its own) | about 9 MB | 1.9 MB | 3 MB (30) |

The tests that measured them are the real ones: `tests/budget/test_footprint_budget.py -m budget -k "core or serverless"` (4 and 1 passed) and the probe of
`tests/budget/test_cold_start.py` run with the python of the clean install. Each limit is the measure plus room for a slower runner (the CI runner is about three times a laptop) and for growth; a limit only goes down.

Done since the previous table (2026-10-30): `jinja2` and `markupsafe` left the core (the prompts engine is standard library), the provider SDK extras
(`google` 176 MB, `cohere` 33 MB, `anthropic` 10 MB) are empty because every provider has one built-in REST adapter, `pydantic` and `tenacity` left the core (D49), and the `yaml` extra and `pyyaml` were removed (D62): the library reads no YAML.

### Parse time of a `.skye` file (2026-11-07, task 11.3 of `0-base-base`; decides open decision O37)

Each number is the best of 5 fresh interpreters on the clean install above (Python 3.13.2, macOS arm64), in milliseconds. "Cold" is `skye.base.dsl.build` on the text, the first
call of the process. "From the cache" is the second call in the same process: `build_cached` on the same text, and `load_document` on the same file (a stat, no read).

| File | Lines | Import of `skye.base.dsl` and `skye.utils.skye_files` | `build`, cold | `load_document`, first call (read, hash, build) | `build_cached`, hit | `load_document`, hit |
|---|---|---|---|---|---|---|
| `examples/routing/router_config.skye` (the real router, 292 lines with comments) | 292 | 27.6 | 4.6 | 5.1 | 0.008 | 0.03 |
| `examples/routing/router_config_simple.skye` | 37 | 32.1 | 1.0 | 0.1 (text already built in the probe) | 0.005 | 0.04 |
| `tests/fixtures/skye/f9.skye` (a flow) | 47 | 26.6 | 2.3 | 3.7 | 0.007 | 0.04 |
| `tests/fixtures/skye/flows.skye` (several flows) | 129 | 27.3 | 5.6 | 5.1 | 0.010 | 0.04 |

Reading: parsing and checking a real file costs 2 to 6 ms, about one tenth of the cold path of the library (56 ms) and nothing next to a model call. A hit in the memory cache costs 8 to 40 microseconds. Importing the parser costs more (about 27 ms) than parsing the file, and that import is paid by a new process
whatever happens to the parse result, so a file on disk would save at most 5 of the roughly 70 ms (import of `skye` 16, of the parser 27, parse 5, router import and build 22) that a new serverless container spends on the first router.

**Conclusion for O37: a parse result on disk is not worth it.** It would save about 5 ms per cold container, and it would add a second file to keep consistent (hash, parser version, spec version), a place to write on a read-only Lambda, and a reader whose own cost (JSON decoding plus rebuilding the spec objects) is a fraction of the parse that it replaces. The in-memory cache of D63 already covers the warm container and the program that reloads a router. Decision for the owner: close O37 as "no".

### Import cost per component package
No package imports `pydantic` or `tenacity` any more (decision D49; the sizes above are the measure before the removal, to be re-measured on a clean Linux install). Before the removal (2026-11-05):

- `skye` and `skye.base` (and the facades `skye.interfaces`, `skye.data`, `skye.messages`, `skye.completion`, `skye.exceptions`, `skye.config`): no.
- `skye.agents`, `skye.auth`, `skye.flows`, `skye.gateway`, `skye.guard`, `skye.models`, `skye.observe`, `skye.policy`, `skye.prompts`, `skye.store`, `skye.teams`: no.
- `skye.router`: yes (one module).
- `skye.tools`: yes (two modules, among them the pydantic `CapabilitySchema`).
- `skye.memory`: yes (one module).
- `skye.utils`: yes (`validation`, for pydantic structured-output classes).
