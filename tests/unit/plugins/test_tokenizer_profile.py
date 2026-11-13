"""A tokenizer is named in a profile and counted through it (task 17.3, Requirements 59.11 and
59.10).

The cases of ``examples/plugins/tokenizer.py`` and ``tokenizer_provider.py``, with the real
``openai`` profile. The merge itself is tested in
``test_profile_merge.py`` and the table of ``register_tokenizer`` in
``tests/unit/models/test_register_tokenizer_table.py``. Every test puts the
default registrar back as it was.
"""

from __future__ import annotations

import pytest

from skye import Plugins
from skye.base.profile import ModelProfile, ProviderProfile
from skye.models import OpenAICompatibleProvider, TokenCounter
from skye.models.cost import CostCalculator
from tests.unit.plugins.registrar_state import restored_default_registrar

TEXT = "one two three four"  # 4 words, 18 characters


class Words:
    def encode(self, text: str) -> list[str]:
        return text.split()


class Chunks:
    """A token is a piece of four characters."""

    def encode(self, text: str) -> list[str]:
        return [text[i : i + 4] for i in range(0, len(text), 4)]


@pytest.fixture(autouse=True)
def default_registrar_put_back():
    with restored_default_registrar() as registrar:
        yield registrar


@pytest.fixture
def plugins() -> Plugins:
    handle = Plugins()

    @handle.tokenizer("zz-words")
    def words(model: str) -> Words:
        return Words()

    @handle.tokenizer("zz-chunks")
    def chunks(model: str) -> Chunks:
        return Chunks()

    return handle


# -- 1. a change of the tokenizer of one model of an existing provider
# ----------------------------------------


def test_the_tokenizer_of_gpt_4o_changes_and_its_own_price_and_the_endpoint_stay(plugins):
    old = plugins.get_profile("openai")
    price_before = CostCalculator.pricing_for("gpt-4o")
    plugins.profile("openai", models={"gpt-4o": ModelProfile(tokenizer="zz-words")})
    new = plugins.get_profile("openai")

    assert TokenCounter.count_tokens(TEXT, "gpt-4o") == 4  # the new tokenizer
    assert new.models["gpt-4o"].tokenizer == "zz-words"
    assert new.models["gpt-4o"].prompt_price == old.models["gpt-4o"].prompt_price
    assert new.models["gpt-4o"].completion_price == old.models["gpt-4o"].completion_price
    assert new.default_api_base == old.default_api_base  # the endpoint
    assert CostCalculator.pricing_for("gpt-4o") == price_before  # the price is read as before


def test_the_price_of_a_model_that_has_one_stays_when_its_tokenizer_changes(plugins):
    """``gpt-4o`` has no price in the built-in profile, so the check of a price uses
    ``gpt-4-turbo``, which has one."""
    price = CostCalculator.pricing_for("gpt-4-turbo")
    assert price == {"prompt": 10.0, "completion": 30.0}
    plugins.profile("openai", models={"gpt-4-turbo": ModelProfile(tokenizer="zz-words")})
    assert plugins.get_profile("openai").models["gpt-4-turbo"].tokenizer == "zz-words"
    assert CostCalculator.pricing_for("gpt-4-turbo") == price


def test_the_other_models_of_the_provider_are_not_changed(plugins):
    old = plugins.get_profile("openai")
    mini_before = TokenCounter.count_tokens(TEXT, "gpt-4o-mini")
    mini_price = CostCalculator.pricing_for("gpt-4o-mini")
    plugins.profile("openai", models={"gpt-4o": ModelProfile(tokenizer="zz-words")})
    new = plugins.get_profile("openai")

    assert sorted(new.models) == sorted(old.models)
    for name in old.models:
        if name != "gpt-4o":
            assert new.models[name] == old.models[name]
    assert TokenCounter.count_tokens(TEXT, "gpt-4o-mini") == mini_before
    assert CostCalculator.pricing_for("gpt-4o-mini") == mini_price


def test_a_dated_name_of_the_changed_model_finds_the_same_tokenizer(plugins):
    plugins.profile("openai", models={"gpt-4o": ModelProfile(tokenizer="zz-words")})
    assert TokenCounter.count_tokens(TEXT, "gpt-4o-2024-08-06") == 4


# -- 2. a new provider names its tokenizer in its profile (examples/plugins/tokenizer_provider.py)
# ----------


def register_acme(plugins: Plugins) -> None:
    plugins.provider(
        "zz-acme",
        OpenAICompatibleProvider,
        profile=ProviderProfile(
            "zz-acme",
            api_key_variables=("ZZ_ACME_API_KEY",),
            default_api_base="https://api.acme.example/v1",
            models={
                "zz-acme-small": ModelProfile(tokenizer="zz-chunks"),
                "zz-acme-large": ModelProfile(prompt_price=2.00, completion_price=8.00),
            },
        ),
    )


def test_a_new_provider_names_its_tokenizer_and_the_counter_uses_it(plugins):
    register_acme(plugins)
    assert len(TEXT) == 18
    assert TokenCounter.count_tokens(TEXT, "zz-acme-small") == 5  # 18 characters make 5 pieces of 4


def test_a_dated_name_of_a_model_of_the_new_provider_finds_the_tokenizer(plugins):
    register_acme(plugins)
    assert TokenCounter.count_tokens(TEXT, "zz-acme-small-2026-01-15") == 5


def test_the_price_of_a_model_of_the_new_provider_is_read_from_its_profile(plugins):
    register_acme(plugins)
    assert CostCalculator.pricing_for("zz-acme-large") == {"prompt": 2.00, "completion": 8.00}


# -- 3. a model with no tokenizer gets the estimate (Requirement 59.10)
# ---------------------------------------


def test_a_model_of_the_profile_with_no_tokenizer_gets_the_estimate(plugins):
    register_acme(plugins)
    plugins.profile("openai", models={"gpt-4o": ModelProfile(tokenizer="zz-words")})
    # 10 words, 19 characters: the estimate (about 4 characters a token) is not the word count
    text = "a b c d e f g h i j"
    estimate = TokenCounter.count_tokens(text, "zz-model-nobody-has-heard-of")
    assert estimate != 10
    assert (
        TokenCounter.count_tokens(text, "zz-acme-large") == estimate
    )  # in a profile, with no tokenizer
    assert TokenCounter.count_tokens(text, "gpt-4o") == 10  # the changed model counts words


def test_a_model_with_no_profile_gets_the_estimate_and_an_unknown_cost(plugins):
    assert TokenCounter.count_tokens(TEXT, "zz-no-profile") == TokenCounter.count_tokens(
        TEXT, "zz-another-no-profile"
    )
    assert CostCalculator.pricing_for("zz-no-profile") is None  # the cost is unknown


def test_a_merge_that_leaves_the_tokenizer_out_keeps_the_tokenizer_it_had(plugins):
    plugins.profile("openai", models={"gpt-4o": ModelProfile(tokenizer="zz-words")})
    plugins.profile(
        "openai", models={"gpt-4o": {"message_overhead": 7}}
    )  # a mapping: only this field
    assert plugins.get_profile("openai").models["gpt-4o"].tokenizer == "zz-words"
    assert TokenCounter.count_tokens(TEXT, "gpt-4o") == 4
