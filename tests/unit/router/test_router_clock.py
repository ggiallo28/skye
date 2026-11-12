"""The router keeps time only with the clock it is given and reads its counters and cooldowns through the store Ports (task 8.3).

Requirements 60.9, 60.10 and 60.11, decision D97. ``time.time`` is frozen on a value that is far from the ``FakeClock``, so a router
that read it for a cooldown, a window or an expiry would fail these tests.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from skye.base.exceptions import ProviderError
from skye.base.interfaces import StorageBackend
from skye.router import ModelRouter
from skye.router.config_models import AllowedFailsPolicyConfig, RetryPolicyConfig
from skye.router.health_tracker import ModelHealth, RateLimitTracker
from skye.store import FakeClock, backend
from tests.unit.router.fakes import FakeModel, RateLimitError, timed

MESSAGES: list[Any] = []


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    """A ``FakeClock`` on a minute boundary; ``time.time`` is frozen far away from it."""
    monkeypatch.setattr(time, "time", lambda: 5.0)
    return FakeClock(start=60.0 * 100_000)


class StoreProxy:
    """A store that forwards to another and records what the router asks of it.

    ``reads`` is the keys read with ``get`` or ``get_multiple``, ``alive`` the keys asked with ``is_alive``, ``counted`` the keys
    asked with ``count``.
    """

    def __init__(self, inner: StorageBackend, *, expiry: bool = True) -> None:
        self._inner = inner
        self._expiry = expiry
        self.reads: list[str] = []
        self.alive: list[str] = []
        self.counted: list[str] = []

    async def get(self, key: str) -> dict[str, Any] | None:
        self.reads.append(key)
        return await self._inner.get(key)

    async def get_multiple(self, keys: list[str]) -> dict[str, dict[str, Any] | None]:
        self.reads.extend(keys)
        return await self._inner.get_multiple(keys)

    async def count(self, key: str) -> int:
        self.counted.append(key)
        return await self._inner.count(key)

    async def is_alive(self, key: str) -> bool:
        self.alive.append(key)
        return await self._inner.is_alive(key)  # type: ignore[attr-defined, no-any-return]

    def __getattr__(self, name: str) -> Any:
        if name in {"is_alive", "remaining"} and not self._expiry:
            raise AttributeError(name)
        return getattr(self._inner, name)


def _health(clock: FakeClock, store: Any = None) -> ModelHealth:
    return ModelHealth(model_id="m", storage=store or backend("memory", clock=clock), clock=clock)


# --- the default store and the clock ---------------------------------------------------------------------------


def test_the_default_store_is_the_memory_backend_of_the_factory() -> None:
    assert type(ModelRouter().storage_backend) is type(backend("memory"))


async def test_a_cooldown_ends_with_the_clock_it_is_given(clock: FakeClock) -> None:
    health = _health(clock)
    await health.set_cooldown(60)
    clock.advance(59)
    assert await health.is_in_cooldown()
    clock.advance(1)
    assert not await health.is_in_cooldown()


async def test_a_cooldown_is_read_through_expiry_store_and_its_end_is_on_the_clock(
    clock: FakeClock,
) -> None:
    store = StoreProxy(backend("memory", clock=clock))
    health = _health(clock, store)
    await health.set_cooldown(30)

    assert await health.is_in_cooldown()
    assert store.alive == ["cooldown:m"]
    assert (await health.get_health_metrics())["cooldown_until"] == clock() + 30


async def test_a_store_with_no_expiry_store_still_ends_the_cooldown(clock: FakeClock) -> None:
    store = StoreProxy(backend("memory", clock=clock), expiry=False)
    health = _health(clock, store)
    await health.set_cooldown(10)
    assert await health.is_in_cooldown()
    assert store.alive == []
    clock.advance(10)
    assert not await health.is_in_cooldown()


async def test_a_cooldown_of_a_fraction_lasts_a_whole_second_and_zero_ends_it(
    clock: FakeClock,
) -> None:
    health = _health(clock)
    await health.set_cooldown(0.2)
    clock.advance(0.9)
    assert await health.is_in_cooldown()
    clock.advance(0.1)
    assert not await health.is_in_cooldown()

    await health.set_cooldown(30)
    await health.set_cooldown(0)
    assert not await health.is_in_cooldown()


async def test_the_rate_limit_window_moves_with_the_clock(clock: FakeClock) -> None:
    tracker = RateLimitTracker(
        model_id="m", rpm_limit=2, storage=backend("memory", clock=clock), clock=clock
    )
    await tracker.record_request(10)
    await tracker.record_request(10)
    assert not await tracker.can_accept_request()
    clock.advance(60)
    assert await tracker.can_accept_request()


async def test_the_recent_failures_window_moves_with_the_clock(clock: FakeClock) -> None:
    health = _health(clock)
    for _ in range(3):
        await health.record_failure("ServerError")
    assert await health.recent_failure_count("ServerError") == 3
    clock.advance(61)
    assert await health.recent_failure_count("ServerError") == 0


# --- the counters are read through count ------------------------------------------------------------------------


async def test_every_count_is_read_through_count_and_none_with_get(clock: FakeClock) -> None:
    store = StoreProxy(backend("memory", clock=clock))
    health = _health(clock, store)
    tracker = RateLimitTracker(model_id="m", rpm_limit=5, tpm_limit=500, storage=store, clock=clock)  # type: ignore[arg-type]

    await health.record_success(12.0)
    await health.record_failure("ServerError")
    await tracker.record_request(20)
    await tracker.increment_active_requests()
    await health.get_health_metrics()
    await health.get_success_rate()
    await tracker.can_accept_request(estimated_tokens=10)
    await tracker.get_current_usage()
    await health.recent_failure_count("ServerError")

    counted = (
        "health:m:success",
        "health:m:failure",
        "health:m:latency_us",
        "health:m:reason:",
        "rate_limit:",
        "active_requests:",
    )
    assert store.counted
    assert not [
        key for key in store.reads if key.startswith(counted) or key.startswith("recent_failures:")
    ]


# --- the router --------------------------------------------------------------------------------------------------


async def test_a_router_cools_a_target_down_and_brings_it_back_on_the_fake_clock(
    clock: FakeClock,
) -> None:
    flaky = FakeModel("flaky", errors=[RateLimitError("429")])
    router = ModelRouter(
        **timed(clock),
        retry_policies=[RetryPolicyConfig(error_type="RateLimitError", max_retries=0)],
        allowed_fails_policies=[
            AllowedFailsPolicyConfig(error_type="RateLimitError", allowed_fails_per_minute=1)
        ],
        cooldown_seconds=30.0,
    )
    router.register_model("flaky", flaky)

    with pytest.raises(ProviderError):
        await router.acomplete(messages=MESSAGES, model="flaky")
    assert (await router.aget_model_health("flaky")).is_in_cooldown

    clock.advance(29)
    assert (await router.aget_model_health("flaky")).is_in_cooldown
    clock.advance(1)
    assert not (await router.aget_model_health("flaky")).is_in_cooldown
