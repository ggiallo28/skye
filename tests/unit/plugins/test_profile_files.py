"""The profile data files of ``models`` and the mapping reader of ``base`` (plugins:5.1)."""

from __future__ import annotations

import tomllib
from importlib import resources

import pytest

from skye.base.exceptions import ConfigurationError, ValidationError
from skye.base.profile import ModelProfile, ProviderProfile, RegionRule, profile_from_mapping
from skye.models import plugins as _plugin

FOLDERS = list(_plugin.IMPLEMENTATIONS)
FILES = sorted(
    f"{folder}/{e.name}"
    for folder in FOLDERS
    for e in resources.files(f"skye.models.plugins.{folder}").iterdir()
    if e.name.endswith(".toml")
)


def test_every_provider_folder_has_a_profile_file():
    assert FILES == [
        "anthropic/profile.toml",
        "azure/profile.toml",
        "bedrock/profile.toml",
        "cohere/profile.toml",
        "google/profile.toml",
        "google/profile_multimodal.toml",
        "openai/profile.toml",
        "typesafe/profile.toml",
    ]


@pytest.mark.parametrize("file", FILES)
def test_each_file_loads_and_names_its_provider(file):
    folder, name = file.split("/")
    text = (
        resources.files(f"skye.models.plugins.{folder}").joinpath(name).read_text(encoding="utf-8")
    )
    profile = profile_from_mapping(tomllib.loads(text), file)
    assert _plugin.profiles()[profile.name] == profile


def test_profiles_reads_every_file():
    assert sorted(_plugin.profiles()) == [
        "anthropic",
        "azure",
        "bedrock",
        "cohere",
        "google",
        "google-multimodal",
        "jev",
        "openai",
    ]


def test_the_price_of_jev_is_the_one_typesafe_published():
    jev = _plugin.profiles()["jev"].models["jev"]
    assert (jev.prompt_price, jev.completion_price) == (
        0.042,
        0.0,
    )  # USD per million tokens; output is free


# -- the mapping reader -------------------------------------------------------------------------------------------


def test_a_minimal_profile_needs_only_a_name():
    assert profile_from_mapping({"name": "acme"}) == ProviderProfile("acme")


def test_a_full_profile_is_read_field_by_field():
    data = tomllib.loads(
        """
        name = "acme"
        api_key_variables = ["ACME_API_KEY", "ACME_KEY"]
        default_api_base = "https://api.acme.example/v1"
        model_is_deployment = true
        map_error = "acme.errors:handle"

        [region]
        variables = ["ACME_REGION"]
        required = false

        [client_settings]
        api_base = "endpoint"

        [models."acme-1"]
        prompt_price = 1.5
        completion_price = 6
        tokenizer = "words"
        message_overhead = 2

        [models."acme-1".info]
        supports_structured_output = true
        """
    )
    profile = profile_from_mapping(data)
    assert profile.api_key_variables == ("ACME_API_KEY", "ACME_KEY")
    assert profile.default_api_base == "https://api.acme.example/v1"
    assert profile.model_is_deployment is True
    assert profile.map_error == "acme.errors:handle"
    assert profile.region == RegionRule(("ACME_REGION",), required=False)
    assert dict(profile.client_settings) == {"api_base": "endpoint"}
    assert profile.models["acme-1"] == ModelProfile(
        1.5, 6, "words", 2, {"supports_structured_output": True}
    )


def test_a_region_table_is_required_by_default():
    assert profile_from_mapping({"name": "a", "region": {"variables": ["R"]}}).region == RegionRule(
        ("R",), required=True
    )


@pytest.mark.parametrize(
    "data,where",
    [
        ({"name": "a", "api_key_variable": ["K"]}, "a typo at the top"),
        ({"name": "a", "region": {"variables": ["R"], "require": True}}, "a typo in [region]"),
        ({"name": "a", "models": {"m": {"prompt_prize": 1}}}, "a typo in a model"),
    ],
)
def test_an_unknown_key_is_an_error_that_names_the_source(data, where):
    with pytest.raises(ConfigurationError) as caught:
        profile_from_mapping(data, "acme.toml")
    assert "acme.toml" in str(caught.value) and caught.value.details["unknown"], where


def test_a_negative_price_is_refused_by_the_dataclass():
    with pytest.raises(ValidationError):
        profile_from_mapping({"name": "a", "models": {"m": {"prompt_price": -1}}})


def test_a_profile_without_a_name_is_refused():
    with pytest.raises(ConfigurationError):
        profile_from_mapping({"default_api_base": "https://x"})
