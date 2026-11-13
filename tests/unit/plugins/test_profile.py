"""The provider profile: validation, ``find_model_profile``, ``resolve_region`` and total lookups
(plugins:3.1 to 3.4)."""

from __future__ import annotations

import dataclasses
import random
import string

import pytest

from skye.base.exceptions import ConfigurationError, ValidationError
from skye.base.profile import (
    ModelProfile,
    ProviderProfile,
    RegionRule,
    find_model_profile,
    resolve_region,
)

# -- the dataclasses (3.1)
# ---------------------------------------------------------------------------------------


def test_profiles_are_frozen():
    profile = ProviderProfile("acme", ("ACME_API_KEY",))
    with pytest.raises(dataclasses.FrozenInstanceError):
        profile.name = "other"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        ModelProfile().prompt_price = 1.0  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        RegionRule(("R",)).required = False  # type: ignore[misc]


def test_the_mappings_are_read_only_and_copied():
    source = {"gpt": ModelProfile(prompt_price=1.0)}
    settings = {"api_base": "azure_endpoint"}
    info = {"supports_structured_output": True}
    profile = ProviderProfile("acme", models=source, client_settings=settings)
    model = ModelProfile(info=info)
    source["other"] = ModelProfile()
    settings["x"] = "y"
    info["z"] = 1
    assert list(profile.models) == ["gpt"] and dict(profile.client_settings) == {
        "api_base": "azure_endpoint"
    }
    assert dict(model.info) == {"supports_structured_output": True}
    with pytest.raises(TypeError):
        profile.models["new"] = ModelProfile()  # type: ignore[index]
    with pytest.raises(TypeError):
        model.info["k"] = 1  # type: ignore[index]


def test_defaults_declare_nothing():
    profile = ProviderProfile("acme")
    assert (
        profile.api_key_variables == ()
        and profile.region is None
        and profile.default_api_base is None
    )
    assert (
        profile.model_is_deployment is False
        and dict(profile.models) == {}
        and profile.map_error is None
    )
    model = ModelProfile()
    assert (
        model.prompt_price is None
        and model.completion_price is None
        and model.tokenizer is None
        and model.message_overhead == 0
    )


def test_equal_profiles_compare_equal():
    def make():
        return ProviderProfile("acme", ("K",), models={"m": ModelProfile(1.0, 2.0)})

    assert make() == make()
    assert make() != ProviderProfile("acme", ("OTHER",), models={"m": ModelProfile(1.0, 2.0)})


def test_a_list_of_variables_becomes_a_tuple():
    assert ProviderProfile("acme", ["A", "B"]).api_key_variables == ("A", "B")  # type: ignore[arg-type]
    assert RegionRule(["A", "B"]).variables == ("A", "B")  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["prompt_price", "completion_price"])
@pytest.mark.parametrize("bad", [-0.01, -1, float("nan"), "1", True])
def test_a_price_must_be_zero_or_more(field, bad):
    with pytest.raises(ValidationError):
        ModelProfile(**{field: bad})


@pytest.mark.parametrize("good", [0, 0.0, 0.15, 75, None])
def test_a_price_of_zero_or_more_or_none_is_valid(good):
    assert ModelProfile(prompt_price=good).prompt_price == good


@pytest.mark.parametrize("bad", [-1, 1.5, "3", True])
def test_the_overhead_must_be_a_non_negative_integer(bad):
    with pytest.raises(ValidationError):
        ModelProfile(message_overhead=bad)


@pytest.mark.parametrize("bad", ["", 3])
def test_a_tokenizer_is_none_or_a_name(bad):
    with pytest.raises(ValidationError):
        ModelProfile(tokenizer=bad)


def test_a_profile_needs_a_name_names_for_variables_a_region_rule_and_model_profiles():
    for kwargs in (
        {"name": ""},
        {"name": "a", "api_key_variables": ("",)},
        {"name": "a", "region": "us-east-1"},
        {"name": "a", "models": {"m": 1.0}},
        {"name": "a", "models": {"": ModelProfile()}},
    ):
        with pytest.raises(ValidationError):
            ProviderProfile(**kwargs)  # type: ignore[arg-type]


def test_a_region_rule_needs_names():
    with pytest.raises(ValidationError):
        RegionRule(("",))


