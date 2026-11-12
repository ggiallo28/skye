---
title: "Custom store backend"
status: current
---

# Custom store backend

This guide shows you how to write a store backend of your own, register it under a name, and check it with the conformance suite that
the built-in backends pass.

## What you need

- `pip install skyeai`.
- A place to keep JSON objects by key: a database, a cache, a service. Its client is your dependency, not Skye's.

## 1. Choose the Ports

The store contract is split into small capability Ports in [`skye.interfaces`](../../reference/api/interfaces.md). Implement what your
storage can do:

| Port | Methods | Required |
|---|---|---|
| `KeyValueStore` | `get`, `set`, `delete`, `get_multiple`, `set_multiple` | yes |
| `CounterStore` | `increment(key, amount=1, ttl=None)`, atomic, and `count(key)`, a read | for the router |
| `ExpiryStore` | `is_alive(key)` and `remaining(key)`, the seconds left (rounded up; `None` when absent, expired or without expiry) | for the router cooldown |
| `ScanStore` | `keys(prefix="", limit=None)` | only if your storage can list keys |

`StorageBackend` is key-value plus counter, as an abstract base class: subclass it, and add `ScanStore` when you implement `keys`.
`StorageBackend` already gives you `connect` and `close` (they do nothing; override them to open and release a client) and default
`get_multiple` and `set_multiple` that call `get` and `set` once per key (override them when your storage has a batch call).

## 2. Implement the backend

```python
--8<-- "examples/store/custom_backend.py:9:49"
```

The promises your backend must keep, the same for every backend:

- A value is a JSON-compatible `dict`; `set` replaces the whole value. A value that is not a `dict`, or an empty key, raises
  `ValidationError`.
- An absent or expired key reads as `None`; `get_multiple` maps it to `None` and keeps the order of the keys; `delete` returns
  `False`; `keys` leaves it out. Absence never raises.
- `ttl` is `None` (no expiry) or a positive whole number of seconds. Anything else (`0`, `-1`, `1.5`, `True`, `"10"`) raises
  `ValidationError` before anything is written. Check the expiry on every read, even if your storage deletes expired entries later.
- `set_multiple` with one invalid key writes nothing.
- `increment` is atomic across concurrent tasks (and across processes, for an external store), starts an absent or expired key at 0,
  accepts a negative amount, stores `{"count": n}` and returns `n`.
- `count(key)` returns the current count as an `int`, `0` when the key is absent or expired. It only reads: it never creates the key and never
  moves its expiry, and it validates the key like the other methods. A backend with `increment` and no `count` is refused by `check_backend`.
- `keys` returns the live keys that start with the prefix, sorted, at most `limit` of them; `%`, `_`, `*`, `?` and `[` in the prefix
  match literally.
- When the storage cannot be reached, raise `ProviderError`.

The example above keeps the shape of the Ports in focus and ignores expiry, so it would not pass the full suite.

## 3. Register it

```python
--8<-- "examples/store/custom_backend.py:52:61"
```

`register_backend(name, factory)` takes a class or any function that returns a backend; `backend(name, **config)` calls it with the
configuration as keyword arguments. A name already taken (one of the built-in names included) raises `ConfigurationError` unless you
pass `replace=True`. Register backends at start-up.

You can also pass the instance directly wherever a store is accepted, for example `ModelRouter(..., storage=DictBackend())`.

## 4. Check it with the conformance suite

`check_backend(make)` runs every check that your backend's Ports allow and raises `AssertionError` naming the first broken promise. It
returns the names of the checks that ran. `make` builds a fresh, empty backend from a clock: take a `clock` argument (a function that
returns the time in seconds) and use it for expiry, so the suite checks expiry with a `FakeClock` instead of sleeping.

```python
import asyncio

from skye.store import InMemoryBackend, check_backend


def test_my_backend_conforms() -> None:
    assert asyncio.run(check_backend(lambda clock: InMemoryBackend(clock=clock))) == ["key_value", "counter", "expiry", "scan"]
```

Replace `InMemoryBackend` with your class. The counter check runs 50 concurrent increments and expects no lost update, checks `count` (absent, after increments, after the expiry) and, for `ExpiryStore`, `is_alive` and `remaining` (absent, no expiry, the time left, expired). A backend that
keeps time on its server (Redis does) passes the clock to a fake client in its test instead.

## See also

- [Choose a store backend](../state/choose-a-backend.md): the built-in backends and the time-to-live rule.
- [Which Port to implement](index.md): every Port of Skye.
- Reference: [`skye.store`](../../reference/api/store.md) (`register_backend`, `check_backend`, `FakeClock`),
  [`skye.interfaces`](../../reference/api/interfaces.md).
- Example: [`custom_backend.py`](https://github.com/ggiallo28/skye/blob/main/examples/store/custom_backend.py).
