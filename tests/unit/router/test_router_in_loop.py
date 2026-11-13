"""A router built inside a running event loop (task 5.2, Requirement 23.2; Serverless rules of ``00-rules``).

These tests assert behaviour only (the router builds and routes inside a running loop, and its storage is connected before it is
used), not how the connection is made, so that they hold before and after the storage connection becomes lazy (task 4.2).
The repository runs async tests with pytest-asyncio in ``auto`` mode.
"""

from __future__ import annotations

import asyncio
from typing import Any

from skye.base.messages import UserMessage
from skye.router import ModelRouter, ModelTarget, RouteConfig
from skye.store.plugins.memory import InMemoryBackend
from tests.unit.router.fakes import FakeModel

MESSAGES = [UserMessage(content="hi")]


class StrictBackend(InMemoryBackend):
    """An in-memory backend that records whether it was connected before each use."""

    def __init__(self) -> None:
        super().__init__()
        self.connected = False
        self.connect_calls = 0
        self.used_before_connect: list[str] = []

    async def connect(self) -> None:
        self.connect_calls += 1
        self.connected = True

    def _check(self, op: str) -> None:
        if not self.connected:
            self.used_before_connect.append(op)

    async def get(self, key: str) -> dict[str, Any] | None:
        self._check("get")
        return await super().get(key)

    async def set(self, key: str, data: dict[str, Any], ttl: int | None = None) -> None:
        self._check("set")
        await super().set(key, data, ttl)

    async def increment(self, key: str, amount: int = 1, ttl: int | None = None) -> int:
        self._check("increment")
        return await super().increment(key, amount, ttl)


async def test_a_router_built_in_a_running_loop_routes_a_call() -> None:
    asyncio.get_running_loop()  # this test really runs inside a loop
    router = ModelRouter()
    model = FakeModel("m")
    router.register_model("m", model)

    response = await router.acomplete(messages=MESSAGES, model="m")
    assert response.content == "answer from m"
    assert model.calls == 1
    health = await router.aget_model_health("m")
    assert health.success_count == 1


async def test_a_router_with_routes_built_in_a_running_loop_resolves_its_alias() -> None:
    router = ModelRouter(
        routes=[
            RouteConfig(
                alias="chat", targets=[ModelTarget(model="small", provider="openai", api_key="k")]
            )
        ]
    )
    router.models["chat:openai:small"] = FakeModel("small")
    response = await router.acomplete(messages=MESSAGES, model="chat")
    assert response.content == "answer from small"


async def test_the_sync_form_also_works_when_called_from_a_running_loop() -> None:
    router = ModelRouter()
    router.register_model("m", FakeModel("m"))
    assert router.complete(messages=MESSAGES, model="m").content == "answer from m"
    assert router.get_model_health("m").success_count == 1


async def test_several_routers_built_in_one_loop_do_not_interfere() -> None:
    routers = []
    for name in ("a", "b", "c"):
        router = ModelRouter()
        router.register_model(name, FakeModel(name))
        routers.append((name, router))
    results = await asyncio.gather(*(r.acomplete(messages=MESSAGES, model=n) for n, r in routers))
    assert [r.content for r in results] == ["answer from a", "answer from b", "answer from c"]


def test_a_router_built_with_no_loop_connects_its_storage_before_use() -> None:
    backend = StrictBackend()
    router = ModelRouter(storage=backend)
    router.register_model("m", FakeModel("m"))
    router.complete(messages=MESSAGES, model="m")
    assert backend.connect_calls == 1
    assert backend.used_before_connect == []


async def test_a_router_built_in_a_running_loop_connects_its_storage_before_use() -> None:
    backend = StrictBackend()
    router = ModelRouter(storage=backend)
    router.register_model("m", FakeModel("m"))

    await router.acomplete(messages=MESSAGES, model="m")
    assert backend.connect_calls == 1
    assert backend.used_before_connect == []
