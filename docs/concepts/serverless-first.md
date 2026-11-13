---
title: "Serverless first"
status: current
---

# Serverless first

This page explains the choices that make Skye fit a serverless function: a standard-library core, budgets checked on every pull
request, extras you add only when you need them, no background work and state kept outside the process.

## Why it matters

In a serverless function you pay for every dependency three times:

- at deploy time, in package size (AWS Lambda allows 250 MB unzipped, code and layers together);
- at cold start, in import time and memory, before your handler runs;
- at build time, when a compiled wheel needs a container built for the right architecture and Python version.

A thin Python function starts in about 100 to 300 ms, and `import boto3` alone costs 150 to 250 ms. Skye keeps its own cold path
below one `import boto3`.

## The standard library first

For everything Skye imports, the order of preference is:

1. the Python standard library;
2. libraries the serverless runtime already ships (on AWS Lambda: `boto3`, `botocore`, `urllib3`, ...);
3. pure-Python packages (a `py3-none-any` wheel), only when 1 and 2 cannot do the job;
4. never a compiled package in the core.

So the core install has no third-party dependency at all. Every provider (OpenAI, Anthropic, Bedrock, Azure OpenAI, Google) is
called over REST with `urllib`, through the one HTTP helper in `base`. Bedrock is signed with SigV4 written in the standard library,
so you do not need `boto3` to call it. Streaming responses are parsed with the standard library too. Vendor SDKs appear only in the
tests that compare Skye with them.

The library is I/O bound: it spends its time waiting for a model. Speed is never a reason to accept a compiled package.

## Budgets

The limits live in `budgets.toml` at the root of the repository. `tests/budget` and the `budgets` GitHub workflow check them on
every pull request, and a budget only goes down: raising a number needs a reason and a review from the owner of the file.

| Budget | Key in `budgets.toml` | Limit | Measured on a laptop |
|---|---|---|---|
| Distributions in the core install | `[core] max_distributions` | 1 | 1 (`skyeai`) |
| Installed size of the core | `[core] max_installed_mb` | 2 MB | 1.9 MB |
| Compiled packages in the core | `[core] known_compiled` | none | none |
| Modules loaded by `import skye` | `[load] max_modules_loaded` | 80 | 58 |
| Time of `import skye`, best of 5 | `[load] max_import_ms` | 100 ms | about 16 ms |
| Memory added by `import skye` | `[load] max_rss_delta_mb` | 16 MB | about 5 MB |
| Cold path: import, router, one target, one request | `[cold_start] max_cold_start_ms` | 200 ms | about 56 ms |
| Core plus the `bedrock` extra, Lambda libraries excluded | `[lambda] max_profile_mb` | 3 MB | 1.9 MB |
| Lambda zip of `examples/serverless/lambda_zip` (library and handler) | `[lambda] max_zip_mb` | 1 MB | 0.56 MB |

The limits leave room for a slower CI runner (about three times a laptop). Sizes are measured on Linux x86_64, the platform of the
runner and of the serverless target.

`import skye` must also never import a library from `[load] forbidden_at_import`: `openai`, `anthropic`, `boto3`, `redis`,
`httpx`, `requests`, `tiktoken`, `numpy`, `fastmcp`, `yaml` and others. The check runs even when those libraries are installed.

Run the checks yourself:

```bash
make budget-fast    # policy and import checks, about a second
make budget         # installs Skye in clean environments, about a minute
```

[Size and load budgets](../project/budgets.md) lists every check, where it lives and the measures behind each number.

## Extras per need

Skye is one package with optional extras. Each extra installs only the library its feature imports, and one extra never pulls
another. A heavy extra weighs only on who installs it.

=== "pip"

    ```bash
    pip install skyeai                # the core: no third-party dependency
    pip install "skyeai[valkey]"      # + the Valkey/Redis store driver
    pip install "skyeai[tokens]"      # + exact token counts with tiktoken
    ```

=== "uv"

    ```bash
    uv add skyeai
    uv add "skyeai[valkey]"
    uv add "skyeai[tokens]"
    ```

An extra is named after what it enables, not after a provider: every provider already has a built-in adapter, so `skyeai[openai]`
installs nothing. Each extra has its own size budget, measured in its own environment. The full list is in
[Extras](../reference/extras.md).

Optional libraries are imported lazily, inside the function that first needs them. If the extra is missing, Skye raises
`MissingExtraError`, which names the extra to install.

## No background work

Skye starts no thread, process or task that outlives the call you made:

- no multiprocessing and no process pools;
- no background threads; a thread is used only inside one call (to run a coroutine from synchronous code when an event loop is
  already running) and is joined before the call returns;
- nothing that depends on a connection surviving between invocations: a backend that opens one opens it again when it needs to.

A serverless runtime freezes the process between invocations, so work left running in the background would be lost or would run at
the wrong time.

## State lives outside the process

All durable state is external. Do not rely on an in-process cache or a connection pool surviving between invocations.

- The default store backend is in-memory, so tests and local scripts need nothing. In production you choose a durable backend:
  DynamoDB, Valkey or Redis, PostgreSQL, or the durable context of AWS Lambda durable functions.
- The router keeps target health and cooldowns through the storage Ports, so every container sees the same health when you give it a
  shared backend.
- In-process caches exist only as a speed-up for a warm container, never for correctness. A `.skye` file, for example, is parsed once
  per process and kept in memory by the hash of its text; a new container simply parses it again in a few milliseconds.

## A handler

Create the client once, outside the handler, so a warm invocation pays nothing:

```python
--8<-- "examples/serverless/lambda_handler.py:9:30"
```

The example runs offline: without AWS credentials a scripted client answers. See
[`lambda_handler.py`](https://github.com/ggiallo28/skye/blob/main/examples/serverless/lambda_handler.py) on GitHub.

## See also

- [Deploy on AWS Lambda](../get-started/lambda.md): a step-by-step deployment.
- [Size and load budgets](../project/budgets.md): every check and every measure.
- [Extras](../reference/extras.md): what each extra installs.
- [Architecture](architecture.md): layers, Ports and lazy imports.
