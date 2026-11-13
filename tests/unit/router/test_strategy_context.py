"""The read-only ``StrategyContext`` of a routing strategy and ``with_context`` (plugins task 23.1, Requirement 58.7, D113).

A strategy is one of three things, told apart by the object and never by its parameters: a function of the ids, a function marked with
``with_context`` that gets the context, or a ``RouterStrategy`` subclass whose ``select`` gets the context. Fake models only, no network.
"""

from __future__ import annotations

import asyncio
import dataclasses
from types import SimpleNamespace

import pytest

from skye.base.completion import CompleteRequest
from skye.base.exceptions import ConfigurationError
from skye.base.messages import UserMessage
from skye.router import ModelRouter, ModelTarget, RouteConfig, StrategyContext, with_context
from skye.router.routing_strategies import RouterStrategy, RoutingStrategySelector
from tests.unit.plugins.registrar_state import restored_default_registrar
from tests.unit.router.test_serving_record import FakeModel

MODELS = ["cheap", "strong"]


def _selector(**kwargs) -> RoutingStrategySelector:
    return RoutingStrategySelector(
        health={}, rate_limits={}, model_targets=kwargs.pop("targets", {}), round_robin_index={}
    )


def _router(strategy: str) -> ModelRouter:
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
        strategy=strategy,
    )
    router.models.update({model_id: FakeModel(model_id) for model_id in router.models})
    return router


@pytest.fixture
def registrar():
    with restored_default_registrar() as registrar:
        yield registrar


# -- the context -----------------------------------------------------------------------------------------------


def test_the_context_is_frozen_and_its_mappings_are_read_only():
    context = _selector().context(["a", "b"], "alias", (10.0, 20.0), None)
    assert context.models == ("a", "b")
    assert context.alias == "alias"
    assert context.token_estimate == (10.0, 20.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        context.alias = "other"  # type: ignore[misc]
    with pytest.raises(TypeError):
        context.snapshot["a"] = {}  # type: ignore[index]
    with pytest.raises(TypeError):
        context.targets["a"] = None  # type: ignore[index]
    with pytest.raises(TypeError):
        context.snapshot["a"]["latency_ms"] = 1.0  # type: ignore[index]


def test_the_context_has_defaults_for_a_context_built_by_hand():
    context = StrategyContext(models=("a",))
    assert (context.alias, context.token_estimate, context.request) == (None, None, None)
    assert dict(context.snapshot) == {} and dict(context.targets) == {}


def test_the_context_carries_the_snapshot_and_the_targets_of_its_models():
    target = SimpleNamespace(weight=1)
    selector = _selector(targets={"a": target, "z": target})
    selector._snapshot = {"a": {"latency_ms": 12.0}, "z": {"latency_ms": 99.0}}
    context = selector.context(["a", "b"])
    assert dict(context.snapshot["a"]) == {"latency_ms": 12.0}
    assert dict(context.snapshot["b"]) == {}  # a model with no tracker has an empty entry
    assert set(context.targets) == {
        "a"
    }  # only the models of the call, and only those with a target
    assert "z" not in context.snapshot


def test_changing_the_selector_snapshot_later_does_not_change_a_context_already_made():
    selector = _selector()
    selector._snapshot = {"a": {"latency_ms": 1.0}}
    context = selector.context(["a"])
    selector._snapshot["a"]["latency_ms"] = 500.0
    assert context.snapshot["a"]["latency_ms"] == 1.0


# -- the three call shapes -------------------------------------------------------------------------------------


def test_with_context_returns_the_function_unchanged():
    def pick(context):
        return context.models[0]

    assert with_context(pick) is pick
    assert pick(StrategyContext(models=("a", "b"))) == "a"


def test_a_plain_function_gets_the_list_of_the_ids(registrar):
    seen = []

    def ids_only(available_models):
        seen.append(available_models)
        return available_models[-1]

    registrar.routing_strategy("ids-only", ids_only)
    assert _selector().apply_strategy(MODELS, strategy="ids-only") == "strong"
    assert seen == [["cheap", "strong"]] and isinstance(seen[0], list)


def test_a_marked_function_gets_the_context(registrar):
    seen = []

    @with_context
    def wants_context(context):
        seen.append(context)
        return context.models[0]

    registrar.routing_strategy("wants-context", wants_context)
    request = CompleteRequest(model="chat", messages=[UserMessage(content="hello")])
    assert (
        _selector().apply_strategy(
            MODELS, "chat", "wants-context", token_estimate=(5.0, 5.0), request=request
        )
        == "cheap"
    )
    (context,) = seen
    assert isinstance(context, StrategyContext)
    assert (context.models, context.alias, context.token_estimate) == (
        ("cheap", "strong"),
        "chat",
        (5.0, 5.0),
    )
    assert context.request is request


def test_a_class_strategy_gets_the_context_in_select(registrar):
    seen = []

    class Last(RouterStrategy):
        def select(self, context):
            seen.append(context)
            return context.models[-1]

    registrar.routing_strategy("last", Last)
    assert _selector().apply_strategy(MODELS, strategy="last") == "strong"
    assert isinstance(seen[0], StrategyContext)


def test_the_shape_is_told_by_the_marker_and_not_by_the_parameters(registrar):
    """A function with the parameter name ``context`` that is not marked still gets the ids."""

    def named_context(context):
        return context[0]  # a list of ids, so this is the first id

    registrar.routing_strategy("named", named_context)
    assert _selector().apply_strategy(MODELS, strategy="named") == "cheap"


def test_an_id_that_is_not_one_of_the_models_is_an_error_for_a_marked_function(registrar):
    registrar.routing_strategy("lost", with_context(lambda context: "elsewhere"))
    with pytest.raises(ConfigurationError, match="not one of the available models"):
        _selector().apply_strategy(MODELS, strategy="lost")


# -- the request reaches the strategy from the router ----------------------------------------------------------


def test_the_router_gives_the_request_to_the_strategy_of_an_alias(registrar):
    seen = []

    @with_context
    def capture(context):
        seen.append(context)
        return context.models[0]

    registrar.routing_strategy("capture", capture)
    router = _router("capture")
    router.complete(messages=[UserMessage(content="Where is order 42?")], model="chat")
    (context,) = seen
    assert context.alias == "chat"
    assert context.request is not None and context.request.model == "chat"
    assert context.request.messages[0].content == "Where is order 42?"
    assert context.token_estimate is not None
    assert len(context.models) == 2 and all(model.startswith("chat:") for model in context.models)
    assert set(context.targets) == set(context.models)


def test_the_router_gives_the_request_to_the_strategy_with_no_alias(registrar):
    seen = []

    @with_context
    def capture(context):
        seen.append(context)
        return context.models[0]

    registrar.routing_strategy("capture", capture)
    router = _router("capture")
    request = CompleteRequest(model="not-an-alias", messages=[UserMessage(content="hi")])
    chosen = asyncio.run(router.select_model(request))
    (context,) = seen
    assert context.alias is None
    assert context.request is request
    assert chosen == context.models[0]
