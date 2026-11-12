"""``namespaced(store, prefix)``: a prefix on every key, the ports of the store, and no meeting between namespaces (task 8.4)."""

from __future__ import annotations

from typing import Any

import pytest

from skye.base.exceptions import ValidationError
from skye.base.interfaces.storage import (
    CounterStore,
    ExpiryStore,
    KeyValueStore,
    ScanStore,
    StorageBackend,
)
from skye.store import FakeClock, InMemoryBackend, backend, check_backend, namespaced


async def test_every_key_is_written_with_the_prefix() -> None:
    store = InMemoryBackend()
    router = namespaced(store, "router")
    await router.set("health:m", {"ok": True})
    await router.increment("hits", 2)
    assert await store.keys() == ["router:health:m", "router:hits"]
    assert await store.get("router:health:m") == {"ok": True}
    assert await router.get("health:m") == {"ok": True}
    assert await router.count("hits") == 2
    assert await router.delete("health:m") is True
    assert await store.get("router:health:m") is None


async def test_keys_lists_the_namespace_only_and_without_the_prefix() -> None:
    store = InMemoryBackend()
    router, memory = namespaced(store, "router"), namespaced(store, "memory")
    await router.set("a:1", {"x": 1})
    await router.set("a:2", {"x": 2})
    await router.set("b:1", {"x": 3})
    await memory.set("a:1", {"x": 9})
    await store.set("plain", {"x": 0})
    assert await router.keys() == ["a:1", "a:2", "b:1"]
    assert await router.keys("a:") == ["a:1", "a:2"]
    assert await router.keys("a:", 1) == ["a:1"]
    assert await memory.keys() == ["a:1"]


async def test_two_namespaces_never_see_each_other() -> None:
    store = InMemoryBackend()
    one, two = namespaced(store, "one"), namespaced(store, "two")
    await one.set("k", {"who": "one"})
    await one.increment("n", 5)
    assert await two.get("k") is None
    assert await two.count("n") == 0
    await two.set("k", {"who": "two"})
    assert await one.get("k") == {"who": "one"}
    assert await one.delete("k") is True
    assert await two.get("k") == {"who": "two"}


async def test_namespaces_nest() -> None:
    store = InMemoryBackend()
    inner = namespaced(namespaced(store, "a"), "b")
    await inner.set("key", {"x": 1})
    assert await store.keys() == ["a:b:key"]
    assert await inner.keys() == ["key"]


async def test_get_multiple_and_set_multiple_map_the_keys_both_ways() -> None:
    store = InMemoryBackend()
    router = namespaced(store, "router")
    await router.set_multiple({"a": {"n": 1}, "b": {"n": 2}}, ttl=60)
    assert sorted(await store.keys()) == ["router:a", "router:b"]
    assert await router.get_multiple(["a", "b", "c"]) == {"a": {"n": 1}, "b": {"n": 2}, "c": None}


async def test_the_wrapper_has_the_ports_of_the_store_it_wraps() -> None:
    full = namespaced(InMemoryBackend(), "t")
    for port in (KeyValueStore, CounterStore, ExpiryStore, ScanStore, StorageBackend):
        assert isinstance(full, port)

    class Plain(StorageBackend):
        """A store with key-value and counter only."""

        def __init__(self) -> None:
            self.data: dict[str, dict[str, Any]] = {}

        async def get(self, key: str) -> dict[str, Any] | None:
            return self.data.get(key)

        async def set(self, key: str, data: dict[str, Any], ttl: int | None = None) -> None:
            self.data[key] = data

        async def delete(self, key: str) -> bool:
            return self.data.pop(key, None) is not None

        async def increment(self, key: str, amount: int = 1, ttl: int | None = None) -> int:
            value = self.data.get(key, {}).get("count", 0) + amount
            self.data[key] = {"count": value}
            return value

        async def count(self, key: str) -> int:
            return int(self.data.get(key, {}).get("count", 0))

    plain = namespaced(Plain(), "t")
    assert isinstance(plain, StorageBackend)
    assert not isinstance(plain, ExpiryStore)
    assert not isinstance(plain, ScanStore)
    await plain.increment("n", 3)
    assert await plain.count("n") == 3


async def test_the_expiry_port_works_through_the_prefix() -> None:
    clock = FakeClock()
    store = backend("memory", clock=clock)
    router = namespaced(store, "router")
    await router.set("cooldown:m", {"until": 1}, ttl=30)
    assert await router.is_alive("cooldown:m")
    assert await router.remaining("cooldown:m") == 30
    clock.advance(31)
    assert not await router.is_alive("cooldown:m")
    assert await router.remaining("cooldown:m") is None


async def test_connect_and_close_reach_the_store() -> None:
    calls: list[str] = []

    class Spy(InMemoryBackend):
        async def connect(self) -> None:
            calls.append("connect")

        async def close(self) -> None:
            calls.append("close")

    router = namespaced(Spy(), "router")
    await router.connect()
    await router.close()
    assert calls == ["connect", "close"]


@pytest.mark.parametrize("prefix", ["", "a:b", ":", None, 7])
def test_a_bad_prefix_is_refused(prefix: Any) -> None:
    with pytest.raises(ValidationError):
        namespaced(InMemoryBackend(), prefix)


async def test_a_bad_key_is_refused_by_the_wrapper() -> None:
    router = namespaced(InMemoryBackend(), "router")
    with pytest.raises(ValidationError):
        await router.get("")


async def test_a_namespace_passes_the_conformance_suite() -> None:
    ran = await check_backend(lambda clock: namespaced(InMemoryBackend(clock=clock), "t"))
    assert ran == ["key_value", "counter", "expiry", "scan"]
