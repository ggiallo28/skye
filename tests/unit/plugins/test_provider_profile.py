"""One profile for one provider name, and the price of Jev (task 15.4, Requirements 59.7, 59.8,
59.12, 58.3).

A profile is kept under the registered name of the provider whatever the functions registered. The
profile of Jev is named ``jev``, the
registered name, and the ``CostCalculator`` reads its price through the registrar.
"""

from __future__ import annotations

import pytest

from skye.base.completion import TokenUsage
from skye.base.exceptions import ConfigurationError
from skye.base.plugins import Registrar, get_registrar
from skye.base.profile import ProviderProfile
from skye.models import plugins as _plugin
from skye.models.cost import CostCalculator


@pytest.fixture
def registrar() -> Registrar:
    fresh = Registrar()
    _plugin.register(fresh)
    return fresh


def usage(prompt: int, completion: int = 0) -> TokenUsage:
    return TokenUsage(
        prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion
    )


# -- the profile is under the registered name
# ----------------------------------------------------------------------


def test_the_profile_of_jev_is_named_by_the_registered_name(registrar):
    profile = registrar.get_profile("jev")
    assert profile is not None and profile.name == "jev"
    assert (
        registrar.get_profile("typesafe") is None
    )  # the folder is the company, not a provider name
    assert (profile.models["jev"].prompt_price, profile.models["jev"].completion_price) == (
        0.042,
        0.0,
    )


def test_the_decision_provider_is_registered_with_its_profile(registrar):
    assert registrar.has("provider", "jev", "decision")
    assert registrar.get_profile("jev") is _plugin.profiles()["jev"]


def test_every_built_in_profile_is_named_by_a_registered_provider_name(registrar):
    for profile_name in _plugin.profiles():
        assert registrar.get_profile(profile_name) is not None, profile_name


# -- one profile for the functions of one name
# ----------------------------------------------------------------------


def test_a_chat_class_and_an_embedding_class_of_one_name_share_one_profile(registrar):
    assert registrar.has("provider", "openai", "model")
    assert registrar.has("provider", "openai", "embedding")
    profile = registrar.get_profile("openai")
    assert profile is _plugin.profiles()["openai"]
    # the second registration of the pair gave the same profile and it was accepted: there is one
    # object for the name
    assert registrar.get_profile("openai") is profile


def test_a_different_second_profile_for_the_name_raises(registrar):
    other = ProviderProfile("openai", default_api_base="https://other.example/v1")
    with pytest.raises(ConfigurationError, match="different profile"):
        registrar.provider("openai", object, profile=other, function="decision")
    assert registrar.get_profile("openai") is _plugin.profiles()["openai"]  # nothing changed
    assert not registrar.has("provider", "openai", "decision")


def test_replace_overrides_the_profile_of_the_name(registrar):
    other = ProviderProfile("jev", default_api_base="https://other.example/decide")
    registrar.provider(
        "jev",
        f"{_plugin.__name__}.typesafe:JevDecisionModel",
        profile=other,
        function="decision",
        replace=True,
    )
    assert registrar.get_profile("jev") is other


def test_the_same_profile_given_again_is_accepted(registrar):
    registrar.provider(
        "jev",
        f"{_plugin.__name__}.typesafe:JevDecisionModel",
        profile=_plugin.profiles()["jev"],
        function="decision",
        replace=True,
    )
    assert registrar.get_profile("jev") is _plugin.profiles()["jev"]


# -- the cost of a decision call
# ----------------------------------------------------------------------------------


def test_the_cost_calculator_prices_a_decision_call_from_the_profile():
    assert get_registrar().get_profile("jev") is not None
    assert CostCalculator.get_pricing("jev") == {"prompt": 0.042, "completion": 0.0}
    assert CostCalculator.calculate_cost("jev", usage(2_000_000, 500)) == pytest.approx(0.084)
    assert CostCalculator.calculate_cost("jev", usage(1_000)) == pytest.approx(0.000042)


def test_a_dated_name_of_jev_finds_the_price():
    pricing = CostCalculator.pricing_for("jev-2026-01-15")
    assert pricing == {"prompt": 0.042, "completion": 0.0}


def test_an_unknown_model_of_the_provider_has_an_unknown_cost():
    assert (
        CostCalculator.get_pricing("jev-xl") is None
    )  # the profile has no such model (Requirement 59.10)
    assert CostCalculator.calculate_cost("jev-xl", usage(1_000_000)) == 0.0


def test_the_price_of_jev_is_listed_with_the_other_models():
    assert "jev" in CostCalculator.list_models()
