"""``skye.provider`` builds the three functions of the single kind ``provider`` (tasks 15.3 and 15.5, Requirements 56.11, 56.12, 58.3).

A model provider is the default, ``provider_type="embedding"`` and ``provider_type="decision"`` give the others, and a name that has one
function only gives that one. ``create_decision_model`` stays as the typed accessor and builds the same object.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

import pytest

import skye
from skye.base.exceptions import ConfigurationError
from skye.base.interfaces.decision import DecisionModel, DecisionResult
from skye.base.plugins import get_registrar
from skye.models import JevDecisionModel, create_decision_model
from skye.models.registry import ProviderRegistry

ENDPOINT = "https://jev.example/decide"


class FirstOption:
    """A decision provider of a third party: the first option takes all the probability."""

    def __init__(self, bias: float = 1.0) -> None:
        self.bias = bias

    async def decide(self, prompt: str, options: Sequence[str]) -> DecisionResult:
        rest = (1.0 - self.bias) / max(len(options) - 1, 1)
        return DecisionResult(
            options[0], {o: self.bias if i == 0 else rest for i, o in enumerate(options)}
        )


@pytest.fixture
def first_option() -> Iterator[str]:
    """``first-option`` registered on the default registrar as a decision provider, and taken away after the test."""
    registrar = get_registrar()
    registrar.provider("first-option", FirstOption, function="decision", replace=True)
    try:
        yield "first-option"
    finally:
        registrar.unregister("provider", "first-option", "decision")


def test_provider_type_decision_builds_the_built_in_decision_model():
    model = skye.provider("jev", provider_type="decision", endpoint=ENDPOINT, timeout=5.0)
    assert isinstance(model, JevDecisionModel)
    assert isinstance(model, DecisionModel)
    assert model.endpoint == ENDPOINT and model.timeout == 5.0


def test_provider_and_create_decision_model_build_the_same_kind_of_object():
    by_provider = skye.provider("jev", provider_type="decision", endpoint=ENDPOINT)
    by_accessor = create_decision_model("jev", endpoint=ENDPOINT)
    assert type(by_provider) is type(by_accessor) is JevDecisionModel
    assert by_provider.endpoint == by_accessor.endpoint


def test_a_name_with_one_function_gives_that_function_without_provider_type():
    assert isinstance(skye.provider("jev", endpoint=ENDPOINT), JevDecisionModel)  # a decision only
    cohere = skye.provider(
        "cohere", api_key="k", model="embed-english-v3.0"
    )  # an embedding only, as before
    assert hasattr(cohere, "encode")


def test_a_third_party_decision_provider_is_built_both_ways(first_option):
    by_provider = skye.provider(first_option, provider_type="decision", bias=0.8)
    by_accessor = create_decision_model(first_option, bias=0.8)
    assert isinstance(by_provider, FirstOption) and isinstance(by_accessor, FirstOption)
    assert by_provider.bias == by_accessor.bias == 0.8
    assert isinstance(by_provider, DecisionModel)


def test_the_default_provider_type_still_builds_a_model_provider():
    client = skye.provider("openai", api_key="sk-test")
    assert hasattr(client, "complete")


def test_an_unknown_decision_name_lists_the_decision_providers():
    with pytest.raises(ConfigurationError) as caught:
        skye.provider("nope", provider_type="decision")
    assert "jev" in str(caught.value)
    assert (
        "openai" not in str(caught.value).split("registered:")[-1]
    )  # only the names of the function


def test_asking_a_decision_provider_for_a_model_says_how_to_ask():
    with pytest.raises(
        ConfigurationError, match='is a decision provider: pass provider_type="decision"'
    ):
        skye.provider("jev", provider_type="model")
    with pytest.raises(ConfigurationError, match="not found"):
        ProviderRegistry.get_model_provider("jev")


def test_a_decision_provider_is_not_listed_as_a_model_or_embedding_provider():
    assert "jev" not in ProviderRegistry.list_model_providers()
    assert "jev" not in ProviderRegistry.list_embedding_providers()
    assert "jev" in get_registrar().names("provider", "decision")
