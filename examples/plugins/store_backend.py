"""Add a store backend.

To add a store backend you use the decorator `@plugins.backend("name")` on top of a class.

The class has the methods of the `StorageBackend` Port, all `async`:

* `get`, `set`, `delete` and `get_multiple`, `set_multiple`: values are JSON objects, with an
  optional time to live.
* `increment` and `count`: an atomic counter; `count` is 0 when the key is absent or expired.
* `connect`, which opens what the backend needs.

`skye.backend("name")` builds it (the same word, `backend`, to add and to build), and
`check_backend` runs the conformance suite over it.

Tip: this one keeps a dict and ignores the time to live, to keep the shape of the Port in view. A
real one talks to a database.
"""

import asyncio
from typing import Any

import skye
from skye.interfaces import StorageBackend

plugins = skye.Plugins()


@plugins.backend("acme-dict")
class DictBackend(StorageBackend):
    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}

    async def connect(self) -> None:
        """Nothing to open for a dict."""

    async def get(self, key: str) -> dict[str, Any] | None:
        return self._data.get(key)

    async def set(self, key: str, data: dict[str, Any], ttl: int | None = None) -> None:
        self._data[key] = dict(data)

    async def delete(self, key: str) -> bool:
        return self._data.pop(key, None) is not None

    async def increment(self, key: str, amount: int = 1, ttl: int | None = None) -> int:
        count = await self.count(key) + amount
        self._data[key] = {"count": count}
        return count

    async def count(self, key: str) -> int:
        return (self._data.get(key) or {}).get("count", 0)

    async def get_multiple(self, keys: list[str]) -> dict[str, dict[str, Any] | None]:
        return {key: self._data.get(key) for key in keys}

    async def set_multiple(self, data: dict[str, dict[str, Any]], ttl: int | None = None) -> None:
        for key, value in data.items():
            self._data[key] = dict(value)


async def main() -> None:
    store = skye.backend("acme-dict")
    await store.connect()
    await store.set("greeting", {"text": "hello from a plugin"})
    print("get:", await store.get("greeting"))
    print("count:", await store.increment("hits", 3), await store.count("hits"))


if __name__ == "__main__":
    asyncio.run(main())
