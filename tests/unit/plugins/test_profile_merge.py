"""``plugins.profile``: a change merged into the profile of an existing provider (task 17.1, Requirement 59.11, D111).

Only what is given changes. The profile is frozen, so a new one is built and published under the write lock, and a call that raises changes
nothing. The tokenizer example is the one of ``examples/plugins/tokenizer.py``.
"""

from __future__ import annotations

import threading

import pytest

from skye.base.exceptions import ConfigurationError, ValidationError
from skye.base.interfaces.plugin import RegistrarInterface
from skye.base.plugins import Plugins, Registrar
from skye.base.profile import ModelProfile, ProviderProfile, RegionRule
from skye.models import TokenCounter
from skye.models.cost import CostCalculator
from tests.unit.plugins.registrar_state import restored_default_registrar


def acme_profile() -> ProviderProfile:
    return ProviderProfile(
        "acme",
        api_key_variables=("ACME_KEY",),
        default_api_base="https://api.acme.example/v1",
        models={
            "acme-1": ModelProfile(
                prompt_price=1.0, completion_price=2.0, message_overhead=4, info={"vision": True}
            ),
            "acme-2": ModelProfile(prompt_price=3.0, completion_price=6.0),
        },
    )


@pytest.fixture
def registrar() -> Registrar:
    fresh = Registrar()
    fresh.provider("acme", "acme.models:Chat", function="model", profile=acme_profile())
    return fresh


# -- the tokenizer example -----------------------------------------------------------------------------------------


def test_the_tokenizer_of_one_model_of_an_existing_provider_changes_and_nothing_else():
    text = "a b c d e f g h"  # 8 words, 15 characters
    with restored_default_registrar():
        plugins = Plugins()

        @plugins.tokenizer("words")
        def words(model):
            class Words:
                def encode(self, value):
                    return value.split()

            return Words()

        before = TokenCounter.count_tokens(text, "gpt-4o")  # fills the cache of the tokenizers
        mini = TokenCounter.count_tokens(text, "gpt-4o-mini")
        old = plugins.get_profile("openai")
        plugins.profile("openai", models={"gpt-4o": ModelProfile(tokenizer="words")})
        assert TokenCounter.count_tokens(text, "gpt-4o") == 8
        assert before != 8
        assert TokenCounter.count_tokens(text, "gpt-4o-mini") == mini  # another model: not changed
        new = plugins.get_profile("openai")
        assert new.default_api_base == old.default_api_base
        assert new.api_key_variables == old.api_key_variables
        assert new.models["gpt-4o"].message_overhead == old.models["gpt-4o"].message_overhead
        assert new.models["gpt-4o-mini"] == old.models["gpt-4o-mini"]
        assert sorted(new.models) == sorted(old.models)


def test_a_price_changed_by_a_merge_is_read_at_once_by_the_cost_calculator():
    with restored_default_registrar() as default:
        default.provider(
            "zz-test",
            "zz.models:Chat",
            function="model",
            profile=ProviderProfile(
                "zz-test", models={"zz-1": ModelProfile(prompt_price=1.0, completion_price=1.0)}
            ),
        )
        assert CostCalculator.get_pricing("zz-1") == {"prompt": 1.0, "completion": 1.0}
        default.profile("zz-test", models={"zz-1": {"prompt_price": 3.0}})
        assert CostCalculator.get_pricing("zz-1") == {"prompt": 3.0, "completion": 1.0}


# -- what merges ---------------------------------------------------------------------------------------------------


def test_a_model_profile_keeps_the_price_and_the_overhead_it_does_not_give(registrar):
    registrar.profile("acme", models={"acme-1": ModelProfile(tokenizer="words")})
    entry = registrar.get_profile("acme").models["acme-1"]
    assert entry.tokenizer == "words"
    assert (entry.prompt_price, entry.completion_price, entry.message_overhead) == (1.0, 2.0, 4)


def test_a_model_profile_cannot_set_a_field_back_to_its_default_but_a_mapping_can(registrar):
    registrar.profile("acme", models={"acme-1": ModelProfile(message_overhead=0)})
    assert (
        registrar.get_profile("acme").models["acme-1"].message_overhead == 4
    )  # the default: "not given"
    registrar.profile("acme", models={"acme-1": {"message_overhead": 0}})
    assert registrar.get_profile("acme").models["acme-1"].message_overhead == 0


def test_a_mapping_of_fields_changes_only_those_fields(registrar):
    registrar.profile("acme", models={"acme-2": {"prompt_price": 9.0}})
    entry = registrar.get_profile("acme").models["acme-2"]
    assert (entry.prompt_price, entry.completion_price) == (9.0, 6.0)


def test_a_model_the_profile_does_not_have_is_added(registrar):
    registrar.profile("acme", models={"acme-3": {"prompt_price": 0.5, "completion_price": 1.5}})
    models = registrar.get_profile("acme").models
    assert models["acme-3"].prompt_price == 0.5
    assert sorted(models) == ["acme-1", "acme-2", "acme-3"]
    registrar.profile("acme", models={"acme-4": ModelProfile(tokenizer="words")})
    assert registrar.get_profile("acme").models["acme-4"].tokenizer == "words"


def test_the_info_of_a_change_is_merged_key_by_key(registrar):
    registrar.profile("acme", models={"acme-1": {"info": {"tools": True}}})
    assert dict(registrar.get_profile("acme").models["acme-1"].info) == {
        "vision": True,
        "tools": True,
    }
    registrar.profile("acme", models={"acme-1": ModelProfile(info={"vision": False})})
    assert dict(registrar.get_profile("acme").models["acme-1"].info) == {
        "vision": False,
        "tools": True,
    }


