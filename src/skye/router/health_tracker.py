"""Health and rate limit tracking for model router.

This module contains classes for tracking model health, rate limits, and performance metrics. All
state is stored via the storage backend. Storage backend is initialized by the ModelRouter.
"""

import asyncio
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from skye.base.interfaces import StorageBackend
from skye.base.interfaces.storage import ExpiryStore
from skye.store import backend

#: A source of the current time in seconds since the epoch (the ``FakeClock`` of ``skye.store`` in tests).
Clock = Callable[[], float]


def wall_clock() -> float:
    """The real time. It reads ``time.time`` at each call, so a test that replaces ``time.time`` still drives it."""
    return time.time()


def _memory_store() -> StorageBackend:
    """The default storage (decision D97): the in-memory backend, built by the factory of the store."""
    return backend("memory")


#: The window of the allowed-fails policy: only the failures of the last minute count.
RECENT_FAILURES_WINDOW_SECONDS = 60.0
#: How long the health counts live after their last update.
HEALTH_TTL_SECONDS = 86400


@dataclass
class RateLimitTracker:
    """Track rate limits for a model deployment.

    All state is stored via the storage backend for consistency across both traditional and
    serverless environments.
    """

    tpm_limit: int | None = None  # Tokens per minute
    rpm_limit: int | None = None  # Requests per minute
    model_id: str = ""
    storage: StorageBackend = field(default_factory=_memory_store)
    window_seconds: int = 60  # Rate limit window
    clock: Clock = (
        wall_clock  # Chooses the window of a count; the store keeps its own clock for expiry
    )

    def _get_window_key(self, metric_type: str) -> str:
        """Get storage key for current time window."""
        current_window = int(self.clock()) // self.window_seconds
        return f"rate_limit:{self.model_id}:{metric_type}:{current_window}"

    def _get_active_requests_key(self) -> str:
        """Get storage key for active requests counter."""
        return f"active_requests:{self.model_id}"

    async def can_accept_request(self, estimated_tokens: int = 0) -> bool:
        """Check if request can be accepted within rate limits."""
        # Check RPM limit
        if self.rpm_limit:
            rpm_key = self._get_window_key("rpm")
            current_rpm = await self.storage.count(rpm_key)
            if current_rpm >= self.rpm_limit:
                return False

        # Check TPM limit
        if self.tpm_limit and estimated_tokens > 0:
            tpm_key = self._get_window_key("tpm")
            current_tpm = await self.storage.count(tpm_key)
            if current_tpm + estimated_tokens > self.tpm_limit:
                return False

        return True

    async def record_request(self, tokens_used: int) -> None:
        """Record a completed request."""
        # Update both RPM and TPM counters atomically
        rpm_key = self._get_window_key("rpm")
        await self.storage.increment(rpm_key, 1, ttl=self.window_seconds * 2)

        if tokens_used > 0:
            tpm_key = self._get_window_key("tpm")
            await self.storage.increment(tpm_key, tokens_used, ttl=self.window_seconds * 2)

    async def increment_active_requests(self) -> int:
        """Increment active requests counter."""
        active_key = self._get_active_requests_key()
        return await self.storage.increment(active_key, 1, ttl=3600)  # 1 hour TTL

    async def decrement_active_requests(self) -> int:
        """Decrement active requests counter."""
        active_key = self._get_active_requests_key()
        return await self.storage.increment(active_key, -1, ttl=3600)  # 1 hour TTL

    async def get_current_usage(self) -> dict[str, Any]:
        """Get current usage statistics."""
        rpm_key = self._get_window_key("rpm")
        tpm_key = self._get_window_key("tpm")
        active_key = self._get_active_requests_key()

        rpm_used, tpm_used, active = await asyncio.gather(
            self.storage.count(rpm_key), self.storage.count(tpm_key), self.storage.count(active_key)
        )

        return {
            "rpm_used": rpm_used,
            "tpm_used": tpm_used,
            "rpm_limit": self.rpm_limit,
            "tpm_limit": self.tpm_limit,
            "active_requests": active,
        }