# -- find_model_profile (3.2)
# ------------------------------------------------------------------------------------


def _profile(*names: str) -> ProviderProfile:
    return ProviderProfile(
        "p",
        models={name: ModelProfile(prompt_price=float(i)) for i, name in enumerate(names, start=1)},
    )


def test_the_exact_name_wins_over_a_family():
    profile = _profile("gpt-4o", "gpt-4o-2024-08-06")
    assert find_model_profile(profile, "gpt-4o-2024-08-06") is profile.models["gpt-4o-2024-08-06"]
    assert find_model_profile(profile, "gpt-4o") is profile.models["gpt-4o"]


def test_gpt_4o_never_matches_gpt_4():
    profile = _profile("gpt-4")
    assert find_model_profile(profile, "gpt-4o") is None
    assert find_model_profile(profile, "gpt-4o-2024-08-06") is None
    assert find_model_profile(profile, "gpt-4-turbo") is None


@pytest.mark.parametrize(
    "model",
    [
        "gpt-4o-2024-08-06",  # a dated name
        "gpt-4o-20240806",
        "gpt-4o-0613",
        "gpt-4o@001",
        "gpt-4o-v2",
        "gpt-4o-latest",
    ],
)
def test_dated_and_versioned_names_find_their_family(model):
    profile = _profile("gpt-4o")
    assert find_model_profile(profile, model) is profile.models["gpt-4o"]


@pytest.mark.parametrize(
    "model",
    [
        "anthropic.claude-3-5-sonnet-20240620-v1:0",
        "anthropic.claude-3-5-sonnet-v2:0",
        "anthropic.claude-3-5-sonnet-20241022-v2:0",
    ],
)
def test_bedrock_versioned_names_find_their_family(model):
    profile = _profile("anthropic.claude-3-5-sonnet", "anthropic.claude-3-haiku")
    assert find_model_profile(profile, model) is profile.models["anthropic.claude-3-5-sonnet"]


def test_the_longest_registered_name_wins():
    profile = _profile("claude-3", "claude-3-5-sonnet")
    assert (
        find_model_profile(profile, "claude-3-5-sonnet-20240620")
        is profile.models["claude-3-5-sonnet"]
    )
    assert find_model_profile(profile, "claude-3-20240229") is profile.models["claude-3"]


@pytest.mark.parametrize(
    "model",
    [
        "gpt-4o-mini",
        "gpt-4o-preview",
        "gpt-4o-",
        "gpt-4o2024",
        "gpt-4o-2024-08",
        "gpt-4o--0613",
        "xgpt-4o",
        "GPT-4O",
    ],
)
def test_a_name_that_is_not_a_date_or_a_version_is_another_model(model):
    assert find_model_profile(_profile("gpt-4o"), model) is None


def test_no_profile_no_model_and_an_empty_name_find_nothing():
    assert find_model_profile(None, "gpt-4o") is None
    assert find_model_profile(ProviderProfile("p"), "gpt-4o") is None
    assert find_model_profile(_profile("gpt-4o"), "") is None


# -- resolve_region (3.3)
# ----------------------------------------------------------------------------------------


class Authenticator:
    def __init__(self, region):
        self.region = region


RULE = RegionRule(("AWS_REGION", "AWS_DEFAULT_REGION"))


def test_the_region_passed_wins_over_everything():
    env = {"AWS_REGION": "from-env"}
    assert resolve_region(RULE, "passed", Authenticator("from-auth"), env) == "passed"


def test_the_authenticators_region_wins_over_the_variables():
    assert (
        resolve_region(RULE, None, Authenticator("from-auth"), {"AWS_REGION": "from-env"})
        == "from-auth"
    )


def test_the_variables_are_read_in_order():
    assert (
        resolve_region(RULE, environ={"AWS_REGION": "first", "AWS_DEFAULT_REGION": "second"})
        == "first"
    )
    assert resolve_region(RULE, environ={"AWS_DEFAULT_REGION": "second"}) == "second"


def test_an_empty_value_counts_as_missing():
    assert (
        resolve_region(
            RULE, "", Authenticator(""), {"AWS_REGION": "", "AWS_DEFAULT_REGION": "second"}
        )
        == "second"
    )
    assert resolve_region(RULE, None, Authenticator(None), {"AWS_REGION": "env"}) == "env"


