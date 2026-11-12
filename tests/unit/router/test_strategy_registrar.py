"""Routing strategies by name through the registrar (plugins task 9.1, Requirement 58.1).

The eight built-ins are registered under the values of ``RoutingStrategy``; a name that a plugin registers is valid wherever a built-in name is: the
router, a route, ``from_config_dict``, ``to_config`` and ``set_routing_strategy``. Fake models only, no network.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from skye.base.exceptions import ConfigurationError
from skye.base.interfaces.router import RoutingStrategy
from skye.base.messages import UserMessage
from skye.router import ModelRouter, ModelTarget, RouteConfig
from skye.router.routing_strategies import (
    RouterStrategy,
    RoutingStrategySelector,
    normalize_strategy,
    registered_strategies,
    strategy_name,
)
from tests.unit.plugins.registrar_state import restored_default_registrar
from tests.unit.router.test_serving_record import FakeModel

MODELS = ["gpt-4o", "o3", "claude-sonnet"]


def shortest_name(available_models: list[str]) -> str:
    return min(available_models, key=len)


@pytest.fixture
def registrar():
    with restored_default_registrar() as registrar:
        registrar.routing_strategy("shortest-name", shortest_name)
        yield registrar


def _selector() -> RoutingStrategySelector:
    """No metrics are read, so a tracker with no limit stands for each model (the rate-limit strategy asks for one)."""
    unlimited = {model: SimpleNamespace(rpm_limit=None, tpm_limit=None) for model in MODELS}
    return RoutingStrategySelector(
        health={}, rate_limits=unlimited, model_targets={}, round_robin_index={}
    )


def _router(**kwargs):
    router = ModelRouter(
        routes=[
            RouteConfig(
                alias="chat",
                targets=[
                    ModelTarget(model="gpt-4o", provider="openai", api_key="k"),
                    ModelTarget(model="o3", provider="openai", api_key="k"),
                ],
            )
        ],
        **kwargs,
    )
    router.models.update({model_id: FakeModel(model_id) for model_id in router.models})
    return router


# -- the built-ins ----------------------------------------------------------------------------------------------


def test_every_member_of_the_enumeration_is_registered_as_a_router_strategy():
    with restored_default_registrar() as registrar:
        for member in RoutingStrategy:
            assert issubclass(registrar.get("routing_strategy", member.value), RouterStrategy)


@pytest.mark.parametrize("member", list(RoutingStrategy), ids=lambda m: m.value)
def test_every_member_still_chooses_a_model(member):
    chosen = _selector().apply_strategy(MODELS, "alias", member, token_estimate=(10, 10))
    assert chosen in MODELS


def test_a_member_and_its_value_are_the_same_strategy():
    selector = _selector()
    picks = [selector.apply_strategy(MODELS, "a", RoutingStrategy.ROUND_ROBIN) for _ in range(3)]
    assert picks == MODELS
    selector = _selector()
    picks = [selector.apply_strategy(MODELS, "a", "round_robin") for _ in range(3)]
    assert picks == MODELS


def test_no_strategy_picks_the_first_model():
    assert _selector().apply_strategy(MODELS) == "gpt-4o"


def test_no_model_is_an_error():
    with pytest.raises(ValueError):
        _selector().apply_strategy([], strategy="round_robin")


# -- a strategy of a plugin -------------------------------------------------------------------------------------


def test_a_registered_function_is_a_strategy(registrar):
    assert _selector().apply_strategy(MODELS, strategy="shortest-name") == "o3"


def test_the_router_takes_a_registered_name(registrar):
    router = ModelRouter(strategy="shortest-name")
    assert router.strategy == "shortest-name"
    assert normalize_strategy("least_busy") is RoutingStrategy.LEAST_BUSY


def test_a_route_takes_a_registered_name(registrar):
    route = RouteConfig(
        alias="chat",
        targets=[ModelTarget(model="gpt-4o", provider="openai", api_key="k")],
        strategy="shortest-name",
    )
    assert route.strategy == "shortest-name"


def test_the_router_runs_the_strategy_of_a_plugin(registrar):
    router = _router(strategy="shortest-name")
    response = router.complete(messages=[UserMessage(content="hi")], model="chat")
    assert response.content.endswith("o3")


def test_the_strategy_of_a_route_wins_over_the_router_one(registrar):
    router = ModelRouter(
        routes=[
            RouteConfig(
                alias="chat",
                targets=[
                    ModelTarget(model="gpt-4o", provider="openai", api_key="k"),
                    ModelTarget(model="o3", provider="openai", api_key="k"),
                ],
                strategy="shortest-name",
            )
        ],
        strategy=RoutingStrategy.ROUND_ROBIN,
    )
    router.models.update({model_id: FakeModel(model_id) for model_id in router.models})
    for _ in range(3):
        assert router.complete(messages=[UserMessage(content="hi")], model="chat").content.endswith(
            "o3"
        )


def test_set_routing_strategy_takes_a_registered_name(registrar):
    router = ModelRouter()
    router.set_routing_strategy("shortest-name")
    assert router.strategy == "shortest-name"
    router.set_routing_strategy("least_busy")
    assert router.strategy is RoutingStrategy.LEAST_BUSY


def test_from_config_dict_takes_a_registered_name(registrar):
    config = {
        "strategy": "shortest-name",
        "routes": [
            {
                "alias": "chat",
                "strategy": "least_busy",
                "targets": [{"model": "gpt-4o", "provider": "openai", "api_key": "k"}],
            }
        ],
    }
    router = ModelRouter.from_config_dict(config)
    assert router.strategy == "shortest-name"
    assert router.aliases["chat"].strategy is RoutingStrategy.LEAST_BUSY


def test_to_config_writes_the_name_and_reads_it_back(registrar):
    config = {
        "strategy": "round_robin",
        "routes": [
            {
                "alias": "chat",
                "strategy": "shortest-name",
                "targets": [{"model": "gpt-4o", "provider": "openai", "api_key": "k"}],
            }
        ],
    }
    router = ModelRouter.from_config_dict(config)
    written = router.to_config(include_secrets=True)
    assert written["strategy"] == "round_robin"
    assert written["routes"][0]["strategy"] == "shortest-name"
    assert ModelRouter.from_config_dict(written).aliases["chat"].strategy == "shortest-name"


def test_a_built_in_name_can_be_replaced_like_any_other(registrar):
    registrar.routing_strategy("least_busy", lambda models: models[-1], replace=True)
    assert (
        _selector().apply_strategy(MODELS, strategy=RoutingStrategy.LEAST_BUSY) == "claude-sonnet"
    )


# -- the errors -------------------------------------------------------------------------------------------------


def test_an_unknown_name_lists_the_names_that_can_be_used(registrar):
    with pytest.raises(ConfigurationError) as caught:
        ModelRouter(strategy="nope")
    assert "nope" in str(caught.value)
    valid = caught.value.details["valid_strategies"]
    assert "shortest-name" in valid and "round_robin" in valid


def test_from_config_dict_rejects_an_unknown_route_strategy(registrar):
    config = {
        "routes": [
            {
                "alias": "chat",
                "strategy": "nope",
                "targets": [{"model": "gpt-4o", "provider": "openai", "api_key": "k"}],
            }
        ]
    }
    with pytest.raises(ConfigurationError) as caught:
        ModelRouter.from_config_dict(config)
    message = str(
        caught.value
    )  # the route error is wrapped with the cause, which lists the names that can be used
    assert "chat" in message and "nope" in message and "shortest-name" in message


def test_registered_strategies_are_the_built_ins_then_the_plugin_names(registrar):  # lazy_complex is a built-in
    names = registered_strategies()
    assert names[:8] == [member.value for member in RoutingStrategy]
    assert names[8:] == ["lazy_complex", "shortest-name"]  # the built-in that is not a member, then the plugin's


def test_a_strategy_that_returns_an_unknown_id_is_an_error(registrar):
    registrar.routing_strategy("lost", lambda models: "somewhere-else")
    with pytest.raises(ConfigurationError) as caught:
        _selector().apply_strategy(MODELS, strategy="lost")
    assert "somewhere-else" in str(caught.value)


def test_a_strategy_that_was_removed_is_an_error_at_the_call(registrar):
    selector = _selector()
    registrar.unregister("routing_strategy", "shortest-name")
    with pytest.raises(ConfigurationError):
        selector.apply_strategy(MODELS, strategy="shortest-name")


def test_the_name_of_a_strategy():
    assert strategy_name(RoutingStrategy.COST_BASED) == "cost_based"
    assert strategy_name("shortest-name") == "shortest-name"
