"""Redis and Valkey backend (decisions D99, D102): any server that speaks the Redis protocol.

The driver is ``valkey`` (valkey-py, extra ``valkey``) when installed, else ``redis`` (redis-py,
extra ``redis``); both have the same API, so install only one. ``driver=`` forces one, and
``skye.store.backend("valkey", ...)`` is a second name for this class.

A value is stored as JSON under ``key_prefix + key``; the time to live is the server's own expiry
(``EX``). ``increment`` runs one Lua script on the server, so it is atomic across processes and
keeps the value a JSON ``{"count": n}`` like the other backends. ``keys`` uses ``SCAN`` with the
prefix (never ``KEYS``), with the glob characters of the prefix escaped.

Example:
    >>> from skye.store import RedisBackend
    >>> store = RedisBackend("rediss://cache.example.com:6379/0", key_prefix="app:")  # no call yet

Raises: ``ValidationError`` for an invalid key, value or time to live; ``MissingExtraError`` naming
    ``valkey`` (and noting ``redis``) when neither driver is installed; ``ProviderError`` naming the
    operation when a call fails. The URL is never put in an error or a log.
Missing: an absent or expired key reads as ``None``.
Concurrency: every operation is one round trip or one pipeline; ``increment`` is atomic on the
    server.
"""

from __future__ import annotations

import importlib.util
import json
from typing import Any, Literal

from skye.base.exceptions import MissingExtraError, ValidationError
from skye.base.interfaces.storage import (
    ExpiryStore,
    ScanStore,
    StorageBackend,
    check_key,
    check_ttl,
)
from skye.base.lazy_import import missing_extra
from skye.store._common import check_data, check_items, check_limit, count_of, provider_errors

#: Read the JSON value (or nothing), add the amount to ``count``, write ``{"count": n}`` with the
#: expiry (or none), and return ``n``.
INCREMENT_SCRIPT = """
local current = redis.call('GET', KEYS[1])
local count = 0
if current then
  local ok, decoded = pcall(cjson.decode, current)
  if ok and type(decoded) == 'table' and tonumber(decoded['count']) then
    count = tonumber(decoded['count'])
  end
end
count = count + tonumber(ARGV[1])
local encoded = cjson.encode({count = count})
if tonumber(ARGV[2]) > 0 then
  redis.call('SET', KEYS[1], encoded, 'EX', tonumber(ARGV[2]))
else
  redis.call('SET', KEYS[1], encoded)
end
return count
"""

_GLOB = str.maketrans({c: "\\" + c for c in "*?[]\\"})

Driver = Literal["valkey", "redis"]


def choose_driver() -> Driver:
    """``valkey`` when installed, else ``redis``, else ``MissingExtraError`` (D102)."""
    if importlib.util.find_spec("valkey") is not None:
        return "valkey"
    if importlib.util.find_spec("redis") is not None:
        return "redis"
    error = MissingExtraError(extra="valkey", missing="valkey")
    error.add_note("Or the redis-py driver, same API: pip install skyeai[redis]")
    raise error


