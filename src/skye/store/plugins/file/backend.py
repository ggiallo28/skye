"""File backend: one JSON file per key in a folder, standard library only.

For local development and single-host persistence. The file name is the key percent-encoded, so
every key round-trips through
``keys``. Each value is written to a temporary file and renamed into place, so a reader never sees
half a file. File I/O runs in a
worker thread (``asyncio.to_thread``), never on the event loop.

Example:
    >>> import asyncio, tempfile
    >>> from skye.store import FileSystemBackend
    >>> async def demo(folder):
    ...     store = FileSystemBackend(folder)
    ...     await store.set("a/b", {"x": 1})
    ...     return await store.get("a/b"), await store.keys()
    >>> with tempfile.TemporaryDirectory() as folder:
    ...     asyncio.run(demo(folder))
    ({'x': 1}, ['a/b'])

Raises: ``ValidationError`` for an invalid key, value or time to live (D95); ``ProviderError`` when
    the folder cannot be read or
    written.
Missing: an absent, expired or unreadable file reads as ``None``.
Concurrency: ``increment`` is atomic between the tasks of one process (a lock); it is not atomic
    across processes that share the folder.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

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
    provider_errors,
    remaining_of,
)

_SUFFIX = ".json"
_EXPIRY = "_skye_expires_at"


class FileSystemBackend(StorageBackend, ScanStore, ExpiryStore):
    """Key-value, counter, scan and expiry over JSON files in ``base_path``.

    Args:
        base_path: The folder that holds the files; created on first write.
        clock: The time source for expiry; ``time.time`` by default.
    """

    def __init__(
        self, base_path: str = "/tmp/skye_storage", *, clock: Clock = default_clock
    ) -> None:
        """Remember the folder; nothing is created until the first write."""
        self.base_path = base_path
        self._root = Path(base_path)
        self._clock = clock
        self._lock = asyncio.Lock()

    def _path(self, key: str) -> Path:
        return self._root / (quote(key, safe="") + _SUFFIX)

    def _read(self, key: str) -> dict[str, Any] | None:
        entry = self._read_entry(key)
        return None if entry is None else entry[0]

    def _read_entry(self, key: str) -> tuple[dict[str, Any], float | None] | None:
        """The live value of ``key`` and its absolute expiry, or ``None``; an expired file is removed."""
        path = self._path(key)
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except ValueError:  # a corrupt file reads as absent; other OS errors become ProviderError
            return None
        if not isinstance(stored, dict):
            return None
        expiry = stored.pop(_EXPIRY, None)
        if is_expired(expiry, self._clock):
            path.unlink(missing_ok=True)
            return None
        return stored, expiry

    def _write(self, key: str, data: dict[str, Any], expiry: float | None) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        stored = dict(data)
        if expiry is not None:
            stored[_EXPIRY] = expiry
        handle, temp = tempfile.mkstemp(dir=self._root, suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as out:
                json.dump(stored, out)
            os.replace(temp, self._path(key))
        except BaseException:
            Path(temp).unlink(missing_ok=True)
            raise

    def _remove(self, key: str) -> bool:
        present = self._read(key) is not None
        self._path(key).unlink(missing_ok=True)
        return present

    def _list(self, prefix: str) -> list[str]:
        if not self._root.is_dir():
            return []
        found = []
        for path in self._root.iterdir():
            if not path.name.endswith(_SUFFIX):
                continue
            key = unquote(path.name[: -len(_SUFFIX)])
            if key.startswith(prefix) and self._read(key) is not None:
                found.append(key)
        return sorted(found)

    async def get(self, key: str) -> dict[str, Any] | None:
        """The value of ``key``, or ``None``."""
        check_key(key)
        with provider_errors("file", "get"):
            return await asyncio.to_thread(self._read, key)

    async def set(self, key: str, data: dict[str, Any], ttl: int | None = None) -> None:
        """Write ``data`` to the file of ``key``."""
        check_key(key)
        check_data(data)
        expiry = expiry_of(ttl, self._clock)
        with provider_errors("file", "set"):
            await asyncio.to_thread(self._write, key, data, expiry)

    async def delete(self, key: str) -> bool:
        """Remove the file of ``key``; ``True`` when it held a live value."""
        check_key(key)
        with provider_errors("file", "delete"):
            return await asyncio.to_thread(self._remove, key)

    async def increment(self, key: str, amount: int = 1, ttl: int | None = None) -> int:
        """Add ``amount`` to the counter of ``key`` under the lock of this process."""
        check_key(key)
        check_ttl(ttl)
        async with self._lock:
            current = await self.get(key) or {}
            value = int(current.get("count", 0)) + amount
            await self.set(key, {"count": value}, ttl)
            return value

    async def count(self, key: str) -> int:
        """The count of ``key``; 0 when it is absent or expired. It reads the file and does not rewrite it."""
        check_key(key)
        with provider_errors("file", "count"):
            return count_of(await asyncio.to_thread(self._read, key))

    async def is_alive(self, key: str) -> bool:
        """``True`` when the file of ``key`` holds a live value."""
        check_key(key)
        with provider_errors("file", "is_alive"):
            return await asyncio.to_thread(self._read_entry, key) is not None

    async def remaining(self, key: str) -> int | None:
        """The seconds ``key`` has left (rounded up), or ``None`` when absent, expired or without expiry."""
        check_key(key)
        with provider_errors("file", "remaining"):
            entry = await asyncio.to_thread(self._read_entry, key)
        return None if entry is None else remaining_of(entry[1], self._clock)

    async def set_multiple(self, data: dict[str, dict[str, Any]], ttl: int | None = None) -> None:
        """Write every item; nothing is written when one key or value is invalid."""
        check_items(data)
        check_ttl(ttl)
        for key, value in data.items():
            await self.set(key, value, ttl)

    async def keys(self, prefix: str = "", limit: int | None = None) -> list[str]:
        """The live keys that start with ``prefix``, sorted."""
        check_limit(limit)
        with provider_errors("file", "keys"):
            found = await asyncio.to_thread(self._list, prefix)
        return found if limit is None else found[:limit]


__all__ = ["FileSystemBackend"]
