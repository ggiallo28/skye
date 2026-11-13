---
title: "Choose a store backend"
status: current
---

# Choose a store backend

This guide helps you pick where Skye keeps state (router health, counters, your own values) and shows you how to create that backend.

A store is a set of JSON objects by key, with an optional time to live. Six backends ship with Skye. Each one imports its driver only
on first use and has its own extra, so you install only the backend you use.

## The six backends

| Backend | Name for `backend(...)` | Capabilities | Install | Right for |
|---|---|---|---|---|
| `InMemoryBackend` | `memory` | key-value, counter, scan | nothing | the default; tests, a container, a warm Lambda serving web requests |
| `FileSystemBackend` | `file` | key-value, counter, scan | nothing | local development; one JSON file per key |
| `DynamoDBBackend` | `dynamodb` | key-value, counter, scan | nothing in Lambda, `skyeai[aws]` elsewhere | serverless on AWS |
| `RedisBackend` | `redis` or `valkey` | key-value, counter, scan | `skyeai[valkey]` or `skyeai[redis]` | Redis, Valkey (ElastiCache) and compatible servers |
| `PostgreSQLBackend` | `postgres` | key-value, counter, scan | see [PostgreSQL drivers](#postgresql-drivers) | Aurora or any PostgreSQL |
| `DurableFunctionBackend` | `durable_function` | key-value, counter | nothing | the steps of one Lambda durable function execution |

The in-memory backend is the default everywhere, and the library never picks a durable backend for you. In pure serverless, where an
invocation may start with an empty process, choose one yourself: the durable function backend when the function is durable, or an
external store (DynamoDB, PostgreSQL, Valkey or Redis).

## Capabilities

A backend implements the capabilities it can. A component asks only for what it uses. The capabilities are small Ports in
[`skye.interfaces`](../../reference/api/interfaces.md):

| Port | Methods | Who needs it |
|---|---|---|
| `KeyValueStore` | `get`, `set`, `delete`, `get_multiple`, `set_multiple` | every backend has it |
| `CounterStore` | `increment(key, amount=1, ttl=None)`, atomic, and `count(key)`, which reads the counter (0 when absent or expired) | the router (health, cooldown, rate limits) |
| `ExpiryStore` | `is_alive(key)` and `remaining(key)`: the seconds a key has left, rounded up | the router cooldown, anything that asks how long a key lives |
| `ScanStore` | `keys(prefix="", limit=None)` | listing keys by prefix |

`StorageBackend` is key-value plus counter: the base class of every backend. The Ports are runtime-checkable, so you can test a
capability before you use it. Every method is a coroutine.

```python
import asyncio

from skye.interfaces import ScanStore
from skye.store import backend


async def main() -> None:
    store = backend("memory")
    await store.set("session:42", {"user": "ada"}, ttl=3600)
    print(await store.get("session:42"))                  # {'user': 'ada'}
    print(await store.increment("hits:today", ttl=86400))  # 1
    if isinstance(store, ScanStore):
        print(await store.keys("session:"))               # ['session:42']


asyncio.run(main())
```

An absent or expired key reads as `None`; absence never raises. A value must be a JSON-compatible `dict`.

## The time to live

`ttl` is `None` (no expiry) or a positive whole number of seconds. `0`, a negative number or a non-integer raises `ValidationError` in
every backend, before anything is written. Every backend checks the expiry on read, so an expired entry is absent at once, even where
the store deletes it later (DynamoDB deletes expired items within days).

## Create a backend

`skye.backend(name, **config)` builds a backend by name (`skye.store.backend` is the same function); the configuration is the keyword arguments of its class. Naming a
backend imports only its module, and its driver only on first use.

```python
from skye.store import backend

state = backend("dynamodb", table_name="skye-router-state")             # Lambda: nothing to install
state = backend("valkey", redis_url="rediss://cache:6379/0")            # pip install skyeai[valkey]
state = backend("postgres", cluster_arn="arn:aws:rds:...", secret_arn="arn:aws:secretsmanager:...", database="app")
state = backend("file", base_path="/tmp/skye_storage")
```

You can also build the classes directly: `DynamoDBBackend("skye-router-state")` is the same as the first line. `available_backends()`
lists the names `backend` accepts, yours included.

Notes per backend:

- **DynamoDB**: the table has a string partition key `pk`; the expiry is the number attribute `ttl`, which you can enable as the table's
  TTL attribute. There is no default region: it comes from `region_name` or the AWS configuration (`AWS_REGION` in Lambda). `keys`
  scans the whole table: keep it for small tables or maintenance.
- **Valkey and Redis**: one class serves both. It uses the `valkey` driver when installed, else `redis`; `driver=` forces one.
  `key_prefix` (default `skye:`) lets several applications share one database. The URL may hold a password, so it is never logged.
- **File**: atomic between the tasks of one process, not across processes that share the folder.
- **Durable function**: pass the durable context of the execution, `backend("durable_function", context=context)`. Any object with
  `get_state(name)` and `set_state(name, value)` works.

## PostgreSQL drivers

One `PostgreSQLBackend` has three drivers, all optional, tried in this order:

1. **RDS Data API** when you pass `cluster_arn` and `secret_arn`: HTTP calls through `boto3`, no connection to manage, IAM
   authorization. Aurora only. Nothing to install in Lambda; `skyeai[aws]` elsewhere.
2. **pg8000** when installed: pure Python, any PostgreSQL. Install `skyeai[postgres]`.
3. **asyncpg** when installed: compiled, the fastest. Install `skyeai[postgres-asyncpg]`.

=== "pip"

    ```bash
    pip install skyeai[postgres]
    ```

=== "uv"

    ```bash
    uv add "skyeai[postgres]"
    ```

`driver="data-api"`, `"pg8000"` or `"asyncpg"` forces one. With a connection string and neither library installed, building the
backend raises `MissingExtraError`. The table (`skye_storage` by default, `table_name=` to change it) is created on first use.

## Use it for router state

Pass the store to the router so its health, cooldown and rate-limit counters survive between invocations (the router reads the key
from `OPENAI_API_KEY`):

```python
from skye.router import ModelRouter
from skye.store import backend

router = ModelRouter({"chat": ["openai/gpt-4o-mini"]}, storage=backend("dynamodb", table_name="skye-router-state"))
```

See [Router state in a store](../routing/router-state.md) for the details.

## See also

- [Custom store backend](../extend/custom-store.md): write and register your own backend.
- Reference: [`skye.store`](../../reference/api/store.md), [`skye.interfaces`](../../reference/api/interfaces.md).
- Examples: [`backends.py`](https://github.com/ggiallo28/skye/blob/main/examples/store/backends.py),
  [`serverless_router_example.py`](https://github.com/ggiallo28/skye/blob/main/examples/serverless/serverless_router_example.py).
