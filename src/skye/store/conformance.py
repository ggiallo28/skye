# Requirement 12.6, decision D98
"""The public conformance suite of the storage Ports.

Every promise of ``KeyValueStore``, ``CounterStore``, ``ExpiryStore`` and ``ScanStore`` written
once, as code anyone
can run against a backend, Skye's
or their own. ``check_backend`` takes a function that builds a fresh, empty backend from a clock and
runs every check that the backend's
capabilities allow; it raises ``AssertionError`` naming the first broken promise. The clock is a
``FakeClock``, so expiry is checked
without sleeping; a backend that keeps time on its server (Redis) passes the clock to its fake
client instead.

Example:
    >>> import asyncio
    >>> from skye.store import InMemoryBackend
    >>> from skye.store import check_backend
    >>> asyncio.run(check_backend(lambda clock: InMemoryBackend(clock=clock)))
    ['key_value', 'counter', 'expiry', 'scan']

In a test of your own backend::

    def test_my_backend_conforms():
        asyncio.run(check_backend(lambda clock: MyBackend(clock=clock)))

Raises: ``AssertionError`` naming the broken promise.
Missing: not applicable.
Concurrency: the counter check runs 50 concurrent increments and expects no lost update.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from skye.base.exceptions import ValidationError
from skye.base.interfaces.storage import CounterStore, ExpiryStore, KeyValueStore, ScanStore


class FakeClock:
    """A clock that moves only when told to; call it to read the time."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        """Start at ``start`` seconds since the epoch."""
        self.now = start

    def __call__(self) -> float:
        """The current fake time."""
        return self.now

    def advance(self, seconds: float) -> None:
        """Move the time forward."""
        self.now += seconds


Make = Callable[[FakeClock], Any]


def _require(store: Any, port: type, message: str) -> None:
    if not isinstance(store, port):
        raise AssertionError(message)


async def _rejects(call: Callable[[], Awaitable[Any]], what: str) -> None:
    try:
        await call()
    except ValidationError:
        return
    raise AssertionError(f"{what} must raise ValidationError")


# D95
async def check_key_value(make: Make) -> None:
    """``get``, ``set``, ``delete``, ``get_multiple``, ``set_multiple`` and expiry."""
    clock = FakeClock()
    store: Any = make(clock)
    _require(store, KeyValueStore, "the backend must implement KeyValueStore")
    assert await store.get("absent") is None, "an absent key reads as None"
    await store.set("a", {"x": 1, "nested": {"y": [1, 2]}, "f": 1.5, "s": "text"})
    assert await store.get("a") == {
        "x": 1,
        "nested": {"y": [1, 2]},
        "f": 1.5,
        "s": "text",
    }, "set then get returns the value"
    await store.set("a", {"x": 2})
    assert await store.get("a") == {"x": 2}, "set replaces the whole value"

    await store.set("short", {"v": 1}, ttl=10)
    clock.advance(9)
    assert await store.get("short") == {"v": 1}, "a value is live before its ttl"
    clock.advance(2)
    assert await store.get("short") is None, "an expired value reads as None"
    await store.set("forever", {"v": 1}, ttl=None)
    clock.advance(10**6)
    assert await store.get("forever") == {"v": 1}, "ttl=None never expires"

    for bad in (0, -1, 1.5, True, "10"):

        def write(ttl: Any = bad) -> Awaitable[None]:
            result: Awaitable[None] = store.set("bad", {"v": 1}, ttl=ttl)
            return result

        await _rejects(write, f"set with ttl={bad!r}")
    assert await store.get("bad") is None, "a rejected set writes nothing"
    await _rejects(lambda: store.set("", {"v": 1}), "an empty key")
    await _rejects(lambda: store.set("bad", ["not", "a", "dict"]), "a value that is not a dict")

    assert await store.delete("a") is True, "delete of a live key returns True"
    assert await store.get("a") is None, "a deleted key reads as None"
    assert await store.delete("a") is False, "delete of an absent key returns False"

    await store.set_multiple({"m1": {"i": 1}, "m2": {"i": 2}}, ttl=5)
    got = await store.get_multiple(["m2", "missing", "m1"])
    assert list(got) == ["m2", "missing", "m1"], "get_multiple keeps the order of the keys"
    assert got == {"m2": {"i": 2}, "missing": None, "m1": {"i": 1}}, "get_multiple maps every key"
    clock.advance(6)
    assert await store.get_multiple(["m1", "m2"]) == {
        "m1": None,
        "m2": None,
    }, "set_multiple applies the ttl"
    assert await store.get_multiple([]) == {}, "get_multiple of no keys is empty"
    await _rejects(
        lambda: store.set_multiple({"ok": {"v": 1}, "": {"v": 2}}), "set_multiple with an empty key"
    )
    assert await store.get("ok") is None, "a rejected set_multiple writes nothing"


async def check_counter(make: Make) -> None:
    """``increment`` and ``count``: start at 0, add, read, expire, and no lost update under
    concurrent tasks."""
    clock = FakeClock()
    store: Any = make(clock)
    _require(store, CounterStore, "the backend must implement CounterStore")
    assert await store.increment("c") == 1, "an absent counter starts at 0"
    assert await store.increment("c", 4) == 5, "increment adds the amount"
    assert await store.increment("c", -2) == 3, "a negative amount subtracts"
    assert await store.get("c") == {"count": 3}, "a counter reads as {'count': n}"
    await store.set("preset", {"count": 10})
    assert await store.increment("preset") == 11, "increment continues a value set as {'count': n}"
    assert await store.increment("t", ttl=10) == 1
    clock.advance(11)
    assert await store.get("t") is None, "an expired counter reads as None"
    assert await store.increment("t") == 1, "an expired counter starts again"
    await _rejects(lambda: store.increment("t", ttl=0), "increment with ttl=0")
    await asyncio.gather(*(store.increment("busy") for _ in range(50)))
    assert await store.get("busy") == {"count": 50}, "concurrent increments lose no update"
    await check_count(store, clock)


async def check_count(store: Any, clock: FakeClock) -> None:
    """``count``: 0 when absent, the value after increments, 0 when expired, a pure read, and a key
    is validated."""
    assert await store.count("never") == 0, "count of an absent key is 0"
    assert await store.get("never") is None, "count does not create the key"
    assert isinstance(await store.count("never"), int), "count is an int"
    assert await store.increment("k", 3) == 3
    assert await store.count("k") == 3, "count reads the value that increment returned"
    assert await store.increment("k", 4) == 7
    assert await store.count("k") == 7, "count follows the increments"
    await store.set("k_preset", {"count": 10})
    assert await store.count("k_preset") == 10, "count reads a value set as {'count': n}"
    assert await store.count("busy") == 50, "count after concurrent increments"
    assert await store.get("k") == {"count": 7}, "count leaves the stored value as it was"

    assert await store.increment("k_ttl", ttl=10) == 1
    clock.advance(9)
    assert await store.count("k_ttl") == 1, "a counter is live before its ttl"
    clock.advance(2)
    assert (
        await store.count("k_ttl") == 0
    ), "count does not move the expiry: the counter has expired"
    assert await store.get("k_ttl") is None, "an expired counter reads as None"
    assert await store.count("k_ttl") == 0, "count of an expired key is 0, as many times as asked"
    assert await store.increment("k_ttl") == 1, "an expired counter starts again after count"
    await _rejects(lambda: store.count(""), "count with an empty key")


async def check_expiry(make: Make) -> None:
    """``is_alive`` and ``remaining``: absent, no expiry, the time left (rounded up), expired, pure
    reads, a key is validated."""
    clock = FakeClock()
    store: Any = make(clock)
    _require(store, ExpiryStore, "the backend must implement ExpiryStore")
    assert await store.is_alive("never") is False, "an absent key is not alive"
    assert await store.remaining("never") is None, "an absent key has no remaining time"
    assert await store.get("never") is None, "is_alive and remaining do not create the key"

    await store.set("forever", {"v": 1})
    assert await store.is_alive("forever") is True, "a key with no expiry is alive"
    assert await store.remaining("forever") is None, "a key with no expiry has no remaining time"
    clock.advance(10**6)
    assert await store.is_alive("forever") is True, "a key with no expiry stays alive"

    await store.set("short", {"v": 1}, ttl=10)
    assert await store.is_alive("short") is True, "a key is alive before its ttl"
    remaining = await store.remaining("short")
    assert remaining == 10 and isinstance(
        remaining, int
    ), "remaining is the ttl just written, as an int"
    clock.advance(3)
    assert await store.remaining("short") == 7, "remaining goes down with the time"
    clock.advance(6.5)
    assert await store.remaining("short") == 1, "remaining rounds up: half a second left is 1"
    assert await store.is_alive("short") is True, "a key with time left is alive"
    clock.advance(1)
    assert await store.is_alive("short") is False, "an expired key is not alive"
    assert await store.remaining("short") is None, "an expired key has no remaining time"
    assert await store.get("short") is None, "an expired key reads as None"

    await store.set("steady", {"v": 1}, ttl=10)
    clock.advance(5)
    for _ in range(3):
        assert await store.is_alive("steady") is True
        assert await store.remaining("steady") == 5, "remaining does not move the expiry"
    clock.advance(6)
    assert (
        await store.is_alive("steady") is False
    ), "is_alive does not move the expiry: the key has expired"

    await store.set("replaced", {"v": 1}, ttl=10)
    await store.set("replaced", {"v": 2})
    assert await store.remaining("replaced") is None, "a set without ttl removes the expiry"
    await store.set("again", {"v": 1})
    await store.set("again", {"v": 2}, ttl=20)
    assert await store.remaining("again") == 20, "a set with a ttl replaces the expiry"

    assert await store.increment("counter", ttl=15) == 1, "setup of a counter with a ttl"
    assert await store.remaining("counter") == 15, "a counter has an expiry too"

    assert await store.delete("again") is True
    assert await store.is_alive("again") is False, "a deleted key is not alive"
    await _rejects(lambda: store.is_alive(""), "is_alive with an empty key")
    await _rejects(lambda: store.remaining(""), "remaining with an empty key")


async def check_scan(make: Make) -> None:
    """``keys``: prefix, order, limit, expiry, and keys with special characters."""
    clock = FakeClock()
    store: Any = make(clock)
    _require(store, ScanStore, "the backend must implement ScanStore")
    assert await store.keys("run:") == [], "no keys in an empty store"
    for key in ("run:2", "run:1", "other:1", "run:3"):
        await store.set(key, {"k": key})
    await store.set("run:old", {"k": 1}, ttl=1)
    await store.set("odd/%_*?[x]", {"k": 1})
    assert await store.keys("run:") == [
        "run:1",
        "run:2",
        "run:3",
        "run:old",
    ], "keys returns the matching keys, sorted"
    clock.advance(2)
    assert await store.keys("run:") == ["run:1", "run:2", "run:3"], "keys leaves out expired keys"
    assert await store.keys("run:", limit=2) == ["run:1", "run:2"], "keys honours the limit"
    assert await store.keys("odd/%_*?[") == [
        "odd/%_*?[x]"
    ], "a prefix with %, _, *, ?, [ matches literally"
    assert "other:1" in await store.keys(), "an empty prefix lists every key"


async def check_backend(make: Make) -> list[str]:
    """Run every check the backend's capabilities allow; return the names of the checks that ran."""
    probe = make(FakeClock())
    if hasattr(probe, "increment") and not isinstance(probe, CounterStore):
        raise AssertionError("a backend with increment must implement CounterStore: add count(key)")
    if (hasattr(probe, "is_alive") or hasattr(probe, "remaining")) and not isinstance(
        probe, ExpiryStore
    ):
        raise AssertionError(
            "a backend with is_alive or remaining must implement ExpiryStore: add both"
        )
    ran = []
    checks: list[tuple[str, type, Callable[[Make], Awaitable[None]]]] = [
        ("key_value", KeyValueStore, check_key_value),
        ("counter", CounterStore, check_counter),
        ("expiry", ExpiryStore, check_expiry),
        ("scan", ScanStore, check_scan),
    ]
    for name, port, check in checks:
        if isinstance(probe, port):
            await check(make)
            ran.append(name)
    if "key_value" not in ran:
        raise AssertionError("every backend must implement KeyValueStore")
    return ran


__all__ = [
    "FakeClock",
    "check_backend",
    "check_count",
    "check_counter",
    "check_expiry",
    "check_key_value",
    "check_scan",
]
