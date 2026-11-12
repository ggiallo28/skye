"""A third party adds a routing strategy, an MCP client and a decision provider, and the product paths find them (task 9.4).

Requirements 58.1, 58.2 and 58.3 of steering. Each kind is added with the ``skye.Plugins()`` handle, by a decorator or by a direct call, and then
used where a built-in is used: the router, a route, ``from_config_dict`` and a ``.skye`` router block for a strategy; ``skye.mcp_client`` and
``create_mcp_client`` for an MCP client; ``skye.provider(..., provider_type="decision")`` and ``create_decision_model`` for a decision provider.
Each test puts the default registrar back as it was. Fake models only, no network.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

import pytest

import skye
from skye.base.completion import CompleteRequest
from skye.base.dsl import build
from skye.base.interfaces.decision import DecisionModel, DecisionResult
from skye.base.messages import UserMessage
from skye.models import create_decision_model
from skye.router import ModelRouter, ModelTarget, RouteConfig, StrategyContext, with_context
from skye.tools import capability, create_mcp_client
from tests.unit.plugins.registrar_state import restored_default_registrar
from tests.unit.router.test_serving_record import FakeModel


@pytest.fixture
def plugins():
    """The default handle, with the default registrar put back as it was after the test."""
    with restored_default_registrar():
        yield skye.Plugins()


# -- a routing strategy (58.1) -----------------------------------------------------------------------------------------------------

TARGETS = [
    ModelTarget(model="gpt-4o-mini", provider="openai", api_key="k"),
    ModelTarget(model="o3", provider="openai", api_key="k"),
]

SKYE_ROUTER = """router "r" {
  strategy = "NAME"
  route "main" {
    strategy = "NAME"
    target {
      model = "gpt-4o"
      provider = "openai"
    }
  }
}
"""


def _router(strategy: str) -> ModelRouter:
    router = ModelRouter(
        routes=[RouteConfig(alias="chat", targets=list(TARGETS))], strategy=strategy
    )
    router.models.update({model_id: FakeModel(model_id) for model_id in router.models})
    return router


def _is_valid_everywhere(name: str) -> None:
    """The name of a registered strategy is valid in the router, in a route, in ``from_config_dict`` and in a ``.skye`` router block."""
    assert ModelRouter(strategy=name).strategy == name
    assert RouteConfig(alias="r", targets=list(TARGETS), strategy=name).strategy == name
    built = ModelRouter.from_config_dict(
        {
            "strategy": name,
            "routes": [
                {
                    "alias": "chat",
                    "strategy": name,
                    "targets": [{"model": "o3", "provider": "openai", "api_key": "k"}],
                }
            ],
        }
    )
    assert built.strategy == name and built.aliases["chat"].strategy == name
    document = build(SKYE_ROUTER.replace("NAME", name))
    assert document.diagnostics == []
    router = document.routers[0]
    assert router.strategy == name and router.routes[0].strategy == name


def test_a_plain_function_strategy_is_valid_everywhere_and_runs(plugins):
    picked: list[str] = []

    @plugins.routing_strategy("tp-last-model")
    def last_model(models: list[str]) -> str:
        picked.append(models[-1])
        return models[-1]

    assert (
        skye.routing_strategy("tp-last-model") is last_model
    )  # the decorator returned the function
    assert "tp-last-model" in plugins.names("routing_strategy")
    _is_valid_everywhere("tp-last-model")
    reply = _router("tp-last-model").complete(messages=[UserMessage(content="hi")], model="chat")
    assert picked and reply.content.endswith(picked[-1])


def test_a_context_strategy_is_valid_everywhere_and_reads_the_request(plugins):
    seen: list[StrategyContext] = []

    @plugins.routing_strategy("tp-by-tools")
    @with_context
    def by_tools(context: StrategyContext) -> str:
        seen.append(context)
        has_tools = context.request is not None and bool(context.request.capabilities)
        return context.models[-1] if has_tools else context.models[0]

    @capability
    def lookup(order_id: str) -> str:
        """Look up an order."""
        return order_id

    _is_valid_everywhere("tp-by-tools")
    seen.clear()
    router = _router("tp-by-tools")
    plain = CompleteRequest(model="chat", messages=[UserMessage(content="hi")])
    with_tool = CompleteRequest(
        model="chat", messages=[UserMessage(content="hi")], capabilities=[lookup]
    )
    cheap = asyncio.run(router.select_model(plain))
    strong = asyncio.run(router.select_model(with_tool))
    assert [context.request for context in seen] == [plain, with_tool]
    assert cheap == seen[0].models[0] and strong == seen[1].models[-1]
    assert cheap != strong


def test_a_direct_call_registers_a_strategy_as_well(plugins):
    plugins.routing_strategy("tp-first-model", lambda models: models[0])
    _is_valid_everywhere("tp-first-model")
    reply = _router("tp-first-model").complete(messages=[UserMessage(content="hi")], model="chat")
    assert reply.content


# -- an MCP client (58.2) ----------------------------------------------------------------------------------------------------------


class FakeMCP:
    """What a third party writes: the target and the options in the constructor, and the tools in ``list_tools``."""

    def __init__(
        self, target: Any, *, headers: dict[str, str] | None = None, timeout: float = 30.0
    ) -> None:
        self.target, self.headers, self.timeout = target, headers, timeout

    async def list_tools(self) -> list[str]:
        return ["ping"]


def test_a_third_party_mcp_client_is_built_by_both_functions_and_used(plugins):
    plugins.mcp_client("tp-mcp", FakeMCP)  # a direct call
    assert "tp-mcp" in plugins.names("mcp_client")
    assert plugins.get("mcp_client", "tp-mcp") is FakeMCP

    by_builder = skye.mcp_client("http://x/mcp", impl="tp-mcp", headers={"a": "b"}, timeout=3.0)
    by_function = create_mcp_client("http://x/mcp", impl="tp-mcp")
    assert type(by_builder) is type(by_function) is FakeMCP
    assert (by_builder.target, by_builder.headers, by_builder.timeout) == (
        "http://x/mcp",
        {"a": "b"},
        3.0,
    )
    assert (by_function.headers, by_function.timeout) == (None, 30.0)
    assert asyncio.run(by_builder.list_tools()) == ["ping"]


def test_a_third_party_mcp_client_added_by_a_decorator_is_found_next_to_the_built_ins(plugins):
    @plugins.mcp_client("tp-mcp-decorated")
    class Decorated(FakeMCP):
        pass

    assert plugins.names("mcp_client") == sorted(plugins.names("mcp_client"))  # a sorted list
    assert {"skyemcp", "fastmcp", "tp-mcp-decorated"} <= set(plugins.names("mcp_client"))
    assert type(skye.mcp_client("http://x/mcp", impl="tp-mcp-decorated")) is Decorated


# -- a decision provider (58.3) ----------------------------------------------------------------------------------------------------


class Decider:
    """A decision provider of a third party: the first option gets ``bias``, the others share the rest."""

    def __init__(self, bias: float = 1.0) -> None:
        self.bias = bias

    async def decide(self, prompt: str, options: Sequence[str]) -> DecisionResult:
        rest = (1.0 - self.bias) / max(len(options) - 1, 1)
        probabilities = {o: self.bias if i == 0 else rest for i, o in enumerate(options)}
        return DecisionResult(options[0], probabilities)


def test_a_decision_provider_added_by_a_decorator_is_deduced_built_by_both_functions_and_used(
    plugins,
):
    decorated = plugins.provider("third-party-decider")(Decider)
    assert decorated is Decider  # the decorator returned the class
    assert plugins.get("provider", "third-party-decider") is Decider

    # the function is deduced from the method `decide`
    assert "third-party-decider" in plugins.names("provider", function="decision")
    assert "third-party-decider" not in plugins.names("provider", function="model")
    assert "third-party-decider" not in plugins.names("provider", function="embedding")

    by_provider = skye.provider("third-party-decider", provider_type="decision", bias=0.8)
    by_accessor = create_decision_model("third-party-decider", bias=0.8)
    assert type(by_provider) is type(by_accessor) is Decider
    assert isinstance(by_provider, DecisionModel)

    result = asyncio.run(by_provider.decide("Which route fits?", ["cheap", "strong", "refuse"]))
    assert result.choice == "cheap"
    assert result.probabilities["cheap"] == pytest.approx(0.8)
    assert sum(result.probabilities.values()) == pytest.approx(1.0)


def test_a_decision_provider_added_by_a_direct_call_is_found_by_the_name_alone(plugins):
    plugins.provider("third-party-direct", Decider)
    assert isinstance(
        skye.provider("third-party-direct"), Decider
    )  # one function: no provider_type
    assert isinstance(create_decision_model("third-party-direct"), Decider)
