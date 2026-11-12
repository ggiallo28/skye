"""Lambda durable function backend: state kept by the durable context the caller passes in (no
extra).

When a function runs as an AWS Lambda durable function, its durable context keeps state across the
invocations of one execution.
This backend stores each value there under ``key_prefix + key``, with the expiry beside it. The
context object is the caller's: any
object with ``get_state(name)`` and ``set_state(name, value)`` works, so the backend does not import
the durable execution SDK.

Example:
    >>> import asyncio
    >>> from skye.store import DurableFunctionBackend
    >>> class Context:
    ...     def __init__(self): self.state = {}
    ...     def get_state(self, name): return self.state.get(name)
    ...     def set_state(self, name, value): self.state[name] = value
    >>> async def demo():
    ...     store = DurableFunctionBackend(Context())
    ...     await store.set("run", {"step": 3})
    ...     return await store.get("run")
    >>> asyncio.run(demo())
    {'step': 3}

Raises: ``ValidationError`` for an invalid key, value or time to live; ``ProviderError`` naming the
    operation when the context fails.
Missing: an absent or expired key reads as ``None``.
Concurrency: one execution runs one handler at a time; ``increment`` also holds a lock for the tasks
    of that handler.
"""

from __future__ import annotations

import asyncio
from typing import Any

from skye.base.interfaces.storage import ExpiryStore, StorageBackend, check_key, check_ttl
from skye.store._common import (
    Clock,
    check_data,
    check_items,
    count_of,
    default_clock,
    expiry_of,
    is_expired,
    provider_errors,
    remaining_of,
)

_VALUE = "value"
_EXPIRY = "expires_at"


class DurableFunctionBackend(StorageBackend, ExpiryStore):
    """Key-value, counter and expiry in the durable context of a Lambda durable function.

    Args:
        context: The durable context (anything with ``get_state`` and ``set_state``).
        key_prefix: Prepended to every key.
        clock: The time source for expiry; ``time.time`` by default.
    """

    def __init__(
        self, context: Any, key_prefix: str = "skye:", *, clock: Clock = default_clock
    ) -> None:
        """Keep the context; nothing is read until the first operation."""
        self.context = context
        self.key_prefix = key_prefix
        self._clock = clock
        self._lock = asyncio.Lock()

    def _name(self, key: str) -> str:
        return self.key_prefix + check_key(key)

    def _read(self, name: str) -> dict[str, Any] | None:
        entry = self._read_entry(name)
        return None if entry is None else entry[0]

    def _read_entry(self, name: str) -> tuple[dict[str, Any], float | None] | None:
        """The live value kept under ``name`` and its absolute expiry, or ``None``; an expired entry is cleared."""
        stored = self.context.get_state(name)
        if not isinstance(stored, dict) or not isinstance(stored.get(_VALUE), dict):
            return None
        if is_expired(stored.get(_EXPIRY), self._clock):
            self.context.set_state(name, None)
            return None
        return dict(stored[_VALUE]), stored.get(_EXPIRY)

    async def get(self, key: str) -> dict[str, Any] | None:
        """The value of ``key``, or ``None``."""
        name = self._name(key)
        with provider_errors("durable_function", "get"):
            return self._read(name)

    async def set(self, key: str, data: dict[str, Any], ttl: int | None = None) -> None:
        """Store ``data`` with its expiry in the durable context."""
        name = self._name(key)
        stored = {_VALUE: dict(check_data(data)), _EXPIRY: expiry_of(ttl, self._clock)}
        with provider_errors("durable_function", "set"):
            self.context.set_state(name, stored)

    async def delete(self, key: str) -> bool:
        """Clear ``key``; ``True`` when it held a live value."""
        name = self._name(key)
        with provider_errors("durable_function", "delete"):
            present = self._read(name) is not None
            self.context.set_state(name, None)
            return present

    async def increment(self, key: str, amount: int = 1, ttl: int | None = None) -> int:
        """Add ``amount`` to the counter of ``key`` under a lock."""
        name = self._name(key)
        check_ttl(ttl)
        async with self._lock:
            with provider_errors("durable_function", "increment"):
                current = self._read(name) or {}
                value = int(current.get("count", 0)) + amount
                self.context.set_state(
                    name, {_VALUE: {"count": value}, _EXPIRY: expiry_of(ttl, self._clock)}
                )
                return value

    async def count(self, key: str) -> int:
        """The count of ``key``; 0 when it is absent or expired. It does not create the key or move its expiry."""
        name = self._name(key)
        with provider_errors("durable_function", "count"):
            return count_of(self._read(name))

    async def is_alive(self, key: str) -> bool:
        """``True`` when ``key`` is present and has not expired."""
        name = self._name(key)
        with provider_errors("durable_function", "is_alive"):
            return self._read_entry(name) is not None

    async def remaining(self, key: str) -> int | None:
        """The seconds ``key`` has left (rounded up), or ``None`` when absent, expired or without expiry."""
        name = self._name(key)
        with provider_errors("durable_function", "remaining"):
            entry = self._read_entry(name)
        return None if entry is None else remaining_of(entry[1], self._clock)

    async def set_multiple(self, data: dict[str, dict[str, Any]], ttl: int | None = None) -> None:
        """Store every item; nothing is written when one key or value is invalid."""
        check_items(data)
        check_ttl(ttl)
        for key, value in data.items():
            await self.set(key, value, ttl)


__all__ = ["DurableFunctionBackend"]
