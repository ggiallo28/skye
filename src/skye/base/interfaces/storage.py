# Requirement 12, decision D98, Requirement 60.10, D41, D95
"""Storage Ports: small capability Protocols for the key-value stores of ``store``.

A component asks only for the capabilities it uses, and a backend implements what it can:

* ``KeyValueStore``: ``get``, ``set``, ``delete``, ``get_multiple``, ``set_multiple`` (every
  backend);
* ``CounterStore``: an atomic ``increment`` and a read-only ``count`` (the router);
* ``ScanStore``: ``keys(prefix, limit)``, implemented by five backends of ``store`` (in-memory,
  file, Redis/Valkey, DynamoDB, PostgreSQL): every backend but the durable function;
* ``ExpiryStore``: ``is_alive(key)`` and ``remaining(key)``, the lifetime of a key without reading
  its value (the router keeps a cooldown as a key with a ``ttl`` and asks it here);
  every backend of ``store`` keeps an expiry, so every backend implements it.

``StorageBackend`` is key-value plus counter, the abstract base class every backend of ``store``
subclasses, so the code that typed
against it keeps working. A vector store is added with the first vector store of ``memory``.

A stored value is a JSON-compatible ``dict``. A time to live is ``None`` (no expiry) or a positive
``int`` of seconds; any other value
raises ``ValidationError`` before anything is written. ``check_ttl`` is the one place that
rule lives.

Raises: ``ValidationError`` for an invalid key or time to live; ``ProviderError`` when the backend
    is unreachable or rejects a call.
Missing: ``get`` returns ``None`` for an absent or expired key, ``get_multiple`` maps such a key to
    ``None``, ``delete`` returns
    ``False``, ``keys`` leaves it out, ``count`` returns 0, ``is_alive`` returns ``False`` and
    ``remaining`` returns ``None``; absence never raises.
Concurrency: a backend is shared by many tasks; ``increment`` is atomic across them (and across
    processes for the external stores).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable

from skye.base.exceptions import ValidationError


# decision D95
def check_ttl(ttl: object) -> int | None:
    """Return ``ttl`` when it is ``None`` or a positive ``int``; raise otherwise.

    Example:
        >>> check_ttl(30), check_ttl(None)
        (30, None)
        >>> check_ttl(0)
        Traceback (most recent call last):...
        skye.base.exceptions.ValidationError: ttl must be None or a positive number of seconds, got 0 | Details: {'field': 'ttl', 'value': 0}
    """
    if ttl is None:
        return None
    if isinstance(ttl, bool) or not isinstance(ttl, int) or ttl <= 0:
        raise ValidationError(
            f"ttl must be None or a positive number of seconds, got {ttl!r}", "ttl", ttl
        )
    return ttl


def check_key(key: object) -> str:
    """Return ``key`` when it is a non-empty ``str``; raise ``ValidationError`` otherwise."""
    if not isinstance(key, str) or not key:
        raise ValidationError(f"a storage key must be a non-empty string, got {key!r}", "key", key)
    return key


@runtime_checkable
class KeyValueStore(Protocol):
    """Read, write and delete JSON objects by key, with an optional time to live."""

    async def get(self, key: str) -> dict[str, Any] | None:
        """The value of ``key``, or ``None`` when it is absent or expired."""
        ...

    async def set(self, key: str, data: dict[str, Any], ttl: int | None = None) -> None:
        """Store ``data`` under ``key``, replacing any value; it expires after ``ttl`` seconds."""
        ...

    async def delete(self, key: str) -> bool:
        """Remove ``key``; ``True`` when it was there."""
        ...

    async def get_multiple(self, keys: list[str]) -> dict[str, dict[str, Any] | None]:
        """Every key of ``keys`` mapped to its value or ``None``, in the order given."""
        ...

    async def set_multiple(self, data: dict[str, dict[str, Any]], ttl: int | None = None) -> None:
        """Store every item of ``data`` with the same time to live."""
        ...


@runtime_checkable
class CounterStore(Protocol):
    """An atomic counter stored as ``{"count": n}`` under a key."""

    async def increment(self, key: str, amount: int = 1, ttl: int | None = None) -> int:
        """Add ``amount`` to the counter of ``key`` (an absent or expired key starts at 0) and
        return the new value.

        The stored value becomes ``{"count": n}``; ``ttl`` replaces the expiry of the key, ``None``
        removes it.
        """
        ...

    async def count(self, key: str) -> int:
        """The current count of ``key``: ``0`` when it is absent or expired.

        It only reads: it never creates the key and never changes its expiry, so the caller does not
        need to know that the count is stored as ``{"count": n}``.
        """
        ...


@runtime_checkable
class ExpiryStore(Protocol):
    """Ask whether a key is alive and how long it has left, without reading its value."""

    async def is_alive(self, key: str) -> bool:
        """``True`` when ``key`` is present and has not expired (a key with no expiry is alive).

        It only reads: it never creates the key and never moves its expiry.
        """
        ...

    async def remaining(self, key: str) -> int | None:
        """The whole seconds that ``key`` has left, rounded up, so at least 1 while it is alive.

        ``None`` when the key is absent, has expired, or never expires; ``is_alive`` tells the last
        case from the first two. It only reads: it never creates the key and never moves its expiry.
        """
        ...


@runtime_checkable
class ScanStore(Protocol):
    """List the keys that start with a prefix."""

    async def keys(self, prefix: str = "", limit: int | None = None) -> list[str]:
        """The live keys that start with ``prefix``, sorted, at most ``limit`` of them."""
        ...


# decision D98
class StorageBackend(KeyValueStore, CounterStore, ABC):
    """Key-value plus counter: the base class of every backend of ``store``.

    ``connect`` prepares the backend (a client, a table) and ``close`` releases it; both are safe to
    call more than once and
    the other methods connect on first use, so calling ``connect`` is optional.
    """

    async def connect(self) -> None:  # noqa: B027 - optional hook
        """Prepare the backend; the default does nothing."""

    async def close(self) -> None:  # noqa: B027 - optional hook
        """Release what the backend holds; the default does nothing."""

    @abstractmethod
    async def get(self, key: str) -> dict[str, Any] | None:
        """The value of ``key``, or ``None`` when it is absent or expired."""

    @abstractmethod
    async def set(self, key: str, data: dict[str, Any], ttl: int | None = None) -> None:
        """Store ``data`` under ``key``; it expires after ``ttl`` seconds when given."""

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """Remove ``key``; ``True`` when it was there."""

    @abstractmethod
    async def increment(self, key: str, amount: int = 1, ttl: int | None = None) -> int:
        """Atomically add ``amount`` to the counter of ``key`` and return the new value."""

    @abstractmethod
    async def count(self, key: str) -> int:
        """The count of ``key``, ``0`` when absent or expired; it never creates the key or moves its expiry."""

    async def get_multiple(self, keys: list[str]) -> dict[str, dict[str, Any] | None]:
        """Every key mapped to its value or ``None``; the default calls ``get`` once per key."""
        return {key: await self.get(key) for key in keys}

    async def set_multiple(self, data: dict[str, dict[str, Any]], ttl: int | None = None) -> None:
        """Store every item with the same time to live; the default calls ``set`` once per key."""
        check_ttl(ttl)
        for key, value in data.items():
            await self.set(key, value, ttl)


__all__ = ["CounterStore", "KeyValueStore", "ScanStore", "StorageBackend", "check_key", "check_ttl"]
