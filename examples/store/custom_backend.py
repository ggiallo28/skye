"""Your own durable-state backend behind the StorageBackend Port (Live).

``StorageBackend`` is key-value plus counter (decision D98); ``ScanStore`` adds ``keys`` by prefix.
Subclass, implement the abstract async methods, register the class with ``register_backend`` and
check it with the public conformance suite (``check_backend``). This example backs it with a plain
dict to keep the focus on the shape of the Ports; it ignores expiry, so it skips the full suite.
"""

import asyncio
from typing import Any

from skye.interfaces import ScanStore, StorageBackend
from skye.store import backend, register_backend


class DictBackend(StorageBackend, ScanStore):
    """A minimal StorageBackend kept entirely in a dictionary."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}

    async def connect(self) -> None:
        """No connection to open for an in-process dict."""

    async def get(self, key: str) -> dict[str, Any] | None:
        return self._data.get(key)

    async def set(self, key: str, data: dict[str, Any], ttl: int | None = None) -> None:
        self._data[key] = dict(data)

    async def delete(self, key: str) -> bool:
        return self._data.pop(key, None) is not None

    async def keys(self, prefix: str = "", limit: int | None = None) -> list[str]:
        found = sorted(k for k in self._data if k.startswith(prefix))
        return found if limit is None else found[:limit]

    async def increment(self, key: str, amount: int = 1, ttl: int | None = None) -> int:
        current = await self.get(key) or {}
        new_value = current.get("count", 0) + amount
        await self.set(key, {"count": new_value}, ttl)
        return new_value

    async def count(self, key: str) -> int:
        current = await self.get(key) or {}
        return int(current.get("count", 0))

    async def get_multiple(self, keys: list[str]) -> dict[str, dict[str, Any] | None]:
        return {key: await self.get(key) for key in keys}

    async def set_multiple(self, data: dict[str, dict[str, Any]], ttl: int | None = None) -> None:
        for key, value in data.items():
            await self.set(key, value, ttl)


async def main() -> None:
    register_backend("dict", DictBackend, replace=True)
    store = backend("dict")
    await store.connect()

    await store.set_multiple({"user:1": {"name": "Ada"}, "user:2": {"name": "Grace"}})
    print("get(user:1):", await store.get("user:1"))
    print("increment(hits):", await store.increment("hits", amount=3))
    print("count(hits):", await store.count("hits"))
    print("get_multiple:", await store.get_multiple(["user:1", "user:2", "missing"]))
    print("keys(user:):", await store.keys("user:"))


if __name__ == "__main__":
    asyncio.run(main())
