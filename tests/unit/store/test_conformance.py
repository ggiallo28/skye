"""Every store backend passes the public conformance suite (store tasks 2.1 to 2.3, Requirement 12,
D95, D98).

The external stores run against offline fakes (``fakes.py``); the SQL of PostgreSQL is not executed,
only its parameters are checked.
"""

from __future__ import annotations

import asyncio
import itertools
from pathlib import Path

import pytest

from skye.store import (
    DurableFunctionBackend,
    DynamoDBBackend,
    FileSystemBackend,
    InMemoryBackend,
    PostgreSQLBackend,
    RedisBackend,
)
from skye.store.conformance import FakeClock, check_backend
from tests.unit.store.fakes import FakeDynamoResource, FakeRedis, FakeSqlExecutor


class Context:
    """A durable context: ``get_state`` and ``set_state``."""

    def __init__(self) -> None:
        self.state: dict[str, object] = {}

    def get_state(self, name: str) -> object:
        return self.state.get(name)

    def set_state(self, name: str, value: object) -> None:
        self.state[name] = value


def _makers(tmp_path: Path) -> dict[str, tuple[object, list[str]]]:
    folders = itertools.count()
    return {
        "memory": (
            lambda clock: InMemoryBackend(clock=clock),
            ["key_value", "counter", "expiry", "scan"],
        ),
        "file": (
            lambda clock: FileSystemBackend(str(tmp_path / str(next(folders))), clock=clock),
            ["key_value", "counter", "expiry", "scan"],
        ),
        "dynamodb": (
            lambda clock: DynamoDBBackend("t", resource=FakeDynamoResource(), clock=clock),
            ["key_value", "counter", "expiry", "scan"],
        ),
        "redis": (
            lambda clock: RedisBackend(client=FakeRedis(clock)),
            ["key_value", "counter", "expiry", "scan"],
        ),
        "postgres": (
            lambda clock: PostgreSQLBackend(executor=FakeSqlExecutor(), clock=clock),
            ["key_value", "counter", "expiry", "scan"],
        ),
        "durable_function": (
            lambda clock: DurableFunctionBackend(Context(), clock=clock),
            ["key_value", "counter", "expiry"],
        ),
    }


@pytest.mark.parametrize(
    "name", ["memory", "file", "dynamodb", "redis", "postgres", "durable_function"]
)
def test_backend_conforms(name: str, tmp_path: Path) -> None:
    make, expected = _makers(tmp_path)[name]
    assert asyncio.run(check_backend(make)) == expected


def test_the_suite_is_not_blind() -> None:
    """A backend that keeps expired values fails the suite."""

    class Forgetful(InMemoryBackend):
        async def get(self, key: str):  # type: ignore[override]
            entry = self._data.get(key)
            return None if entry is None else dict(entry[0])

    with pytest.raises(AssertionError, match="expired"):
        asyncio.run(check_backend(lambda clock: Forgetful(clock=clock)))


def test_the_suite_checks_count_ignores_expiry() -> None:
    """A backend whose ``count`` forgets the expiry fails the suite."""

    class IgnoresExpiry(InMemoryBackend):
        async def count(self, key: str) -> int:
            entry = self._data.get(key)
            return 0 if entry is None else int(entry[0].get("count", 0))

    with pytest.raises(AssertionError, match="expired"):
        asyncio.run(check_backend(lambda clock: IgnoresExpiry(clock=clock)))


def test_the_suite_checks_count_does_not_create_the_key() -> None:
    class Creates(InMemoryBackend):
        async def count(self, key: str) -> int:
            value = await super().count(key)
            if key not in self._data:
                await self.set(key, {"count": 0})
            return value

    with pytest.raises(AssertionError, match="does not create the key"):
        asyncio.run(check_backend(lambda clock: Creates(clock=clock)))


def test_the_suite_checks_count_does_not_move_the_expiry() -> None:
    class Extends(InMemoryBackend):
        async def count(self, key: str) -> int:
            value = await super().count(key)
            entry = self._data.get(key)
            if (
                entry is not None and entry[1] is not None
            ):  # count restarts the clock of the counter
                self._data[key] = (entry[0], self._clock() + 10)
            return value

    with pytest.raises(AssertionError, match="expiry"):
        asyncio.run(check_backend(lambda clock: Extends(clock=clock)))


def test_the_suite_checks_count_validates_the_key() -> None:
    class Lenient(InMemoryBackend):
        async def count(self, key: str) -> int:
            return await super().count(key or "x")

    with pytest.raises(AssertionError, match="empty key"):
        asyncio.run(check_backend(lambda clock: Lenient(clock=clock)))


