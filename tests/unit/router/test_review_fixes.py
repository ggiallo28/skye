"""Fixes found by the documentation review of 2026-11-11 (router findings 1 to 8; decision D104).

Each test failed on the code before the fix. Fake models only: no network, no real sleep (the
router's ``sleep`` is
injected), time is the fake clock of ``fakes.clock`` where it matters.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import skye.router
from skye.base.completion import CompleteRequest
from skye.base.exceptions import (
    AuthenticationError,
    ConfigurationError,
    ContentPolicyError,
    ProviderError,
    ProviderTimeoutError,
    RateLimitError,
    ServerError,
)
from skye.base.interfaces.router import RoutingStrategy
from skye.base.messages import UserMessage
from skye.models.registry import ProviderRegistry
from tests.unit.plugins.registrar_state import restored_default_registrar
from skye.router import (
    AllowedFailsPolicyConfig,
    FallbackConfig,
    ModelRouter,
    ModelTarget,
    RetryPolicyConfig,
    RouteConfig,
)
from skye.router.health_tracker import ModelHealth
from skye.store.plugins.memory import InMemoryBackend
from skye.store import FakeClock
from tests.unit.router.fakes import FakeModel, timed

MESSAGES = [UserMessage(content="hi")]


class RecordingProvider(FakeModel):
    """A provider the registry builds from a target; it keeps its configuration, retries on."""

    built: list[RecordingProvider] = []

    def __init__(self, **config: Any) -> None:
        super().__init__(str(config.get("model", "?")))
        self.config = config
        self.max_retries = 3  # the client's own retries, which the router turns off (D104)
        RecordingProvider.built.append(self)


@pytest.fixture(autouse=True)
def recording_provider() -> Iterator[None]:
    with restored_default_registrar():
        RecordingProvider.built = []
        ProviderRegistry.register_model_provider("rec", RecordingProvider)
        yield


class Sleeps:
    """An injected ``sleep`` that records the waits instead of waiting."""

    def __init__(self) -> None:
        self.waits: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def _model(router: ModelRouter, alias: str, index: int = 0) -> RecordingProvider:
    target = router.aliases[alias].targets[index]
    return router.models[f"{alias}:{target.provider}:{target.model}"]  # type: ignore[return-value]


def _id(router: ModelRouter, alias: str, index: int = 0) -> str:
    target = router.aliases[alias].targets[index]
    return f"{alias}:{target.provider}:{target.model}"


# --- finding 1: the fallback chain when no target of the alias is available
# ----------------------------------------


async def test_an_alias_whose_targets_are_all_in_cooldown_uses_its_fallback_chain(
    clock: FakeClock,
) -> None:
    router = ModelRouter(
        **timed(clock),
        routes=[
            RouteConfig(alias="main", targets=[ModelTarget(model="a", provider="rec")]),
            RouteConfig(alias="backup", targets=[ModelTarget(model="b", provider="rec")]),
        ],
        fallbacks=[FallbackConfig(primary="main", fallbacks=["backup"])],
    )
    await router.health[_id(router, "main")].set_cooldown(60)

    response = await router.acomplete(messages=MESSAGES, model="main")

    assert response.content == "answer from b"
    assert response.metadata["router"]["fallback"] is True


async def test_an_alias_over_its_rpm_uses_its_fallback_chain(clock: FakeClock) -> None:
    router = ModelRouter(
        **timed(clock),
        routes=[
            RouteConfig(alias="main", targets=[ModelTarget(model="a", provider="rec", rpm=1)]),
            RouteConfig(alias="backup", targets=[ModelTarget(model="b", provider="rec")]),
        ],
        fallbacks=[FallbackConfig(primary="main", fallbacks=["backup"])],
    )
    assert (await router.acomplete(messages=MESSAGES, model="main")).content == "answer from a"
    assert (await router.acomplete(messages=MESSAGES, model="main")).content == "answer from b"


async def test_with_no_fallback_the_selection_error_is_still_raised(clock: FakeClock) -> None:
    router = ModelRouter(
        **timed(clock),
        routes=[RouteConfig(alias="main", targets=[ModelTarget(model="a", provider="rec")])],
    )
    await router.health[_id(router, "main")].set_cooldown(60)
    with pytest.raises(ProviderError, match="No available targets for alias 'main'"):
        await router.acomplete(messages=MESSAGES, model="main")


# --- finding 2: keyword arguments of from_file / from_config_dict
# --------------------------------------------------

CONFIG: dict[str, Any] = {
    "routes": [{"alias": "main", "targets": [{"model": "a", "provider": "rec"}]}]
}


def test_from_config_dict_passes_the_storage_through() -> None:
    store = InMemoryBackend()
    router = ModelRouter.from_config_dict(CONFIG, storage=store)
    assert router.storage_backend is store
    assert router.health[_id(router, "main")].storage.store is store  # the router state is the namespace ``router`` of it


def test_from_file_passes_the_storage_through(tmp_path: Path) -> None:
    path = tmp_path / "router.skye"
    path.write_text(
        'router { route "main" { target { model = "a", provider = "rec" } } }\n', encoding="utf-8"
    )
    store = InMemoryBackend()
    router = ModelRouter.from_file(path, storage=store)
    assert router.storage_backend is store


def test_an_unknown_keyword_is_rejected_with_the_accepted_names() -> None:
    with pytest.raises(ConfigurationError, match="storge") as caught:
        ModelRouter.from_config_dict(CONFIG, storge=InMemoryBackend())
    assert "storage" in str(caught.value)


def test_keyword_policies_are_added_after_the_file() -> None:
    router = ModelRouter.from_config_dict(
        {**CONFIG, "retry_policies": [{"error_type": "ServerError", "max_retries": 5}]},
        retry_policies=[RetryPolicyConfig(error_type="ServerError", max_retries=1)],
        strategy=RoutingStrategy.LEAST_BUSY,
    )
    assert router.retry_policy["ServerError"] == 1
    assert router.strategy is RoutingStrategy.LEAST_BUSY


# --- finding 3 and D104: the policies match the error classes of Skye
# ----------------------------------------------


@pytest.mark.parametrize(
    ("error", "calls"),
    [
        (RateLimitError("slow down", provider="p", status_code=429), 4),
        (ServerError("down", provider="p", status_code=503), 3),
        (ProviderTimeoutError("timed out", provider="p"), 3),
        (AuthenticationError("bad key", provider="p", status_code=401), 1),
        (ContentPolicyError("refused", provider="p", status_code=400), 1),
    ],
)
def test_the_default_retry_policy_matches_the_provider_errors(
    error: ProviderError, calls: int
) -> None:
    router = ModelRouter(sleep=Sleeps())
    model = FakeModel("m")
    model.always_fail = error
    router.register_model("m", model)
    with pytest.raises(ProviderError):
        router.complete(messages=MESSAGES, model="m")
    assert model.calls == calls


def test_the_default_policies_name_existing_error_classes() -> None:
    import skye.exceptions
    from skye.router.model_router import DEFAULT_ALLOWED_FAILS_POLICY, DEFAULT_RETRY_POLICY

    for name in [*DEFAULT_RETRY_POLICY, *DEFAULT_ALLOWED_FAILS_POLICY]:
        assert isinstance(getattr(skye.exceptions, name, None), type), name


async def test_the_allowed_fails_policy_matches_through_the_class_hierarchy(
    clock: FakeClock,
) -> None:
    router = ModelRouter(
        **timed(clock),
        retry_policies=[RetryPolicyConfig(error_type="ProviderError", max_retries=0)],
        allowed_fails_policies=[
            AllowedFailsPolicyConfig(error_type="ProviderError", allowed_fails_per_minute=2)
        ],
    )
    model = FakeModel("m")
    model.always_fail = ServerError("down", provider="p", status_code=500)
    router.register_model("m", model)
    for _ in range(2):
        with pytest.raises(ProviderError):
            await router.acomplete(messages=MESSAGES, model="m")
    assert (await router.aget_model_health("m")).is_in_cooldown


async def test_the_router_waits_the_retry_after_of_the_error() -> None:
    sleeps = Sleeps()
    router = ModelRouter(sleep=sleeps)
    model = FakeModel(
        "m", errors=[RateLimitError("slow down", provider="p", status_code=429, retry_after=2.5)]
    )
    router.register_model("m", model)
    assert (await router.acomplete(messages=MESSAGES, model="m")).content == "answer from m"
    assert sleeps.waits == [2.5]


async def test_a_retry_after_longer_than_the_cooldown_goes_to_the_fallback() -> None:
    sleeps = Sleeps()
    router = ModelRouter(sleep=sleeps, cooldown_seconds=60)
    slow = FakeModel(
        "slow", errors=[RateLimitError("later", provider="p", status_code=429, retry_after=3600)]
    )
    router.register_model("slow", slow)
    router.register_model("other", FakeModel("other"))
    router.set_fallbacks([FallbackConfig(primary="slow", fallbacks=["other"])])
    assert (await router.acomplete(messages=MESSAGES, model="slow")).content == "answer from other"
    assert sleeps.waits == []
    assert slow.calls == 1


def test_a_target_built_by_the_router_has_its_client_retries_off() -> None:
    router = ModelRouter(
        routes=[RouteConfig(alias="main", targets=[ModelTarget(model="a", provider="rec")])]
    )
    assert _model(router, "main").max_retries == 0


def test_a_registered_model_with_client_retries_has_them_turned_off() -> None:
    router = ModelRouter()
    model = RecordingProvider(model="m")
    router.register_model("m", model)
    assert model.max_retries == 0


# --- finding 4: the router's strategy applies to routes that set none
# ---------------------------------------------


async def test_the_router_strategy_applies_to_a_python_route_without_its_own() -> None:
    route = RouteConfig(
        alias="main",
        targets=[
            ModelTarget(model="dear", provider="rec", cost_per_1k_prompt_tokens=9.0),
            ModelTarget(model="cheap", provider="rec", cost_per_1k_prompt_tokens=1.0),
        ],
    )
    assert route.strategy is None
    router = ModelRouter(routes=[route], strategy=RoutingStrategy.COST_BASED)
    request = CompleteRequest(messages=MESSAGES, model="main")
    picked = {await router.select_model(request) for _ in range(4)}
    assert picked == {_id(router, "main", 1)}


def test_a_route_strategy_still_wins_over_the_router() -> None:
    route = RouteConfig(
        alias="main",
        targets=[ModelTarget(model="a", provider="rec")],
        strategy=RoutingStrategy.LEAST_BUSY,
    )
    router = ModelRouter(routes=[route], strategy=RoutingStrategy.COST_BASED)
    assert router.to_config()["routes"][0]["strategy"] == "least_busy"


# --- finding 5 and task 6.1: waits, per-target retries, fallback_on_error
# ------------------------------------------


async def test_retry_after_seconds_and_exponential_backoff_are_applied() -> None:
    sleeps = Sleeps()
    router = ModelRouter(
        sleep=sleeps,
        retry_policies=[
            RetryPolicyConfig(
                error_type="ServerError",
                max_retries=3,
                retry_after_seconds=1.0,
                exponential_backoff=True,
            )
        ],
    )
    model = FakeModel("m")
    model.always_fail = ServerError("down", provider="p", status_code=500)
    router.register_model("m", model)
    with pytest.raises(ProviderError):
        await router.acomplete(messages=MESSAGES, model="m")
    assert sleeps.waits == [1.0, 2.0, 4.0]


async def test_the_error_retry_after_wins_when_it_is_longer_than_the_policy_wait() -> None:
    sleeps = Sleeps()
    router = ModelRouter(
        sleep=sleeps,
        retry_policies=[
            RetryPolicyConfig(error_type="RateLimitError", max_retries=1, retry_after_seconds=1.0)
        ],
    )
    router.register_model(
        "m", FakeModel("m", errors=[RateLimitError("x", provider="p", retry_after=7.0)])
    )
    await router.acomplete(messages=MESSAGES, model="m")
    assert sleeps.waits == [7.0]


def test_the_wait_fields_are_exported_and_read_back(tmp_path: Path) -> None:
    router = ModelRouter(
        retry_policies=[
            RetryPolicyConfig(
                error_type="ServerError",
                max_retries=2,
                retry_after_seconds=5.0,
                exponential_backoff=True,
            )
        ]
    )
    [policy] = router.to_config()["retry_policies"]
    assert policy == {
        "error_type": "ServerError",
        "max_retries": 2,
        "retry_after_seconds": 5.0,
        "exponential_backoff": True,
    }
    text = router.to_skye()
    assert 'retry_after = "5s"' in text and "exponential_backoff = true" in text
    path = tmp_path / "r.skye"
    path.write_text(text, encoding="utf-8")
    again = ModelRouter.from_file(path)
    assert again.to_config()["retry_policies"] == [policy]


async def test_the_max_retries_of_a_target_overrides_the_policy_count() -> None:
    router = ModelRouter(
        sleep=Sleeps(),
        routes=[
            RouteConfig(
                alias="main", targets=[ModelTarget(model="a", provider="rec", max_retries=1)]
            )
        ],
    )
    model = _model(router, "main")
    model.always_fail = ServerError("down", provider="p", status_code=500)  # the policy says 2
    with pytest.raises(ProviderError):
        await router.acomplete(messages=MESSAGES, model="main")
    assert model.calls == 2


async def test_the_max_retries_of_a_target_does_not_retry_an_error_the_policy_does_not_retry() -> (
    None
):
    router = ModelRouter(
        sleep=Sleeps(),
        routes=[
            RouteConfig(
                alias="main", targets=[ModelTarget(model="a", provider="rec", max_retries=4)]
            )
        ],
    )
    model = _model(router, "main")
    model.always_fail = AuthenticationError("bad key", provider="p", status_code=401)
    with pytest.raises(ProviderError):
        await router.acomplete(messages=MESSAGES, model="main")
    assert model.calls == 1


async def test_fallback_on_error_tries_the_other_targets_of_the_route() -> None:
    router = ModelRouter(
        sleep=Sleeps(),
        routes=[
            RouteConfig(
                alias="main",
                targets=[
                    ModelTarget(model="a", provider="rec"),
                    ModelTarget(model="b", provider="rec"),
                ],
            )
        ],
    )
    _model(router, "main", 0).always_fail = AuthenticationError(
        "bad key", provider="p", status_code=401
    )
    response = await router.acomplete(messages=MESSAGES, model="main")
    assert response.content == "answer from b"
    assert response.metadata["router"]["tried"] == [_id(router, "main", 0)]


async def test_without_fallback_on_error_the_other_targets_are_not_tried() -> None:
    router = ModelRouter(
        sleep=Sleeps(),
        routes=[
            RouteConfig(
                alias="main",
                targets=[
                    ModelTarget(model="a", provider="rec"),
                    ModelTarget(model="b", provider="rec"),
                ],
                fallback_on_error=False,
            )
        ],
    )
    _model(router, "main", 0).always_fail = AuthenticationError(
        "bad key", provider="p", status_code=401
    )
    with pytest.raises(ProviderError):
        await router.acomplete(messages=MESSAGES, model="main")
    assert _model(router, "main", 1).calls == 0


# --- finding 6: provider options of a target
# -----------------------------------------------------------------------


def test_the_options_of_a_target_reach_the_provider_client() -> None:
    router = ModelRouter(
        routes=[
            RouteConfig(
                alias="gemini",
                targets=[
                    ModelTarget(
                        model="gemini-2.0-flash",
                        provider="rec",
                        options={"project_id": "my-project", "location": "europe-west1"},
                    )
                ],
            )
        ]
    )
    config = _model(router, "gemini").config
    assert config["project_id"] == "my-project"
    assert config["location"] == "europe-west1"
    assert config["model"] == "gemini-2.0-flash"


def test_the_options_of_a_target_are_exported_and_read_back() -> None:
    target = {"model": "a", "provider": "rec", "options": {"location": "eu"}}
    router = ModelRouter.from_config_dict({"routes": [{"alias": "main", "targets": [target]}]})
    assert router.aliases["main"].targets[0].options == {"location": "eu"}
    assert router.to_config()["routes"][0]["targets"][0]["options"] == {"location": "eu"}


# --- finding 7: atomic health counters, set_rate_limits on the router's store
# --------------------------------------


class InterleavingStore(InMemoryBackend):
    """An in-memory store that yields to the loop in ``get`` and ``set``, as a remote store does."""

    async def get(self, key: str) -> dict[str, Any] | None:
        await asyncio.sleep(0)
        return await super().get(key)

    async def set(self, key: str, data: dict[str, Any], ttl: int | None = None) -> None:
        await asyncio.sleep(0)
        await super().set(key, data, ttl)


async def test_concurrent_failures_and_successes_lose_no_count() -> None:
    health = ModelHealth(model_id="m", storage=InterleavingStore())
    await asyncio.gather(
        *(health.record_failure("ServerError") for _ in range(20)),
        *(health.record_success(10.0) for _ in range(10)),
    )
    metrics = await health.get_health_metrics()
    assert metrics["failure_count"] == 20
    assert metrics["success_count"] == 10
    assert metrics["failure_reasons"] == {"ServerError": 20}
    assert metrics["average_latency_ms"] == pytest.approx(10.0)
    assert await health.recent_failure_count("ServerError") == 20


def test_set_rate_limits_on_an_unknown_model_uses_the_router_store() -> None:
    store = InMemoryBackend()
    router = ModelRouter(storage=store)
    router.set_rate_limits("new", tpm=10, rpm=1)
    assert router.rate_limits["new"].storage.store is store
    assert router.rate_limits["new"].model_id == "new"


# --- finding 8 and task 4.4
# ----------------------------------------------------------------------------------------


def test_the_docstrings_are_current() -> None:
    assert "(default)" not in (RoutingStrategy.__doc__ or "")
    assert "health['success_rate']" not in (skye.router.__doc__ or "")


async def test_mark_model_failed_in_a_running_loop_takes_effect_at_once() -> None:
    router = ModelRouter()
    router.register_model("m", FakeModel("m"))
    router.mark_model_failed("m")
    assert (await router.aget_model_health("m")).is_in_cooldown
    await router.amark_model_failed("m")
    source = inspect.getsource(ModelRouter.mark_model_failed)
    assert "create_task" not in source and "asyncio.run" not in source


def test_mark_model_failed_outside_a_loop() -> None:
    router = ModelRouter()
    router.register_model("m", FakeModel("m"))
    router.mark_model_failed("m")
    assert router.get_model_health("m").is_in_cooldown