@dataclass
class ModelHealth:
    """Health tracking for a model deployment.

    All state is stored via the storage backend for consistency across both traditional and
    serverless environments. Every count is an atomic ``increment`` of the store (``CounterStore``),
    so two processes that record at the same time lose no count; only the latest times and the
    lowest and highest latency are plain values (the last writer wins).

    Keys (``<id>`` is the model id; health keys live 24 hours from the last update):

    - ``health:<id>:success``, ``health:<id>:failure``: the counts;
    - ``health:<id>:latency_us``: the total latency of the successes, in microseconds;
    - ``health:<id>:reason:<error type>``: the failures of one error type, and
      ``health:<id>:reasons`` the names seen;
    - ``health:<id>:last``: the time of the last success and of the last failure, and the lowest and
      highest latency;
    - ``recent_failures:<id>:<error type>:<second>``: the failures of one second, for the
      allowed-fails window;
    - ``cooldown:<id>``: the cooldown, a key with a ``ttl`` of its duration: it is in cooldown while the key is alive
      (read through ``ExpiryStore``), and the value only says when it ends.
    """

    model_id: str
    storage: StorageBackend = field(default_factory=_memory_store)
    tags: list[str] = field(default_factory=list)
    clock: Clock = (
        wall_clock  # The time of the last success and failure and the second of a recent failure
    )

    def _key(self, name: str) -> str:
        return f"health:{self.model_id}:{name}"

    def _get_cooldown_key(self) -> str:
        """Get storage key for cooldown data."""
        return f"cooldown:{self.model_id}"

    def _recent_key(self, reason: str, second: int) -> str:
        """The key of the failures of one error type in one second."""
        return f"recent_failures:{self.model_id}:{reason}:{second}"

    async def _merge_last(self, **values: float) -> None:
        """Write the latest times and the latency range (a lost update loses a time, never a count)."""
        key = self._key("last")
        data = await self.storage.get(key) or {}
        for name, value in values.items():
            if name == "min_latency_ms":
                value = min(data.get(name, value), value)
            elif name == "max_latency_ms":
                value = max(data.get(name, value), value)
            data[name] = value
        await self.storage.set(key, data, ttl=HEALTH_TTL_SECONDS)

    async def record_success(self, latency_ms: float) -> None:
        """Record a successful request."""
        await self.storage.increment(self._key("success"), 1, ttl=HEALTH_TTL_SECONDS)
        await self.storage.increment(
            self._key("latency_us"), max(0, round(latency_ms * 1000)), ttl=HEALTH_TTL_SECONDS
        )
        await self._merge_last(
            last_success_time=self.clock(), min_latency_ms=latency_ms, max_latency_ms=latency_ms
        )

    async def record_failure(
        self, reason: str = "unknown", window_reason: str | None = None
    ) -> None:
        """Record a failed request.

        Args:
            reason: The error type, counted in ``failure_reasons``.
            window_reason: The name the allowed-fails window counts this failure under (the policy
                entry that matched the error); ``reason`` when not given.
        """
        current_time = self.clock()
        await self.storage.increment(self._key("failure"), 1, ttl=HEALTH_TTL_SECONDS)
        await self.storage.increment(self._key(f"reason:{reason}"), 1, ttl=HEALTH_TTL_SECONDS)
        reasons_key = self._key("reasons")
        known = await self.storage.get(reasons_key) or {}
        names = list(known.get("names", []))
        if reason not in names:
            # Add-only: a name lost to a concurrent write is added again by the next failure of that
            # type.
            await self.storage.set(reasons_key, {"names": [*names, reason]}, ttl=HEALTH_TTL_SECONDS)
        else:
            await self.storage.set(reasons_key, known, ttl=HEALTH_TTL_SECONDS)
        await self._merge_last(last_failure_time=current_time)
        # The allowed-fails policy counts per minute: one counter per second, kept twice the window.
        await self.storage.increment(
            self._recent_key(window_reason or reason, int(current_time)),
            1,
            ttl=int(RECENT_FAILURES_WINDOW_SECONDS) * 2,
        )

    async def recent_failure_count(
        self, reason: str, window_seconds: float = RECENT_FAILURES_WINDOW_SECONDS
    ) -> int:
        """The number of failures of this error type in the last ``window_seconds`` (whole seconds).

        Only the failures of the recorded window (``RECENT_FAILURES_WINDOW_SECONDS``) are kept.
        """
        now = self.clock()
        newest = int(now)
        oldest = int(now - min(window_seconds, RECENT_FAILURES_WINDOW_SECONDS)) + 1
        keys = [self._recent_key(reason, second) for second in range(oldest, newest + 1)]
        # ``count`` reads one key: the keys are read together, so the wait is one round trip of the store.
        return sum(await asyncio.gather(*(self.storage.count(key) for key in keys)))

    async def set_cooldown(self, duration_seconds: float) -> None:
        """Set the cooldown: a key that lives for the duration, in whole seconds rounded up.

        A new cooldown replaces the previous one; a duration of zero or less ends it.
        """
        cooldown_key = self._get_cooldown_key()
        if duration_seconds <= 0:
            await self.storage.delete(cooldown_key)
            return
        ttl = max(1, math.ceil(duration_seconds))
        await self.storage.set(cooldown_key, {"cooldown_until": self.clock() + ttl}, ttl=ttl)

    async def is_in_cooldown(self) -> bool:
        """Check if the model is in cooldown: its cooldown key is alive.

        The store says it (``ExpiryStore.is_alive``); a backend that has no ``ExpiryStore`` drops an expired key on
        ``get``, so a present value is a live one. No stored time is compared with the clock.
        """
        key = self._get_cooldown_key()
        if isinstance(self.storage, ExpiryStore):
            return await self.storage.is_alive(key)
        return await self.storage.get(key) is not None

    async def _counts(self) -> tuple[int, int, float]:
        """The success count, the failure count and the total latency in milliseconds."""
        success, failure, latency_us = await asyncio.gather(
            self.storage.count(self._key("success")),
            self.storage.count(self._key("failure")),
            self.storage.count(self._key("latency_us")),
        )
        return success, failure, latency_us / 1000.0

    async def get_success_rate(self) -> float:
        """Get success rate from storage."""
        success_count, failure_count, _ = await self._counts()
        total = success_count + failure_count
        if total == 0:
            return 1.0
        return success_count / total

    async def get_avg_latency_ms(self) -> float:
        """Get average latency from storage."""
        success_count, _, total_latency_ms = await self._counts()
        if success_count == 0:
            return float("inf")
        return total_latency_ms / success_count

    async def get_health_metrics(self) -> dict[str, Any]:
        """Get comprehensive health metrics."""
        success_count, failure_count, total_latency_ms = await self._counts()
        data = await self.storage.get_multiple([self._key("last"), self._key("reasons")])
        last = data[self._key("last")] or {}
        names = list((data[self._key("reasons")] or {}).get("names", []))
        reason_counts = await asyncio.gather(
            *(self.storage.count(self._key(f"reason:{n}")) for n in names)
        )
        failure_reasons = dict(zip(names, reason_counts, strict=True))
        in_cooldown = await self.is_in_cooldown()
        cooldown_until = None
        if in_cooldown:
            cooldown_until = (await self.storage.get(self._get_cooldown_key()) or {}).get(
                "cooldown_until"
            )
        total_requests = success_count + failure_count

        return {
            "model_id": self.model_id,
            "success_count": success_count,
            "failure_count": failure_count,
            "total_requests": total_requests,
            "success_rate": success_count / total_requests if total_requests > 0 else 1.0,
            "average_latency_ms": total_latency_ms / success_count if success_count > 0 else 0.0,
            "min_latency_ms": last.get("min_latency_ms"),
            "max_latency_ms": last.get("max_latency_ms"),
            "last_success_time": last.get("last_success_time"),
            "last_failure_time": last.get("last_failure_time"),
            "is_in_cooldown": in_cooldown,
            "cooldown_until": cooldown_until,
            "failure_reasons": {name: count for name, count in failure_reasons.items() if count},
            "tags": self.tags,
        }
