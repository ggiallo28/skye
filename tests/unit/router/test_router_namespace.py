"""The router keeps its state in the namespace ``router`` of its store (task 8.4, Requirement 60.10)."""

from __future__ import annotations

from typing import Any

import pytest

from skye.router import ModelRouter
from skye.router.config_models import AllowedFailsPolicyConfig, RetryPolicyConfig
from skye.store import FakeClock, backend, namespaced
from tests.unit.router.fakes import FakeModel, RateLimitError, timed

MESSAGES: list[Any] = []


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(start=60.0 * 100_000)


def _router(clock: FakeClock, store: Any = None, **options: Any) -> ModelRouter:
    keywords = timed(clock)
    if store is not None:
        keywords["storage"] = store
    router = ModelRouter(
        **keywords,
        retry_policies=[RetryPolicyConfig(error_type="RateLimitError", max_retries=0)],
        allowed_fails_policies=[
            AllowedFailsPolicyConfig(error_type="RateLimitError", allowed_fails_per_minute=1)
        ],
        cooldown_seconds=30.0,
        **options,
    )
    return router


async def test_every_key_of_the_router_is_in_its_namespace(clock: FakeClock) -> None:
    store = backend("memory", clock=clock)
    router = _router(clock, store)
    router.register_model("m", FakeModel("m"))
    router.set_rate_limits("m", tpm=1000, rpm=10)
    await router.acomplete(messages=MESSAGES, model="m")

    keys = await store.keys()
    assert keys
    assert all(key.startswith("router:") for key in keys)
    assert any(key.startswith("router:health:m:") for key in keys)
    assert any(key.startswith("router:rate_limit:m:") for key in keys)
    assert router.storage_backend is store


async def test_a_cooldown_is_a_key_of_the_namespace_with_a_ttl(clock: FakeClock) -> None:
    store = backend("memory", clock=clock)
    router = _router(clock, store)
    router.register_model("flaky", FakeModel("flaky", errors=[RateLimitError("429")]))
    with pytest.raises(Exception):
        await router.acomplete(messages=MESSAGES, model="flaky")
    assert await store.is_alive("router:cooldown:flaky")
    clock.advance(31)
    assert not await store.is_alive("router:cooldown:flaky")


async def test_another_component_in_the_same_store_does_not_meet_the_router(
    clock: FakeClock,
) -> None:
    store = backend("memory", clock=clock)
    memory = namespaced(store, "memory")
    await memory.set("health:m", {"mine": True})
    await memory.increment("health:m:success", 99)

    router = _router(clock, store)
    router.register_model("m", FakeModel("m"))
    await router.acomplete(messages=MESSAGES, model="m")

    assert await memory.get("health:m") == {"mine": True}
    assert await memory.count("health:m:success") == 99
    assert not [key for key in await memory.keys() if key not in ("health:m", "health:m:success")]
    assert (await router.aget_model_health("m")).success_count == 1


async def test_two_routers_over_one_store_share_the_state_of_the_router(clock: FakeClock) -> None:
    """The point of a shared store: one process cools a target down and another process sees it."""
    store = backend("memory", clock=clock)
    first, second = _router(clock, store), _router(clock, store)
    first.register_model("flaky", FakeModel("flaky", errors=[RateLimitError("429")]))
    second.register_model("flaky", FakeModel("flaky"))

    with pytest.raises(Exception):
        await first.acomplete(messages=MESSAGES, model="flaky")
    assert (await second.aget_model_health("flaky")).is_in_cooldown


async def test_routers_over_different_stores_do_not_meet(clock: FakeClock) -> None:
    first, second = _router(clock), _router(clock)
    first.register_model("flaky", FakeModel("flaky", errors=[RateLimitError("429")]))
    second.register_model("flaky", FakeModel("flaky"))
    with pytest.raises(Exception):
        await first.acomplete(messages=MESSAGES, model="flaky")
    assert not (await second.aget_model_health("flaky")).is_in_cooldown
