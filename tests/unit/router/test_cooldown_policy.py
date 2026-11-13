"""The cooldown and the allowed-fails policy of ``ModelRouter`` (task 5.2, Requirement 23.2).

A target that fails with an error type listed in the allowed-fails policy goes into cooldown once its failures of that type reach
the allowed count; while in cooldown it is not selected and not tried, and it comes back when the cooldown expires. Time is the fake
clock of ``fakes.clock``; no model touches the network.
"""

from __future__ import annotations

import pytest

from skye.base.completion import CompleteRequest
from skye.base.exceptions import ProviderError
from skye.base.messages import UserMessage
from skye.router import AllowedFailsPolicyConfig, FallbackConfig, ModelRouter, RetryPolicyConfig
from skye.store import FakeClock
from tests.unit.router.fakes import FakeModel, RateLimitError, timed

MESSAGES = [UserMessage(content="hi")]


class ServerError(Exception):
    """An error type the test lists in the policy."""


#: One call is one attempt: the retry policy (task 2.1) is tested on its own, so it is turned off for the error types used here.
NO_RETRIES = [
    RetryPolicyConfig(error_type=name, max_retries=0) for name in ("ServerError", "RateLimitError")
]


def _router(clock: FakeClock, models: dict[str, FakeModel], **kwargs: object) -> ModelRouter:
    kwargs.setdefault("retry_policies", NO_RETRIES)
    router = ModelRouter(**timed(clock), **kwargs)  # type: ignore[arg-type]
    for model_id, model in models.items():
        router.register_model(model_id, model)
    return router


async def _fail_once(router: ModelRouter, model_id: str) -> None:
    with pytest.raises(ProviderError):
        await router.acomplete(messages=MESSAGES, model=model_id)


async def test_a_target_goes_into_cooldown_when_its_failures_reach_the_allowed_count(
    clock: FakeClock,
) -> None:
    flaky = FakeModel("flaky")
    flaky.always_fail = ServerError("down")
    router = _router(
        clock,
        {"flaky": flaky},
        allowed_fails_policies=[
            AllowedFailsPolicyConfig(error_type="ServerError", allowed_fails_per_minute=3)
        ],
    )

    for _ in range(2):
        await _fail_once(router, "flaky")
        assert not (await router.aget_model_health("flaky")).is_in_cooldown

    await _fail_once(router, "flaky")
    health = await router.aget_model_health("flaky")
    assert health.is_in_cooldown
    assert health.cooldown_until == pytest.approx(clock() + router.cooldown_seconds)
    assert [info.model_id for info in await router.aget_cooldown_models()] == ["flaky"]


async def test_a_target_in_cooldown_is_not_called(clock: FakeClock) -> None:
    flaky = FakeModel("flaky")
    flaky.always_fail = ServerError("down")
    router = _router(
        clock,
        {"flaky": flaky},
        allowed_fails_policies=[
            AllowedFailsPolicyConfig(error_type="ServerError", allowed_fails_per_minute=1)
        ],
    )
    await _fail_once(router, "flaky")
    assert flaky.calls == 1

    flaky.always_fail = None
    await _fail_once(router, "flaky")
    assert flaky.calls == 1


async def test_a_target_comes_back_when_the_cooldown_expires(clock: FakeClock) -> None:
    flaky = FakeModel("flaky", errors=[ServerError("down")])
    router = _router(
        clock,
        {"flaky": flaky},
        cooldown_seconds=30.0,
        allowed_fails_policies=[
            AllowedFailsPolicyConfig(error_type="ServerError", allowed_fails_per_minute=1)
        ],
    )
    await _fail_once(router, "flaky")

    clock.advance(29)
    await _fail_once(router, "flaky")
    assert flaky.calls == 1

    clock.advance(1)
    response = await router.acomplete(messages=MESSAGES, model="flaky")
    assert response.content == "answer from flaky"
    assert not (await router.aget_model_health("flaky")).is_in_cooldown


