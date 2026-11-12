"""The routing loop of ``ModelRouter`` (router tasks 2.2, 2.3, 4.1, 4.2, 4.3).

The retry policy, the error chained into the final ``ProviderError``, the call that does not block
the event loop, the storage connection made at first use and the structured log fields.

Fake models only: no network, no real sleep (retries are immediate).
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest

from skye.base.completion import CompleteResponse, StreamChunk, TokenUsage
from skye.base.exceptions import ProviderError
from skye.base.interfaces.model import ModelInterface
from skye.base.messages import UserMessage
from skye.router import FallbackConfig, ModelRouter, RetryPolicyConfig
from skye.store.plugins.memory import InMemoryBackend

MESSAGES = [UserMessage(content="hi")]


class RateLimitError(Exception):
    """Named like an error type of the default retry policy (3 retries)."""


class ProviderRateLimitError(RateLimitError):
    """A provider's subclass with no policy of its own: the ``RateLimitError`` one applies (MRO)."""


class AuthenticationError(Exception):
    """Named like the default policy entry with 0 retries."""


class UnknownError(Exception):
    """No policy names it: no retry."""


def _response(name: str) -> CompleteResponse:
    return CompleteResponse(
        content=f"answer from {name}",
        role="assistant",
        model=name,
        provider="fake",
        finish_reason="stop",
        usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )


class ScriptedModel(ModelInterface):
    """Raises the queued errors in order, then answers; counts the calls and their threads."""

    def __init__(
        self,
        name: str,
        errors: list[BaseException] | None = None,
        *,
        fail_always: BaseException | None = None,
    ) -> None:
        self.name = name
        self.errors = list(errors or [])
        self.fail_always = fail_always
        self.calls = 0
        self.threads: list[int] = []

    def _answer(self) -> CompleteResponse:
        self.calls += 1
        self.threads.append(threading.get_ident())
        if self.fail_always is not None:
            raise self.fail_always
        if self.errors:
            raise self.errors.pop(0)
        return _response(self.name)

    def complete(self, *args: Any, **kwargs: Any) -> CompleteResponse:
        return self._answer()

    async def acomplete(self, *args: Any, **kwargs: Any) -> CompleteResponse:
        return self._answer()

    def stream(self, *args: Any, **kwargs: Any) -> Iterator[StreamChunk]:
        yield StreamChunk(delta=self._answer().content, model=self.name)

    async def astream(self, *args: Any, **kwargs: Any) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(delta=self._answer().content, model=self.name)

    def get_model_info(self) -> dict[str, Any]:
        return {"name": self.name, "provider": "fake"}


class SyncOnlyModel(ScriptedModel):
    """A model with no coroutine ``acomplete``: the router calls ``complete`` in a worker thread."""

    acomplete = None  # type: ignore[assignment]


def _router(**kwargs: Any) -> ModelRouter:
    # No cooldown policy for the error types used here, so retries are not cut short by a cooldown.
    return ModelRouter(allowed_fails_policies=None, **kwargs)


# --- retry policy (2.2) --------------------------------------------------------------------------


def test_a_matching_error_retries_the_same_target_before_the_fallback() -> None:
    router = _router(retry_policies=[RetryPolicyConfig(error_type="UnknownError", max_retries=2)])
    primary = ScriptedModel("primary", [UnknownError("a"), UnknownError("b")])
    backup = ScriptedModel("backup")
    router.register_model("primary", primary)
    router.register_model("backup", backup)
    router.set_fallbacks([FallbackConfig(primary="primary", fallbacks=["backup"])])

    response = router.complete(messages=MESSAGES, model="primary")

    assert response.content == "answer from primary"
    assert primary.calls == 3
    assert backup.calls == 0


def test_retries_are_bounded_by_max_retries_then_the_fallback_chain_is_walked() -> None:
    router = _router(retry_policies=[RetryPolicyConfig(error_type="UnknownError", max_retries=2)])
    primary = ScriptedModel("primary", fail_always=UnknownError("down"))
    backup = ScriptedModel("backup")
    router.register_model("primary", primary)
    router.register_model("backup", backup)
    router.set_fallbacks([FallbackConfig(primary="primary", fallbacks=["backup"])])

    response = router.complete(messages=MESSAGES, model="primary")

    assert response.content == "answer from backup"
    assert primary.calls == 3  # the first call and two retries
    assert backup.calls == 1


def test_an_error_with_no_policy_is_not_retried() -> None:
    router = _router()
    primary = ScriptedModel("primary", fail_always=UnknownError("down"))
    backup = ScriptedModel("backup")
    router.register_model("primary", primary)
    router.register_model("backup", backup)
    router.set_fallbacks([FallbackConfig(primary="primary", fallbacks=["backup"])])

    router.complete(messages=MESSAGES, model="primary")

    assert primary.calls == 1


def test_a_policy_of_zero_retries_is_not_retried() -> None:
    router = _router()  # the default policy has AuthenticationError: 0
    primary = ScriptedModel("primary", fail_always=AuthenticationError("bad key"))
    router.register_model("primary", primary)

    with pytest.raises(ProviderError):
        router.complete(messages=MESSAGES, model="primary")

    assert primary.calls == 1


