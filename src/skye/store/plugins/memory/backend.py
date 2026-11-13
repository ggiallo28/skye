# decision D97, D95
"""In-memory backend: the default of the library, standard library only.

Right for a test, a container or a Lambda that serves web requests and keeps its process warm; wrong
for pure serverless, where every
invocation may start empty (choose a durable backend there). Values are copied on the way in and
out, so a caller cannot change what
is stored by mutating a returned ``dict``.

Example:
    >>> import asyncio
    >>> from skye.store import InMemoryBackend
    >>> async def demo():
    ...     store = InMemoryBackend()
    ...     await store.set("user:1", {"name": "Ada"})
    ...     await store.increment("hits", 2)
    ...     return await store.get("user:1"), await store.get("hits"), await store.keys("user:")
    >>> asyncio.run(demo())
    ({'name': 'Ada'}, {'count': 2}, ['user:1'])

Raises: ``ValidationError`` for an invalid key, value or time to live.
Missing: an absent or expired key reads as ``None``.
Concurrency: one event loop; ``increment`` holds a lock, so concurrent tasks never lose an update.
    Not shared across processes.
"""

from __future__ import annotations

import asyncio
import copy
from typing import Any

from skye.base.interfaces.storage import (
    ExpiryStore,
    ScanStore,
    StorageBackend,
    check_key,
    check_ttl,
)
from skye.store._common import (
    Clock,
    check_data,
    check_items,
    check_limit,
    count_of,
    default_clock,
    expiry_of,
    is_expired,
    remaining_of,
)


class InMemoryBackend(StorageBackend, ScanStore, ExpiryStore):
    """Key-value, counter, scan and expiry in a ``dict`` of this process.

    Args:
        clock: The time source for expiry; ``time.time`` by default (tests pass a fake one).
    """

    def __init__(self, *, clock: Clock = default_clock) -> None:
        """Create an empty store."""
        self._data: dict[str, tuple[dict[str, Any], float | None]] = {}
        self._clock = clock
        self._lock = asyncio.Lock()

    def _live(self, key: str) -> dict[str, Any] | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        value, expiry = entry
        if is_expired(expiry, self._clock):
            del self._data[key]
            return None
        return value

    async def get(self, key: str) -> dict[str, Any] | None:
        """The value of ``key`` (a copy), or ``None``."""
        value = self._live(check_key(key))
        return None if value is None else copy.deepcopy(value)

    async def set(self, key: str, data: dict[str, Any], ttl: int | None = None) -> None:
        """Store a copy of ``data`` under ``key``."""
        check_key(key)
        check_data(data)
        self._data[key] = (copy.deepcopy(data), expiry_of(ttl, self._clock))

    async def delete(self, key: str) -> bool:
        """Remove ``key``; ``True`` when it was there and live."""
        present = self._live(check_key(key)) is not None
        self._data.pop(key, None)
        return present

    async def increment(self, key: str, amount: int = 1, ttl: int | None = None) -> int:
        """Add ``amount`` to the counter of ``key`` under a lock and return the new value."""
        check_key(key)
        check_ttl(ttl)
        async with self._lock:
            current = self._live(key) or {}
            value = int(current.get("count", 0)) + amount
            self._data[key] = ({"count": value}, expiry_of(ttl, self._clock))
            return value

    async def count(self, key: str) -> int:
        """The count of ``key``; 0 when it is absent or expired. It does not create the key or move
        its expiry."""
        return count_of(self._live(check_key(key)))

    async def is_alive(self, key: str) -> bool:
        """``True`` when ``key`` is present and has not expired."""
        return self._live(check_key(key)) is not None

    async def remaining(self, key: str) -> int | None:
        """The seconds ``key`` has left (rounded up), or ``None`` when absent, expired or without
        expiry."""
        if self._live(check_key(key)) is None:
            return None
        return remaining_of(self._data[key][1], self._clock)

    async def set_multiple(self, data: dict[str, dict[str, Any]], ttl: int | None = None) -> None:
        """Store every item; nothing is written when one key or value is invalid."""
        check_items(data)
        check_ttl(ttl)
        for key, value in data.items():
            await self.set(key, value, ttl)

    async def keys(self, prefix: str = "", limit: int | None = None) -> list[str]:
        """The live keys that start with ``prefix``, sorted."""
        check_limit(limit)
        found = sorted(
            k for k in list(self._data) if k.startswith(prefix) and self._live(k) is not None
        )
        return found if limit is None else found[:limit]


__all__ = ["InMemoryBackend"]
