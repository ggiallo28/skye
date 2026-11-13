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
| The wheel has no comment: `scripts/hatch_build.py` strips the comments of the Python files and of the bundled templates at build (same AST, same line numbers, same objects); the repository, the sdist and an editable install keep them; the wheel packs the templates into one reproducible `templates.zip` that the loader reads by name (`test_wheel_templates_archive.py`) | `test_wheel_comments.py` | `uv` |

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

## Current numbers

Measured with skyeai 0.3.0 on a built wheel, installed with `uv pip install --no-deps` into a clean virtual environment (Python 3.13, macOS arm64). The wheel
is pure Python, so the files are the same on Linux; the CI runner measures them again and is about three times slower than a laptop, which is why each limit
leaves room. A limit only goes down.

| Measure | Value | Limit in `budgets.toml` |
|---|---|---|
| Distributions in the core install | 1 (`skyeai`), nothing compiled | 1 |
| Third-party dependencies of the core | 0 | 0 |
| Installed size of the core | 1.9 MB | 2 MB |
| `import skye`: modules loaded | 61 | 80 |
| `import skye`: time, best of 5 | about 20 ms | 100 ms |
| `import skye`: memory added | about 5 MB | 16 MB |
| `BasePromptBuilder()`, the first of the process | about 1 ms | 10 ms |
| Serverless profile (core + `bedrock`, which has no library of its own) | 1.9 MB | 3 MB |
| Lambda zip of `examples/serverless/lambda_zip` | 0.61 MB | 1 MB (AWS: 50 MB) |

The cold path of the library (import, router, one target, one request) has its own limit of 200 ms in `[cold_start]` of `budgets.toml`. Every extra has a
size and a count of compiled distributions there too; the measured sizes over the core are:

| Extra | Added over the core | Compiled distributions |
|---|---|---|
| `auth` | 0.5 MB | 0 |
| `valkey` | 1.1 MB | 0 |
| `postgres` | 1.7 MB | 0 |
| `postgres-asyncpg` | 2.3 MB | 1 |
| `redis` | 2.6 MB | 0 |
| `tokens` | 6.2 MB | 3 |

The tests that measure them are `tests/budget/test_footprint_budget.py`, `test_cold_start.py` and `test_prompts_builder_time.py`; `make size` and
`make size-wheel` print where the bytes of the package are.