async def test_an_error_type_outside_the_policy_never_causes_cooldown(clock: FakeClock) -> None:
    flaky = FakeModel("flaky")
    flaky.always_fail = ValueError("bad")
    router = _router(clock, {"flaky": flaky})
    for _ in range(20):
        await _fail_once(router, "flaky")
    health = await router.aget_model_health("flaky")
    assert health.failure_count == 20
    assert not health.is_in_cooldown


async def test_the_default_policy_cools_a_target_down_after_100_rate_limit_errors(
    clock: FakeClock,
) -> None:
    flaky = FakeModel("flaky")
    flaky.always_fail = RateLimitError("429")
    router = _router(clock, {"flaky": flaky})
    assert router.allowed_fails_policy["RateLimitError"] == 100

    for _ in range(99):
        await _fail_once(router, "flaky")
    assert not (await router.aget_model_health("flaky")).is_in_cooldown
    await _fail_once(router, "flaky")
    assert (await router.aget_model_health("flaky")).is_in_cooldown


async def test_set_allowed_fails_policy_and_set_cooldown_time_take_effect(clock: FakeClock) -> None:
    flaky = FakeModel("flaky")
    flaky.always_fail = ServerError("down")
    router = _router(clock, {"flaky": flaky})
    router.set_allowed_fails_policy(
        [AllowedFailsPolicyConfig(error_type="ServerError", allowed_fails_per_minute=1)]
    )
    router.set_cooldown_time(5.0)

    await _fail_once(router, "flaky")
    assert (await router.aget_model_health("flaky")).is_in_cooldown
    clock.advance(5)
    assert not (await router.aget_model_health("flaky")).is_in_cooldown


async def test_a_primary_in_cooldown_goes_straight_to_its_fallback(clock: FakeClock) -> None:
    primary = FakeModel("primary")
    primary.always_fail = ServerError("down")
    backup = FakeModel("backup")
    router = _router(
        clock,
        {"primary": primary, "backup": backup},
        fallbacks=[FallbackConfig(primary="primary", fallbacks=["backup"])],
        allowed_fails_policies=[
            AllowedFailsPolicyConfig(error_type="ServerError", allowed_fails_per_minute=1)
        ],
    )

    first = await router.acomplete(messages=MESSAGES, model="primary")
    assert first.content == "answer from backup"
    assert primary.calls == 1

    second = await router.acomplete(messages=MESSAGES, model="primary")
    assert second.content == "answer from backup"
    assert primary.calls == 1  # in cooldown: skipped, not tried


async def test_a_target_in_cooldown_is_not_selected_while_another_is_available(
    clock: FakeClock,
) -> None:
    flaky = FakeModel("flaky")
    flaky.always_fail = ServerError("down")
    steady = FakeModel("steady")
    router = _router(
        clock,
        {"flaky": flaky, "steady": steady},
        allowed_fails_policies=[
            AllowedFailsPolicyConfig(error_type="ServerError", allowed_fails_per_minute=1)
        ],
    )
    await _fail_once(router, "flaky")
    flaky.always_fail = None

    for _ in range(5):
        assert await router.select_model(CompleteRequest(messages=MESSAGES, model="")) == "steady"
    assert flaky.calls == 1


async def test_failures_older_than_a_minute_do_not_count_toward_the_allowed_fails(
    clock: FakeClock,
) -> None:
    flaky = FakeModel("flaky")
    flaky.always_fail = ServerError("down")
    router = _router(
        clock,
        {"flaky": flaky},
        allowed_fails_policies=[
            AllowedFailsPolicyConfig(error_type="ServerError", allowed_fails_per_minute=3)
        ],
    )
    for _ in range(2):
        await _fail_once(router, "flaky")
        clock.advance(120)  # one failure every two minutes: never 3 in one minute
    await _fail_once(router, "flaky")
    assert not (await router.aget_model_health("flaky")).is_in_cooldown
