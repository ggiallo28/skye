"""``ModelHealth`` and ``RateLimitTracker`` on their own, against the in-memory store (task 5.1, Requirements 23.1, 23.2).

Time never passes for real: the ``FakeClock`` of ``skye.store`` is given to the trackers and to the store (task 8.3).
"""

from __future__ import annotations

import math

import pytest

from skye.base.interfaces import StorageBackend
from skye.router.health_tracker import ModelHealth, RateLimitTracker
from skye.store import FakeClock, backend


@pytest.fixture
def storage(clock: FakeClock) -> StorageBackend:
    return backend("memory", clock=clock)


# --- ModelHealth: success rate and latency -------------------------------------------------------------------------


async def test_a_model_with_no_history_has_full_success_rate(
    storage: StorageBackend, clock: FakeClock
) -> None:
    health = ModelHealth(model_id="m", storage=storage, clock=clock)
    assert await health.get_success_rate() == 1.0
    metrics = await health.get_health_metrics()
    assert metrics["total_requests"] == 0
    assert metrics["success_rate"] == 1.0


async def test_success_rate_counts_successes_over_all_requests(
    storage: StorageBackend, clock: FakeClock
) -> None:
    health = ModelHealth(model_id="m", storage=storage, clock=clock)
    for latency in (100.0, 200.0, 300.0):
        await health.record_success(latency)
    await health.record_failure("TimeoutError")

    assert await health.get_success_rate() == pytest.approx(0.75)
    metrics = await health.get_health_metrics()
    assert metrics["success_count"] == 3
    assert metrics["failure_count"] == 1
    assert metrics["total_requests"] == 4
    assert metrics["success_rate"] == pytest.approx(0.75)


async def test_latency_keeps_average_minimum_and_maximum(
    storage: StorageBackend, clock: FakeClock
) -> None:
    health = ModelHealth(model_id="m", storage=storage, clock=clock)
    for latency in (120.0, 40.0, 200.0):
        await health.record_success(latency)

    assert await health.get_avg_latency_ms() == pytest.approx(120.0)
    metrics = await health.get_health_metrics()
    assert metrics["average_latency_ms"] == pytest.approx(120.0)
    assert metrics["min_latency_ms"] == 40.0
    assert metrics["max_latency_ms"] == 200.0


async def test_a_model_with_no_success_has_infinite_average_latency(
    storage: StorageBackend, clock: FakeClock
) -> None:
    health = ModelHealth(model_id="m", storage=storage, clock=clock)
    await health.record_failure("TimeoutError")
    # Infinite so that a latency-based strategy never prefers a model that never answered.
    assert math.isinf(await health.get_avg_latency_ms())


async def test_failures_are_counted_per_reason_with_timestamps(
    storage: StorageBackend, clock: FakeClock
) -> None:
    health = ModelHealth(model_id="m", storage=storage, clock=clock)
    await health.record_failure("TimeoutError")
    clock.advance(5)
    await health.record_failure("TimeoutError")
    await health.record_failure("RateLimitError")
    clock.advance(5)
    await health.record_success(50.0)

    metrics = await health.get_health_metrics()
    assert metrics["failure_reasons"] == {"TimeoutError": 2, "RateLimitError": 1}
    assert metrics["last_failure_time"] == clock() - 5
    assert metrics["last_success_time"] == clock()


async def test_health_data_expires_after_a_day(storage: StorageBackend, clock: FakeClock) -> None:
    health = ModelHealth(model_id="m", storage=storage, clock=clock)
    await health.record_failure("TimeoutError")
    assert await health.get_success_rate() == 0.0
    clock.advance(86_400 + 1)
    assert await health.get_success_rate() == 1.0


async def test_two_models_on_one_storage_keep_separate_health(
    storage: StorageBackend, clock: FakeClock
) -> None:
    a = ModelHealth(model_id="a", storage=storage, clock=clock)
    b = ModelHealth(model_id="b", storage=storage, clock=clock)
    await a.record_failure("TimeoutError")
    await b.record_success(10.0)
    await a.set_cooldown(30)

    assert await a.get_success_rate() == 0.0
    assert await b.get_success_rate() == 1.0
    assert await a.is_in_cooldown()
    assert not await b.is_in_cooldown()


# --- ModelHealth: cooldown -----------------------------------------------------------------------------------------


async def test_a_new_model_is_not_in_cooldown(storage: StorageBackend, clock: FakeClock) -> None:
    health = ModelHealth(model_id="m", storage=storage, clock=clock)
    assert not await health.is_in_cooldown()
    assert (await health.get_health_metrics())["is_in_cooldown"] is False


async def test_cooldown_lasts_its_duration_and_then_expires(
    storage: StorageBackend, clock: FakeClock
) -> None:
    health = ModelHealth(model_id="m", storage=storage, clock=clock)
    await health.set_cooldown(30)
    started = clock()

    assert await health.is_in_cooldown()
    metrics = await health.get_health_metrics()
    assert metrics["is_in_cooldown"] is True
    assert metrics["cooldown_until"] == started + 30

    clock.advance(29.9)
    assert await health.is_in_cooldown()

    clock.advance(0.1)
    assert not await health.is_in_cooldown()
    assert (await health.get_health_metrics())["is_in_cooldown"] is False


