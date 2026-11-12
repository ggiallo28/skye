# Contributing to Skye

Skye is a light, modular library for serverless GenAI applications. Contributions are welcome. Please read these rules before opening a pull request.

Everyone taking part in the project follows the [Code of Conduct](CODE_OF_CONDUCT.md).

## Where code comes from

- Write the code yourself, or take it from a source whose licence allows it.
- Do not copy code from another project without adding its licence and attribution (a `NOTICE` or `THIRD_PARTY_NOTICES` file, and a comment at the copied code). Ideas and public API shapes are free; code and documentation text are not.
- Never copy from the `enterprise/` directory of LiteLLM: it is under a separate commercial licence.
- Skye is inspired by LangChain, LiteLLM, Pydantic, Cedar, Strands and Amazon Bedrock AgentCore Gateway. "Inspired" means ideas only. Do not use "AgentCore" in a product or module name.
- Prompt templates must be written for Skye or carry the licence of their source.
- Skye is MIT licensed. By contributing you agree that your contribution is released under the same licence.

## Dependencies and size

Skye is built for serverless architectures, where the size of the library and its cold start make a difference, so a user installs only what is needed and nothing forces a third-party library on them. For everything the library imports, in this order: the Python standard library, then libraries already in the serverless runtime (on AWS Lambda: boto3, botocore, urllib3, ...), then pure-Python packages, only when nothing earlier can do the job. Provider SDKs and other optional libraries are imported inside the function that uses them (`LazyImporter`), never at module level.

The limits are in `budgets.toml` and are checked in every pull request (see `docs/project/budgets.md`):

```bash
make budget-fast    # policy and import checks, a second
make budget         # installs Skye in clean environments, about a minute
```

A budget only goes down. Raising one needs a reason in the pull request and a review from the owner of `budgets.toml`.

## Specs

Design work is spec driven, with Kiro. Requirements, design and tasks for each feature live in `.kiro/specs/`, and project-wide rules in `.kiro/steering/`. For a new feature, add or update the spec in the same pull request.

## Built-in vs external library

When a Component offers a built-in standard-library implementation and one backed by an external library (a provider SDK, `fastmcp`), both sit behind the same Port and return the same Skye types. The external types are converted to Skye types at one boundary point inside the owning Component, and none is exposed in a Port return value, parameter or public API. Today this governs `models` (provider SDKs; only the SDK path exists, no REST adapter yet) and the `tools` MCP client (`mcp_client.py` built-in, `mcp_fastmcp.py` fastmcp, one conversion in `mcp_boundary.py`, which imports no third-party library). A future external backend for `observe`, `store`, `prompts` or `agents` follows the same rule, with no new Component and no new Port. Keep the library import inside a function in the owning file, convert at the boundary, and add the file to `SDK_OWNERS` in `tests/budget/test_boundary_rule.py` (`make budget-fast` enforces it; `tests/differential/test_boundary_leak.py` checks both MCP clients against the fake server). Details: `docs/project/budgets.md`, Requirement 16 in `.kiro/specs/0-base-structure/`.

## Before you open a pull request

```bash
uv run pytest
make check
make budget-fast
```

**The changelog.** Add a line under `Unreleased` in [CHANGELOG.md](CHANGELOG.md) in your pull request, in the Added, Changed or Fixed group, in plain words.

**The Claude skill.** The package ships a skill that teaches a model to use Skye (`src/skye/utils/claude_skill/skye/`: a minimal `SKILL.md`, one file per topic in `references/`, and `evals/`). If your change touches the `skye` command line (a command or an option), the `.skye` language (a keyword, a field, a block, a limit, what is version 2), the router strategies or fields, the public functions of `skye.base.dsl`, the short import paths or a project rule, update the matching reference **in the same pull request**, and add a prompt to `evals/evals.json` if a model could get the new rule wrong. `tests/unit/dsl/test_claude_skill.py` fails when the skill does not mention a command, option, field, keyword or public function that exists, so a missed update is caught by `uv run pytest`. Run `skye skill status` after an upgrade to see whether an installed copy is up to date; `skye skill install` updates a copy nobody edited.
