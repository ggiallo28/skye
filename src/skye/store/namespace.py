# Requirement 60.10, O63
"""A namespace over a store: ``namespaced(store, "router")`` puts a prefix on every key.

Several components keep state in one store (the router, and later the memory and the agents). Each
one takes a namespace, so
that its keys never meet the keys of another and no component writes the prefix of its keys by hand.
``namespaced(store,
prefix)`` returns a store whose key ``"health:m"`` is ``"<prefix>:health:m"`` in ``store``.

The returned store has the ports that ``store`` has: key-value and counter always, ``ExpiryStore``
when ``store`` has
``is_alive`` and ``remaining``, ``ScanStore`` when it has ``keys``. ``keys(prefix, limit)`` lists
only the keys of the namespace
and gives them back without the prefix. Namespaces nest: ``namespaced(namespaced(store, "a"), "b")``
writes ``"a:b:key"``.

Example:
    >>> import asyncio
    >>> from skye.store import InMemoryBackend, namespaced
    >>> async def demo():
    ...     store = InMemoryBackend()
    ...     router = namespaced(store, "router")
    ...     await router.set("health:m", {"ok": True})
    ...     return await store.keys(), await router.keys()
    >>> asyncio.run(demo())
    (['router:health:m'], ['health:m'])

Raises: ``ValidationError`` for a prefix that is empty, not a string or has a ``:``, and for an
invalid key or value (the same
    rules as the store).
Missing: an absent key reads as in the store (``None``, 0, ``False``).
Concurrency: the wrapper holds no state; it is as safe as the store it wraps. ``close()`` closes the
store itself, so call it
    once, from the code that owns the store, and not from each component that has a namespace.
"""

from __future__ import annotations

from typing import Any

from skye.base.exceptions import ValidationError
from skye.base.interfaces.storage import (
    ExpiryStore,
    ScanStore,
    StorageBackend,
    check_key,
)

SEPARATOR = ":"


def check_namespace(prefix: object) -> str:
    """Return ``prefix`` when it is a non-empty ``str`` without ``:``; raise ``ValidationError``
    otherwise."""
    if not isinstance(prefix, str) or not prefix or SEPARATOR in prefix:
        raise ValidationError(
            f"a namespace must be a non-empty string without {SEPARATOR!r}, got {prefix!r}",
            "prefix",
            prefix,
        )
    return prefix


class _Namespaced(StorageBackend):
    """Key-value and counter over a prefix of the keys of another store."""

    def __init__(self, store: Any, prefix: str) -> None:
        self._store = store
        self._prefix = check_namespace(prefix)

    @property
    def store(self) -> Any:
        """The store this namespace is over (it holds the keys with the prefix)."""
        return self._store

    @property
    def namespace(self) -> str:
        """The prefix of the keys of this namespace."""
        return self._prefix

    def _key(self, key: str) -> str:
        return f"{self._prefix}{SEPARATOR}{check_key(key)}"

    def __repr__(self) -> str:
        return f"namespaced({self._store!r}, {self._prefix!r})"

    async def connect(self) -> None:
        """Open the store (the same call as on the store itself)."""
        await self._store.connect()

    async def close(self) -> None:
        """Close the store: it is shared by every namespace over it."""
        await self._store.close()

    async def get(self, key: str) -> dict[str, Any] | None:
        return await self._store.get(self._key(key))  # type: ignore[no-any-return]

    async def set(self, key: str, data: dict[str, Any], ttl: int | None = None) -> None:
        await self._store.set(self._key(key), data, ttl)

    async def delete(self, key: str) -> bool:
        return await self._store.delete(self._key(key))  # type: ignore[no-any-return]

    async def increment(self, key: str, amount: int = 1, ttl: int | None = None) -> int:
        return await self._store.increment(self._key(key), amount, ttl)  # type: ignore[no-any-return]

    async def count(self, key: str) -> int:
        return await self._store.count(self._key(key))  # type: ignore[no-any-return]

    async def get_multiple(self, keys: list[str]) -> dict[str, dict[str, Any] | None]:
        inner = {self._key(key): key for key in keys}
        found = await self._store.get_multiple(list(inner))
        return {inner[full]: value for full, value in found.items() if full in inner}

    async def set_multiple(self, data: dict[str, dict[str, Any]], ttl: int | None = None) -> None:
        await self._store.set_multiple({self._key(key): value for key, value in data.items()}, ttl)


class _ExpiryView(ExpiryStore):
    """The expiry port of a namespace (when the store has it)."""

    _store: Any
    _key: Any

    async def is_alive(self, key: str) -> bool:
        return await self._store.is_alive(self._key(key))  # type: ignore[no-any-return]

    async def remaining(self, key: str) -> int | None:
        return await self._store.remaining(self._key(key))  # type: ignore[no-any-return]


class _ScanView(ScanStore):
    """The scan port of a namespace (when the store has it)."""

    _store: Any
    _prefix: str

    async def keys(self, prefix: str = "", limit: int | None = None) -> list[str]:
        head = f"{self._prefix}{SEPARATOR}"
        found = await self._store.keys(head + prefix, limit)
        return [key[len(head) :] for key in found if key.startswith(head)]


class _NamespacedExpiry(_ExpiryView, _Namespaced):
    pass


class _NamespacedScan(_ScanView, _Namespaced):
    pass


class _NamespacedExpiryScan(_ExpiryView, _ScanView, _Namespaced):
    pass


def namespaced(store: Any, prefix: str) -> StorageBackend:
    """A store whose keys are ``store``'s keys with ``prefix`` and ``:`` in front.

    Args:
        store: Any store of ``skye.store``, or another namespace.
        prefix: The namespace, a non-empty string without ``:``.

    Returns:
        A ``StorageBackend`` that also has ``ExpiryStore`` and ``ScanStore`` when ``store`` has
        them.

    Raises:
        ValidationError: ``prefix`` is empty, not a string or holds a ``:``.
    """
    check_namespace(prefix)
    expiry = hasattr(store, "is_alive") and hasattr(store, "remaining")
    scan = hasattr(store, "keys")
    cls: type[_Namespaced]
    if expiry and scan:
        cls = _NamespacedExpiryScan
    elif expiry:
        cls = _NamespacedExpiry
    elif scan:
        cls = _NamespacedScan
    else:
        cls = _Namespaced
    return cls(store, prefix)


__all__ = ["check_namespace", "namespaced"]