def test_an_authenticator_without_a_region_is_skipped():
    assert resolve_region(RULE, None, object(), {"AWS_REGION": "env"}) == "env"


def test_a_required_region_that_is_missing_names_the_variables_and_has_no_default():
    with pytest.raises(ConfigurationError) as caught:
        resolve_region(RULE, environ={})
    assert caught.value.details == {"variables": ["AWS_REGION", "AWS_DEFAULT_REGION"]}
    assert "AWS_REGION" in str(caught.value) and "AWS_DEFAULT_REGION" in str(caught.value)
    assert "us-east-1" not in str(caught.value)


def test_an_optional_region_that_is_missing_is_none():
    assert resolve_region(RegionRule(("R",), required=False), environ={}) is None


def test_no_rule_means_no_region_unless_one_is_passed():
    assert resolve_region(None, environ={"AWS_REGION": "ignored"}) is None
    assert resolve_region(None, "passed") == "passed"
    assert resolve_region(None, None, Authenticator("from-auth")) == "from-auth"


def test_the_process_environment_is_the_default(monkeypatch):
    monkeypatch.setenv("PLUGINS_TEST_REGION", "from-process")
    assert resolve_region(RegionRule(("PLUGINS_TEST_REGION",))) == "from-process"
    monkeypatch.delenv("PLUGINS_TEST_REGION")
    with pytest.raises(ConfigurationError):
        resolve_region(RegionRule(("PLUGINS_TEST_REGION",)))


# -- a lookup is total (3.4, Requirement 59.10)
# ------------------------------------------------------------------
# Property tests with a seeded generator: the same 500 cases on every run, and no test dependency to
# add.

ALPHABET = string.ascii_letters + string.digits + "-.:@_/ \u00e9\u4e2d"
CASES = 500


def _names(rng: random.Random, count: int) -> list[str]:
    return ["".join(rng.choices(ALPHABET, k=rng.randint(0, 40))) for _ in range(count)]


def test_a_lookup_never_raises_for_any_model_name():
    profile = _profile("gpt-4o", "anthropic.claude-3-5-sonnet")
    for model in _names(random.Random(1), CASES):
        found = find_model_profile(profile, model)
        assert found is None or found in profile.models.values()


def test_a_lookup_without_a_profile_is_none_for_any_model_name():
    for model in _names(random.Random(2), CASES):
        assert find_model_profile(None, model) is None
        assert find_model_profile(ProviderProfile("p"), model) is None


def test_the_result_is_always_the_exact_name_or_a_prefix_of_the_model():
    rng = random.Random(3)
    for _ in range(CASES):
        names = list({n for n in _names(rng, rng.randint(1, 6)) if n})
        if not names:
            continue
        profile = ProviderProfile("p", models={n: ModelProfile() for n in names})
        base = rng.choice(names)
        model = (
            base + rng.choice(["", "-2024-08-06", "-v1:0", "@001", "x", "-0613-v2:1"])
            if rng.random() < 0.7
            else _names(rng, 1)[0]
        )
        found = find_model_profile(profile, model)
        if found is not None:
            owner = next(n for n, m in profile.models.items() if m is found)
            assert model == owner or model.startswith(owner)


def test_a_dated_or_versioned_suffix_always_finds_the_family():
    rng = random.Random(4)
    suffixes = ["-2024-08-06", "-20240806", "-0613", "-v1:0", "-v2", "@001", "-20240620-v1:0"]
    for _ in range(CASES):
        name = (
            "".join(rng.choices(string.ascii_lowercase + "-.", k=rng.randint(3, 20))).strip("-.")
            or "m"
        )
        profile = ProviderProfile("p", models={name: ModelProfile(prompt_price=1.0)})
        assert find_model_profile(profile, name + rng.choice(suffixes)) is profile.models[name]


def test_valid_cost_fields_never_raise():
    rng = random.Random(5)
    for _ in range(CASES):
        price = rng.choice([None, 0, 0.0, rng.uniform(0, 1000), rng.randint(0, 10**6)])
        ModelProfile(
            prompt_price=price, completion_price=price, message_overhead=rng.randint(0, 10**6)
        )