def test_a_scalar_field_of_the_provider_changes_and_the_rest_stays(registrar):
    registrar.profile(
        "acme",
        default_api_base="https://eu.acme.example/v1",
        api_key_variables=("ACME_KEY", "ACME_TOKEN"),
        region=RegionRule(("ACME_REGION",)),
        client_settings={"api_base": "endpoint"},
        model_is_deployment=True,
    )
    profile = registrar.get_profile("acme")
    assert profile.default_api_base == "https://eu.acme.example/v1"
    assert profile.api_key_variables == ("ACME_KEY", "ACME_TOKEN")
    assert profile.region == RegionRule(("ACME_REGION",))
    assert dict(profile.client_settings) == {"api_base": "endpoint"}
    assert profile.model_is_deployment is True
    assert profile.name == "acme"
    assert sorted(profile.models) == ["acme-1", "acme-2"]  # the models are not touched


def test_a_string_is_read_as_one_variable_as_the_constructor_reads_it(registrar):
    registrar.profile("acme", api_key_variables="OTHER_KEY")
    assert registrar.get_profile("acme").api_key_variables == ("OTHER_KEY",)


# -- what it refuses -----------------------------------------------------------------------------------------------


def test_a_name_that_is_not_a_field_is_a_type_error_and_nothing_changes(registrar):
    held = registrar.get_profile("acme")
    for bad in ({"nme": "x"}, {"name": "other"}, {"models_": 1}):
        with pytest.raises(TypeError, match="not a field that can change"):
            registrar.profile("acme", **bad)
    with pytest.raises(TypeError, match="not a field of ModelProfile"):
        registrar.profile("acme", models={"acme-1": {"tokenzer": "words"}})
    with pytest.raises(TypeError, match="a ModelProfile or a mapping"):
        registrar.profile("acme", models={"acme-1": "words"})  # type: ignore[dict-item]
    assert registrar.get_profile("acme") is held


def test_a_provider_with_no_profile_is_an_error_that_lists_the_providers_that_have_one(registrar):
    registrar.provider("plain", "plain.models:Chat", function="model")
    with pytest.raises(ConfigurationError) as caught:
        registrar.profile("plain", models={"m": {"prompt_price": 1.0}})
    assert "'plain' has no profile" in str(caught.value)
    assert caught.value.details["known"] == ["acme"]
    with pytest.raises(ConfigurationError):
        registrar.profile("unknown")


def test_an_invalid_value_is_refused_and_nothing_changes(registrar):
    held = registrar.get_profile("acme")
    token = registrar.profiles_token()
    with pytest.raises(ValidationError):
        registrar.profile("acme", models={"acme-1": {"prompt_price": -1.0}})
    with pytest.raises(ValidationError):
        registrar.profile("acme", api_key_variables="")
    assert registrar.get_profile("acme") is held
    assert registrar.profiles_token() is token


# -- the profile is frozen -----------------------------------------------------------------------------------------


def test_the_old_profile_is_not_mutated_and_a_new_one_is_published(registrar):
    old = registrar.get_profile("acme")
    old_entry = old.models["acme-1"]
    registrar.profile("acme", models={"acme-1": {"prompt_price": 7.0}}, default_api_base="x")
    new = registrar.get_profile("acme")
    assert new is not old
    assert old.models["acme-1"] is old_entry and old_entry.prompt_price == 1.0
    assert old.default_api_base == "https://api.acme.example/v1"
    assert new.models["acme-1"].prompt_price == 7.0
    assert (
        new.models["acme-2"] is old.models["acme-2"]
    )  # an entry that was not given is the same object


def test_nothing_given_changes_nothing_and_the_token_stays(registrar):
    held = registrar.get_profile("acme")
    token = registrar.profiles_token()
    registrar.profile("acme")
    registrar.profile("acme", models={})
    assert registrar.get_profile("acme") is held
    assert registrar.profiles_token() is token


def test_a_write_changes_the_profiles_token(registrar):
    token = registrar.profiles_token()
    registrar.profile("acme", models={"acme-1": {"prompt_price": 2.0}})
    assert registrar.profiles_token() is not token


# -- the handle and the Port ---------------------------------------------------------------------------------------


def test_the_handle_forwards_to_its_registrar(registrar):
    plugins = Plugins(registrar=registrar)
    plugins.profile("acme", models={"acme-1": ModelProfile(tokenizer="words")})
    assert plugins.get_profile("acme").models["acme-1"].tokenizer == "words"
    assert registrar.get_profile("acme").models["acme-1"].tokenizer == "words"


def test_the_registrar_has_the_call_of_the_port():
    assert isinstance(Registrar(), RegistrarInterface)
    assert "profile" in dir(RegistrarInterface)


# -- threads -------------------------------------------------------------------------------------------------------


def test_threads_that_merge_different_models_of_one_provider_all_win(registrar):
    count = 16
    barrier = threading.Barrier(count)
    errors: list[BaseException] = []

    def merge(index: int) -> None:
        try:
            barrier.wait()
            registrar.profile("acme", models={f"m{index}": {"prompt_price": float(index)}})
        except BaseException as error:  # noqa: BLE001
            errors.append(error)

    threads = [threading.Thread(target=merge, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    models = registrar.get_profile("acme").models
    assert all(models[f"m{i}"].prompt_price == float(i) for i in range(count))  # none was lost
    assert {"acme-1", "acme-2"} <= set(models)