def test_the_error_type_matches_a_policy_through_the_mro() -> None:
    router = ModelRouter(allowed_fails_policies=None)
    router.allowed_fails_policy.clear()  # keep the default RateLimitError cooldown out of the way
    primary = ScriptedModel("primary", [ProviderRateLimitError("slow down")] * 3)
    router.register_model("primary", primary)

    response = router.complete(messages=MESSAGES, model="primary")

    assert response.content == "answer from primary"
    assert primary.calls == 4  # the default RateLimitError policy: 3 retries


def test_the_most_specific_class_in_the_mro_wins() -> None:
    router = _router(
        retry_policies=[RetryPolicyConfig(error_type="ProviderRateLimitError", max_retries=1)]
    )
    router.allowed_fails_policy.clear()
    primary = ScriptedModel("primary", fail_always=ProviderRateLimitError("slow down"))
    router.register_model("primary", primary)

    with pytest.raises(ProviderError):
        router.complete(messages=MESSAGES, model="primary")

    assert primary.calls == 2  # its own policy (1 retry), not the RateLimitError one (3)


def test_a_target_put_in_cooldown_is_not_retried() -> None:
    router = _router(retry_policies=[RetryPolicyConfig(error_type="UnknownError", max_retries=5)])
    router.allowed_fails_policy["UnknownError"] = 1  # the first failure puts the target in cooldown
    primary = ScriptedModel("primary", fail_always=UnknownError("down"))
    router.register_model("primary", primary)

    with pytest.raises(ProviderError):
        router.complete(messages=MESSAGES, model="primary")

    assert primary.calls == 1


def test_every_attempt_is_recorded_in_the_health_of_the_target() -> None:
    router = _router(retry_policies=[RetryPolicyConfig(error_type="UnknownError", max_retries=2)])
    primary = ScriptedModel("primary", [UnknownError("a"), UnknownError("b")])
    router.register_model("primary", primary)

    router.complete(messages=MESSAGES, model="primary")

    health = router.get_model_health("primary")
    assert (health.failure_count, health.success_count) == (2, 1)
    assert health.failure_reasons == {"UnknownError": 2}
    assert router.get_usage_stats("primary").active_requests == 0


# --- the last error is chained (2.3) -------------------------------------------------------------


def test_the_final_provider_error_chains_the_last_error() -> None:
    router = _router()
    first_error = UnknownError("primary down")
    last_error = UnknownError("backup down")
    router.register_model("primary", ScriptedModel("primary", fail_always=first_error))
    router.register_model("backup", ScriptedModel("backup", fail_always=last_error))
    router.set_fallbacks([FallbackConfig(primary="primary", fallbacks=["backup"])])

    with pytest.raises(ProviderError) as caught:
        router.complete(messages=MESSAGES, model="primary")

    assert caught.value.__cause__ is last_error
    assert caught.value.details["tried"] == ["primary", "backup"]
    assert caught.value.details["last_error_type"] == "UnknownError"


# --- the model call does not block the loop (4.1) ------------------------------------------------


async def test_acomplete_of_the_model_is_awaited_on_the_loop() -> None:
    router = _router()
    model = ScriptedModel("primary")
    router.register_model("primary", model)

    await router.acomplete(messages=MESSAGES, model="primary")

    assert model.threads == [threading.get_ident()]


async def test_a_model_without_acomplete_runs_in_a_worker_thread() -> None:
    router = _router()
    model = SyncOnlyModel("primary")
    router.register_model("primary", model)

    response = await router.acomplete(messages=MESSAGES, model="primary")

    assert response.content == "answer from primary"
    assert model.threads and model.threads[0] != threading.get_ident()


# --- the storage connection is lazy (4.2) --------------------------------------------------------


class CountingBackend(InMemoryBackend):
    """Counts the calls to ``connect``."""

    def __init__(self) -> None:
        super().__init__()
        self.connects = 0

    async def connect(self) -> None:
        self.connects += 1
        await super().connect()


async def test_a_router_built_inside_a_running_loop_starts_no_task() -> None:
    before = asyncio.all_tasks()
    storage = CountingBackend()
    router = ModelRouter(storage=storage)

    assert asyncio.all_tasks() == before
    assert storage.connects == 0

    router.register_model("primary", ScriptedModel("primary"))
    await asyncio.gather(*(router.acomplete(messages=MESSAGES, model="primary") for _ in range(5)))
    assert storage.connects == 1


def test_a_router_built_outside_a_loop_connects_at_the_first_call() -> None:
    storage = CountingBackend()
    router = ModelRouter(storage=storage)
    assert storage.connects == 0

    router.register_model("primary", ScriptedModel("primary"))
    router.complete(messages=MESSAGES, model="primary")
    router.complete(messages=MESSAGES, model="primary")
    assert storage.connects == 1


# --- structured logging (4.3) --------------------------------------------------------------------


def test_failures_are_logged_with_structured_fields_and_no_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    router = _router()
    router.register_model("primary", ScriptedModel("primary", fail_always=UnknownError("down")))
    router.register_model("backup", ScriptedModel("backup"))
    router.set_fallbacks([FallbackConfig(primary="primary", fallbacks=["backup"])])

    with caplog.at_level(logging.DEBUG, logger="skye.router.model_router"):
        router.complete(messages=MESSAGES, model="primary")

    failed = [record for record in caplog.records if record.getMessage() == "Router target failed"]
    assert failed and failed[0].model_id == "primary" and failed[0].error_type == "UnknownError"  # type: ignore[attr-defined]
    for record in caplog.records:
        assert "api_key" not in record.getMessage()