def test_a_counter_backend_without_count_is_refused() -> None:
    """``increment`` without ``count`` used to pass for a backend; now the suite says what is missing."""

    class NoCount:
        async def get(self, key): ...
        async def set(self, key, data, ttl=None): ...
        async def delete(self, key): ...
        async def get_multiple(self, keys): ...
        async def set_multiple(self, data, ttl=None): ...
        async def increment(self, key, amount=1, ttl=None): ...

    with pytest.raises(AssertionError, match="count"):
        asyncio.run(check_backend(lambda clock: NoCount()))


def test_storage_backend_requires_count() -> None:
    """The abstract base tells a third-party backend written for the old Port what it lacks."""
    from skye.base.interfaces.storage import StorageBackend

    class Old(StorageBackend):
        async def get(self, key): ...
        async def set(self, key, data, ttl=None): ...
        async def delete(self, key): ...
        async def increment(self, key, amount=1, ttl=None): ...

    with pytest.raises(TypeError, match="count"):
        Old()  # type: ignore[abstract]


def test_fake_clock_moves_only_when_told() -> None:
    clock = FakeClock(10)
    assert clock() == 10
    clock.advance(5)
    assert clock() == 15


def test_the_suite_checks_is_alive_sees_the_expiry() -> None:
    class Immortal(InMemoryBackend):
        async def is_alive(self, key: str) -> bool:
            return key in self._data

    with pytest.raises(AssertionError, match="expired"):
        asyncio.run(check_backend(lambda clock: Immortal(clock=clock)))


def test_the_suite_checks_remaining_rounds_up() -> None:
    class RoundsDown(InMemoryBackend):
        async def remaining(self, key: str) -> int | None:
            value = await super().remaining(key)
            entry = self._data.get(key)
            if value is None or entry is None or entry[1] is None:
                return value
            return int(entry[1] - self._clock())

    with pytest.raises(AssertionError, match="rounds up"):
        asyncio.run(check_backend(lambda clock: RoundsDown(clock=clock)))


def test_the_suite_checks_remaining_of_a_key_with_no_expiry() -> None:
    class Zero(InMemoryBackend):
        async def remaining(self, key: str) -> int | None:
            return (
                0
                if await self.is_alive(key) and await super().remaining(key) is None
                else await super().remaining(key)
            )

    with pytest.raises(AssertionError, match="no expiry"):
        asyncio.run(check_backend(lambda clock: Zero(clock=clock)))


def test_the_suite_checks_a_read_does_not_move_the_expiry() -> None:
    class Extends(InMemoryBackend):
        async def is_alive(self, key: str) -> bool:
            alive = await super().is_alive(key)
            entry = self._data.get(key)
            if alive and entry is not None and entry[1] is not None:
                self._data[key] = (entry[0], self._clock() + 10)
            return alive

    with pytest.raises(AssertionError, match="not alive"):
        asyncio.run(check_backend(lambda clock: Extends(clock=clock)))


def test_the_suite_checks_the_keys_are_validated() -> None:
    class Lenient(InMemoryBackend):
        async def remaining(self, key: str) -> int | None:
            return await super().remaining(key or "x")

    with pytest.raises(AssertionError, match="empty key"):
        asyncio.run(check_backend(lambda clock: Lenient(clock=clock)))


def test_a_backend_with_half_of_the_expiry_port_is_refused() -> None:
    """``is_alive`` without ``remaining`` is not an ``ExpiryStore``: the suite says what is missing."""

    class Half:
        async def get(self, key): ...
        async def set(self, key, data, ttl=None): ...
        async def delete(self, key): ...
        async def get_multiple(self, keys): ...
        async def set_multiple(self, data, ttl=None): ...
        async def increment(self, key, amount=1, ttl=None): ...
        async def count(self, key): ...
        async def is_alive(self, key): ...

    with pytest.raises(AssertionError, match="ExpiryStore"):
        asyncio.run(check_backend(lambda clock: Half()))


def test_remaining_of_rounds_up_and_leaves_out_no_expiry_and_expired() -> None:
    from skye.store._common import remaining_of

    clock = FakeClock(100)
    assert remaining_of(None, clock) is None
    assert remaining_of(100, clock) is None, "expired at this very second"
    assert remaining_of(99, clock) is None
    assert remaining_of(100.2, clock) == 1, "a fraction of a second is 1"
    assert remaining_of(110, clock) == 10
    assert remaining_of(110.5, clock) == 11