async def test_a_new_cooldown_replaces_the_previous_one(
    storage: StorageBackend, clock: FakeClock
) -> None:
    health = ModelHealth(model_id="m", storage=storage, clock=clock)
    await health.set_cooldown(10)
    clock.advance(5)
    await health.set_cooldown(60)
    clock.advance(30)
    assert await health.is_in_cooldown()
    clock.advance(30)
    assert not await health.is_in_cooldown()


# --- RateLimitTracker: minute window -------------------------------------------------------------------------------


async def test_requests_and_tokens_are_counted_in_the_current_minute(
    storage: StorageBackend, clock: FakeClock
) -> None:
    tracker = RateLimitTracker(
        model_id="m", rpm_limit=10, tpm_limit=1000, storage=storage, clock=clock
    )
    await tracker.record_request(100)
    await tracker.record_request(250)

    usage = await tracker.get_current_usage()
    assert usage["rpm_used"] == 2
    assert usage["tpm_used"] == 350
    assert usage["rpm_limit"] == 10
    assert usage["tpm_limit"] == 1000


async def test_a_request_with_no_tokens_counts_only_as_a_request(
    storage: StorageBackend, clock: FakeClock
) -> None:
    tracker = RateLimitTracker(model_id="m", storage=storage, clock=clock)
    await tracker.record_request(0)
    usage = await tracker.get_current_usage()
    assert usage["rpm_used"] == 1
    assert usage["tpm_used"] == 0


async def test_the_counts_reset_when_the_minute_changes(
    storage: StorageBackend, clock: FakeClock
) -> None:
    tracker = RateLimitTracker(model_id="m", rpm_limit=10, storage=storage, clock=clock)
    await tracker.record_request(100)

    clock.advance(59)
    assert (await tracker.get_current_usage())["rpm_used"] == 1

    clock.advance(1)
    usage = await tracker.get_current_usage()
    assert usage["rpm_used"] == 0
    assert usage["tpm_used"] == 0


async def test_the_rpm_limit_refuses_requests_until_the_next_minute(
    storage: StorageBackend, clock: FakeClock
) -> None:
    tracker = RateLimitTracker(model_id="m", rpm_limit=3, storage=storage, clock=clock)
    for _ in range(2):
        await tracker.record_request(10)
    assert await tracker.can_accept_request()

    await tracker.record_request(10)
    assert not await tracker.can_accept_request()

    clock.advance(60)
    assert await tracker.can_accept_request()


async def test_the_tpm_limit_refuses_a_request_that_would_exceed_it(
    storage: StorageBackend, clock: FakeClock
) -> None:
    tracker = RateLimitTracker(model_id="m", tpm_limit=1000, storage=storage, clock=clock)
    await tracker.record_request(800)

    assert await tracker.can_accept_request(estimated_tokens=200)
    assert not await tracker.can_accept_request(estimated_tokens=201)
    # With no estimate the token limit is not checked.
    assert await tracker.can_accept_request()

    clock.advance(60)
    assert await tracker.can_accept_request(estimated_tokens=1000)


async def test_no_limits_always_accept(storage: StorageBackend, clock: FakeClock) -> None:
    tracker = RateLimitTracker(model_id="m", storage=storage, clock=clock)
    for _ in range(50):
        await tracker.record_request(10_000)
    assert await tracker.can_accept_request(estimated_tokens=10**9)


async def test_two_models_on_one_storage_keep_separate_windows(
    storage: StorageBackend, clock: FakeClock
) -> None:
    a = RateLimitTracker(model_id="a", rpm_limit=1, storage=storage, clock=clock)
    b = RateLimitTracker(model_id="b", rpm_limit=1, storage=storage, clock=clock)
    await a.record_request(10)
    assert not await a.can_accept_request()
    assert await b.can_accept_request()


# --- RateLimitTracker: active requests -----------------------------------------------------------------------------


async def test_active_requests_go_up_and_down(storage: StorageBackend, clock: FakeClock) -> None:
    tracker = RateLimitTracker(model_id="m", storage=storage, clock=clock)
    assert (await tracker.get_current_usage())["active_requests"] == 0

    assert await tracker.increment_active_requests() == 1
    assert await tracker.increment_active_requests() == 2
    assert (await tracker.get_current_usage())["active_requests"] == 2

    assert await tracker.decrement_active_requests() == 1
    assert await tracker.decrement_active_requests() == 0
    assert (await tracker.get_current_usage())["active_requests"] == 0


async def test_active_requests_do_not_reset_with_the_minute(
    storage: StorageBackend, clock: FakeClock
) -> None:
    tracker = RateLimitTracker(model_id="m", storage=storage, clock=clock)
    await tracker.increment_active_requests()
    clock.advance(120)
    assert (await tracker.get_current_usage())["active_requests"] == 1
