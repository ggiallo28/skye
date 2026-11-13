"""Shared fakes for the router unit tests: a controllable clock and a model that never touches the network."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest

from skye.base.completion import CompleteResponse, StreamChunk, TokenUsage
from skye.base.interfaces.model import ModelInterface
from skye.store import FakeClock, backend


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    """The ``FakeClock`` of ``skye.store``, started on a minute boundary so the minute window of a rate limit is predictable.

    The tests that are about time hand it to the router and to the store (``timed``). It also replaces ``time.time`` for the
    tests that build a router with no clock; ``test_router_clock.py`` leaves ``time.time`` alone and proves that the router
    reads only the clock it is given.
    """
    fake = FakeClock(start=60.0 * 100_000)
    monkeypatch.setattr(time, "time", fake)
    return fake


def timed(clock: FakeClock) -> dict[str, Any]:
    """The keyword arguments that drive a ``ModelRouter`` by a ``FakeClock``: the clock and a store on the same clock."""
    return {"clock": clock, "storage": backend("memory", clock=clock)}


class RateLimitError(Exception):
    """Named like the error type of the default allowed-fails policy (the router keys the policy on the class name)."""


class FakeModel(ModelInterface):
    """A model that answers, or raises the next queued error; it counts the calls on every entry point."""

    def __init__(
        self, name: str, *, tokens: int = 30, errors: list[BaseException] | None = None
    ) -> None:
        self.name = name
        self.tokens = tokens
        self.errors: list[BaseException] = list(errors or [])
        self.always_fail: BaseException | None = None
        self.calls = 0

    def _answer(self) -> CompleteResponse:
        self.calls += 1
        if self.always_fail is not None:
            raise self.always_fail
        if self.errors:
            raise self.errors.pop(0)
        return CompleteResponse(
            content=f"answer from {self.name}",
            role="assistant",
            model=self.name,
            provider="fake",
            finish_reason="stop",
            usage=TokenUsage(
                prompt_tokens=10, completion_tokens=self.tokens - 10, total_tokens=self.tokens
            ),
        )

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
