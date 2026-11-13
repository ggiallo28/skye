---
title: "skye.store"
status: current
---

# `skye.store`

State backends behind the storage Ports, the factory and the conformance suite.

## The interface

A store is a set of JSON objects by key, with an optional time to live. Five Ports say what a component can ask of it. They are
defined in `skye.base.interfaces.storage` and exported from `skye.store` and from [`skye.interfaces`](interfaces.md).

| Port | Methods |
|---|---|
| `KeyValueStore` | `get`, `set`, `delete`, `get_multiple`, `set_multiple` |
| `CounterStore` | `increment(key, amount=1, ttl=None)`, `count(key)` |
| `ExpiryStore` | `is_alive(key)`, `remaining(key)` |
| `ScanStore` | `keys(prefix="", limit=None)` |
| `StorageBackend` | key-value plus counter, with `connect` and `close`: the base class of every backend |

Every method is `async`. Five of the six backends implement all four Ports; `DurableFunctionBackend` has no `ScanStore`. To pick a
backend see [Choose a store backend](../../guides/state/choose-a-backend.md). The rest of this page is generated from the docstrings.

::: skye.store
    options:
      show_root_heading: true
      show_submodules: false

::: skye.store.conformance
    options:
      show_root_heading: true
      show_submodules: false

