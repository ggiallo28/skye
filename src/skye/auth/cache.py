# D27
"""A lazy token cache with an expiry margin, and the bearer authenticator built on it.

The cache holds a token per credential identity and returns it until it is within ``margin`` seconds
of its deadline; it then fetches a new one on the calling thread. There is no timer and no
background thread (decisions D1). A secret never appears in a ``repr``.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping

#: A fetch function returns the token and how many seconds it stays valid.
Fetch = Callable[[], tuple[str, float]]

DEFAULT_MARGIN = 60.0


class TokenCache:
    """Tokens by credential identity, refreshed lazily shortly before they expire.

    Args:
        margin: Seconds before the deadline at which a token counts as expired.
        clock: A monotonic clock in seconds (replaced in tests).
    """

    def __init__(
        self, margin: float = DEFAULT_MARGIN, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._margin = margin
        self._clock = clock
        self._tokens: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def get(self, key: str, fetch: Fetch) -> str:
        """The cached token for ``key``, fetching a new one when missing or about to expire.

        Args:
            key: The credential identity (for example ``"google:sa:name@project"``).
            fetch: Called when there is no usable token; returns ``(token, seconds_valid)``.
        """
        with self._lock:
            now = self._clock()
            cached = self._tokens.get(key)
            if cached is not None and now < cached[1] - self._margin:
                return cached[0]
            token, ttl = fetch()
            self._tokens[key] = (token, now + ttl)
            return token

    def invalidate(self, key: str | None = None) -> None:
        """Forget the token of ``key`` (all when omitted), so the next ``get`` fetches again."""
        with self._lock:
            if key is None:
                self._tokens.clear()
            else:
                self._tokens.pop(key, None)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(tokens={len(self._tokens)})"


class CachedBearerAuth:
    """Authentication Port implementation: a header carrying a cached token (``Bearer`` by default).

    ``refresh()`` forgets the token, which is what the 401 retry helper calls
    (``skye.auth.refresh``).

    Args:
        key: The credential identity, the cache key.
        fetch: Returns ``(token, seconds_valid)``.
        cache: A cache to share between authenticators (a private one by default).
        header: The header to set.
        scheme: The prefix of the value (``Bearer``); empty for a bare value.
    """

    def __init__(
        self,
        key: str,
        fetch: Fetch,
        *,
        cache: TokenCache | None = None,
        header: str = "Authorization",
        scheme: str = "Bearer",
    ) -> None:
        self._key = key
        self._fetch = fetch
        self._cache = cache or TokenCache()
        self._header = header
        self._scheme = scheme

    def token(self) -> str:
        """The current token (cached, or freshly fetched)."""
        return self._cache.get(self._key, self._fetch)

    def refresh(self) -> None:
        """Drop the cached token: the next request fetches a new one."""
        self._cache.invalidate(self._key)

    def apply(
        self, method: str, url: str, headers: Mapping[str, str], body: bytes = b""
    ) -> dict[str, str]:
        """The headers with the token added; the input mapping is not modified."""
        value = f"{self._scheme} {self.token()}" if self._scheme else self.token()
        return {**headers, self._header: value}

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"
