"""The ``lazy_complex`` strategy: a deliberately naive choice by how hard the request looks (plugins task 23.2, D113).

The models of a route are ordered from the cheap one to the strong one; the level is 0 to 2: +1 for a long prompt, +1 for tools or a structured
answer. Fake models only, no network.
"""

from __future__ import annotations

import pytest

from skye.base.completion import CompleteRequest
from skye.base.interfaces.router import RoutingStrategy
from skye.base.messages import UserMessage
from skye.base.prompt_parts import OutputSchema
from skye.router import ModelRouter, ModelTarget, RouteConfig, StrategyContext
from skye.router.plugins.lazy_complex import LONG_PROMPT_TOKENS, LazyComplexStrategy
from skye.router.routing_strategies import RoutingStrategySelector, normalize_strategy
from tests.unit.router.test_serving_record import FakeModel


def _choose(models, *, tokens=None, capabilities=None, response_schema=None, request=True):
    selector = RoutingStrategySelector(
        health={}, rate_limits={}, model_targets={}, round_robin_index={}
    )
    estimate = None if tokens is None else (float(tokens), 100.0)
    made = (
        CompleteRequest(
            model="chat",
            messages=[UserMessage(content="x")],
            capabilities=capabilities,
            response_schema=response_schema,
        )
        if request
        else None
    )
    return selector.apply_strategy(
        models, "chat", "lazy_complex", token_estimate=estimate, request=made
    )


TOOLS = [object()]
SCHEMA = OutputSchema("answer", {"type": "object"})


# -- the levels ------------------------------------------------------------------------------------------------


def test_an_easy_request_takes_the_cheap_model():
    assert _choose(["cheap", "strong"], tokens=10) == "cheap"


def test_no_request_and_no_estimate_is_level_0_the_cheap_model():
    assert _choose(["cheap", "strong"], request=False) == "cheap"


def test_a_long_prompt_takes_the_strong_model_of_two():
    assert _choose(["cheap", "strong"], tokens=LONG_PROMPT_TOKENS + 1) == "strong"


def test_a_prompt_exactly_at_the_limit_is_not_long():
    assert _choose(["cheap", "strong"], tokens=LONG_PROMPT_TOKENS) == "cheap"


def test_tools_take_the_strong_model_of_two():
    assert _choose(["cheap", "strong"], tokens=10, capabilities=TOOLS) == "strong"


def test_a_response_schema_takes_the_strong_model_of_two():
    assert _choose(["cheap", "strong"], tokens=10, response_schema=SCHEMA) == "strong"


def test_level_2_takes_the_strong_model_of_two():
    assert (
        _choose(["cheap", "strong"], tokens=LONG_PROMPT_TOKENS + 1, capabilities=TOOLS) == "strong"
    )


def test_three_models_take_the_first_the_middle_and_the_last():
    models = ["cheap", "middle", "strong"]
    assert _choose(models, tokens=10) == "cheap"
    assert _choose(models, tokens=LONG_PROMPT_TOKENS + 1) == "middle"
    assert _choose(models, tokens=LONG_PROMPT_TOKENS + 1, response_schema=SCHEMA) == "strong"


def test_one_model_is_always_chosen():
    assert _choose(["only"], tokens=LONG_PROMPT_TOKENS + 1, capabilities=TOOLS) == "only"
    assert _choose(["only"], request=False) == "only"


def test_the_order_of_the_models_is_the_convention_cheap_first_strong_last():
    assert _choose(["a", "b"], tokens=10) == "a"
    assert _choose(["b", "a"], tokens=10) == "b"
    assert _choose(["a", "b"], tokens=10, capabilities=TOOLS) == "b"
    assert _choose(["b", "a"], tokens=10, capabilities=TOOLS) == "a"


def test_the_strategy_reads_only_the_context_and_keeps_no_state():
    strategy = LazyComplexStrategy(
        RoutingStrategySelector(health={}, rate_limits={}, model_targets={}, round_robin_index={})
    )
    context = StrategyContext(models=("cheap", "strong"), token_estimate=(900.0, 10.0))
    assert [strategy.select(context) for _ in range(3)] == ["strong"] * 3


# -- the name is valid wherever a built-in name is ---------------------------------------------------------------


def test_it_is_not_a_member_of_the_enumeration_and_is_a_registered_name():
    assert "lazy_complex" not in [member.value for member in RoutingStrategy]
    assert normalize_strategy("lazy_complex") == "lazy_complex"


def _router(**kwargs):
    router = ModelRouter(
        routes=[
            RouteConfig(
                alias="chat",
                targets=[
                    ModelTarget(model="gpt-4o-mini", provider="openai", api_key="k"),
                    ModelTarget(model="o3", provider="openai", api_key="k"),
                ],
            )
        ],
        **kwargs,
    )
    router.models.update({model_id: FakeModel(model_id) for model_id in router.models})
    return router


def test_the_router_takes_the_name_and_sends_an_easy_request_to_the_cheap_model():
    router = _router(strategy="lazy_complex")
    assert router.strategy == "lazy_complex"
    response = router.complete(messages=[UserMessage(content="hi")], model="chat")
    assert response.content.endswith("gpt-4o-mini")


def test_the_router_sends_a_long_prompt_to_the_strong_model():
    router = _router(strategy="lazy_complex")
    long_text = "word " * (LONG_PROMPT_TOKENS * 4 + 400)
    response = router.complete(messages=[UserMessage(content=long_text)], model="chat")
    assert response.content.endswith("o3")


def test_a_route_takes_the_name():
    route = RouteConfig(
        alias="chat",
        targets=[ModelTarget(model="gpt-4o-mini", provider="openai", api_key="k")],
        strategy="lazy_complex",
    )
    assert route.strategy == "lazy_complex"


def test_from_config_dict_takes_the_name():
    config = {
        "routes": [
            {
                "alias": "chat",
                "strategy": "lazy_complex",
                "targets": [
                    {"model": "gpt-4o-mini", "provider": "openai", "api_key": "k"},
                    {"model": "o3", "provider": "openai", "api_key": "k"},
                ],
            }
        ],
        "strategy": "lazy_complex",
    }
    router = ModelRouter.from_config_dict(config)
    assert router.strategy == "lazy_complex"
    assert router.get_route("chat").strategy == "lazy_complex"


def test_to_config_writes_the_name():
    assert _router(strategy="lazy_complex").to_config()["strategy"] == "lazy_complex"


def test_a_skye_router_block_accepts_the_name():
    from skye.base.dsl import check_text

    text = (
        'router "main" {\n'
        '  strategy = "lazy_complex"\n'
        '  route "smart" = ["openai/gpt-4o-mini", "openai/o3"]\n'
        "}\n"
    )
    errors = check_text(text)
    assert not errors, errors


def test_a_skye_router_block_still_refuses_an_unknown_name():
    from skye.base.dsl import check_text

    text = (
        'router "main" {\n'
        '  strategy = "lazy_complexx"\n'
        '  route "smart" = ["openai/gpt-4o-mini", "openai/o3"]\n'
        "}\n"
    )
    assert check_text(text)


@pytest.mark.parametrize("name", ["lazy_complex"])
def test_the_name_is_listed_after_the_enumeration_members(name):
    from skye.router.routing_strategies import registered_strategies

    names = registered_strategies()
    assert names.index(name) >= len(RoutingStrategy)