class RedisBackend(StorageBackend, ScanStore, ExpiryStore):
    """Key-value, counter, scan and expiry in Redis or Valkey.

    Args:
        redis_url: The connection URL (``redis://``, ``rediss://`` for TLS); it may hold a password,
            so it is never logged.
        key_prefix: Prepended to every key, so several applications can share one database.
        driver: Force ``"valkey"`` or ``"redis"`` instead of the order of D102.
        client: An asyncio client to use instead of creating one (tests pass a fake one).
    """

    def __init__(
        self,
        redis_url: str | None = None,
        key_prefix: str = "skye:",
        *,
        driver: Driver | None = None,
        client: Any = None,
    ) -> None:
        """Remember the settings; the driver is imported on first use."""
        if redis_url is None and client is None:
            raise ValidationError("RedisBackend needs redis_url or client", "redis_url", None)
        self._url = redis_url
        self.key_prefix = key_prefix
        self.driver = driver
        self._redis: Any = client

    def _client(self) -> Any:
        if self._redis is None:
            driver = self.driver or choose_driver()
            if driver == "valkey":
                module = missing_extra("valkey.asyncio", extra="valkey", package="valkey")
            else:
                module = missing_extra("redis.asyncio", extra="redis", package="redis")
            self.driver = driver
            self._redis = module.from_url(self._url)
        return self._redis

    def _key(self, key: str) -> str:
        return self.key_prefix + check_key(key)

    async def connect(self) -> None:
        """Create the client (the first command opens the connection)."""
        self._client()

    async def close(self) -> None:
        """Close the client."""
        if self._redis is not None:
            closer = getattr(self._redis, "aclose", None) or getattr(self._redis, "close", None)
            if closer is not None:
                await closer()
            self._redis = None

    async def get(self, key: str) -> dict[str, Any] | None:
        """The value of ``key``, or ``None``."""
        name = self._key(key)
        with provider_errors("redis", "get"):
            raw = await self._client().get(name)
        return _decode(raw)

    async def set(self, key: str, data: dict[str, Any], ttl: int | None = None) -> None:
        """Store ``data`` as JSON with Redis's expiry."""
        name = self._key(key)
        payload = json.dumps(check_data(data))
        expiry = check_ttl(ttl)
        with provider_errors("redis", "set"):
            await self._client().set(name, payload, ex=expiry)

    async def delete(self, key: str) -> bool:
        """``DEL`` the key; ``True`` when it existed."""
        name = self._key(key)
        with provider_errors("redis", "delete"):
            return bool(await self._client().delete(name))

    async def increment(self, key: str, amount: int = 1, ttl: int | None = None) -> int:
        """Run the increment script on the server and return the new count."""
        name = self._key(key)
        expiry = check_ttl(ttl) or 0
        with provider_errors("redis", "increment"):
            return int(await self._client().eval(INCREMENT_SCRIPT, 1, name, amount, expiry))

    async def count(self, key: str) -> int:
        """One ``GET``; the count of ``key``, 0 when it is absent or expired. A ``GET`` does not move the server's expiry."""
        name = self._key(key)
        with provider_errors("redis", "count"):
            raw = await self._client().get(name)
        return count_of(_decode(raw))

    async def is_alive(self, key: str) -> bool:
        """One ``EXISTS``; the server drops an expired key, so a key it has is alive."""
        name = self._key(key)
        with provider_errors("redis", "is_alive"):
            return bool(await self._client().exists(name))

    async def remaining(self, key: str) -> int | None:
        """One ``PTTL`` (milliseconds, rounded up to whole seconds); ``None`` when absent, expired or without expiry."""
        name = self._key(key)
        with provider_errors("redis", "remaining"):
            millis = int(await self._client().pttl(name))
        return None if millis < 0 else max(1, -(-millis // 1000))

    async def get_multiple(self, keys: list[str]) -> dict[str, dict[str, Any] | None]:
        """One ``MGET`` for all keys."""
        names = [self._key(key) for key in keys]
        if not names:
            return {}
        with provider_errors("redis", "get_multiple"):
            values = await self._client().mget(names)
        return {key: _decode(raw) for key, raw in zip(keys, values, strict=True)}

    async def set_multiple(self, data: dict[str, dict[str, Any]], ttl: int | None = None) -> None:
        """One pipeline of ``SET``; nothing is sent when one key or value is invalid."""
        check_items(data)
        expiry = check_ttl(ttl)
        if not data:
            return
        with provider_errors("redis", "set_multiple"):
            pipe = self._client().pipeline()
            for key, value in data.items():
                pipe.set(self._key(key), json.dumps(value), ex=expiry)
            await pipe.execute()

    async def keys(self, prefix: str = "", limit: int | None = None) -> list[str]:
        """``SCAN`` for ``key_prefix + prefix*``; keys come back without ``key_prefix``, sorted."""
        check_limit(limit)
        pattern = (self.key_prefix + prefix).translate(_GLOB) + "*"
        found = []
        with provider_errors("redis", "keys"):
            async for name in self._client().scan_iter(match=pattern):
                text = name.decode() if isinstance(name, bytes) else str(name)
                found.append(text[len(self.key_prefix) :])
        found.sort()
        return found if limit is None else found[:limit]


def _decode(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    value = json.loads(raw)
    return value if isinstance(value, dict) else None


__all__ = ["RedisBackend"]
