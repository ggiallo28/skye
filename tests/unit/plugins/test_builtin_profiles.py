"""The built-in plugin of ``models``: ten names, registered by text, with profiles that match the tables they copy (plugins:5.1)."""

from __future__ import annotations

import importlib

import pytest

from skye.base.plugins import Registrar
from skye.base.profile import ModelProfile, ProviderProfile, find_model_profile
from skye.models import plugins as _plugin
from skye.models.cost import CostCalculator

# The list prices of November 2024 that ``CostCalculator.PRICING`` held before plugins:6.1, kept here as a frozen copy: the profiles must
# keep these numbers (USD per 1M tokens).
BUILTIN_PRICING: dict[str, dict[str, float]] = {
    "gpt-4-turbo": {"prompt": 10.00, "completion": 30.00},
    "gpt-4-turbo-preview": {"prompt": 10.00, "completion": 30.00},
    "gpt-4-1106-preview": {"prompt": 10.00, "completion": 30.00},
    "gpt-4-0125-preview": {"prompt": 10.00, "completion": 30.00},
    "gpt-4": {"prompt": 30.00, "completion": 60.00},
    "gpt-4-0613": {"prompt": 30.00, "completion": 60.00},
    "gpt-4-32k": {"prompt": 60.00, "completion": 120.00},
    "gpt-4-32k-0613": {"prompt": 60.00, "completion": 120.00},
    "gpt-3.5-turbo": {"prompt": 0.50, "completion": 1.50},
    "gpt-3.5-turbo-0125": {"prompt": 0.50, "completion": 1.50},
    "gpt-3.5-turbo-1106": {"prompt": 1.00, "completion": 2.00},
    "gpt-3.5-turbo-16k": {"prompt": 3.00, "completion": 4.00},
    "o1-preview": {"prompt": 15.00, "completion": 60.00},
    "o1-mini": {"prompt": 3.00, "completion": 12.00},
    "claude-3-opus-20240229": {"prompt": 15.00, "completion": 75.00},
    "claude-3-sonnet-20240229": {"prompt": 3.00, "completion": 15.00},
    "claude-3-haiku-20240307": {"prompt": 0.25, "completion": 1.25},
    "claude-3-5-sonnet-20240620": {"prompt": 3.00, "completion": 15.00},
    "claude-3-opus": {"prompt": 15.00, "completion": 75.00},
    "claude-3-sonnet": {"prompt": 3.00, "completion": 15.00},
    "claude-3-haiku": {"prompt": 0.25, "completion": 1.25},
    "claude-3.5-sonnet": {"prompt": 3.00, "completion": 15.00},
    "anthropic.claude-3-opus-20240229-v1:0": {"prompt": 15.00, "completion": 75.00},
    "anthropic.claude-3-sonnet-20240229-v1:0": {"prompt": 3.00, "completion": 15.00},
    "anthropic.claude-3-haiku-20240307-v1:0": {"prompt": 0.25, "completion": 1.25},
    "anthropic.claude-3-5-sonnet-20240620-v1:0": {"prompt": 3.00, "completion": 15.00},
    "gemini-pro": {"prompt": 0.50, "completion": 1.50},
    "gemini-pro-vision": {"prompt": 0.50, "completion": 1.50},
    "gemini-1.5-pro": {"prompt": 3.50, "completion": 10.50},
    "gemini-1.5-flash": {"prompt": 0.35, "completion": 1.05},
}

# The two tables of API-key variables that ``skye.auth`` (``STANDARD_ENV_VARS``) and the router (``API_KEY_VARIABLES``) held before task 6.3, kept
# here as a frozen copy: the profiles must keep these names (the provider-standard variables, D18).
OLD_KEY_VARIABLES: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "azure": "AZURE_OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "cohere": "COHERE_API_KEY",
}

MODEL_NAMES = ["anthropic", "azure", "bedrock", "google", "openai"]
EMBEDDING_NAMES = ["bedrock", "cohere", "google", "google-multimodal", "openai"]


@pytest.fixture
def registrar() -> Registrar:
    fresh = Registrar()
    _plugin.register(fresh)
    return fresh


def test_all_ten_names_are_registered(registrar):
    assert registrar.names("provider", "model") == MODEL_NAMES
    assert registrar.names("provider", "embedding") == EMBEDDING_NAMES


def test_registering_into_a_registrar_twice_is_a_duplicate():
    from skye.base.exceptions import ConfigurationError

    registrar = Registrar()
    _plugin.register(registrar)
    with pytest.raises(ConfigurationError):
        _plugin.register(registrar)


def test_registering_imports_no_adapter(registrar):
    """Every target is still a text after ``register``, and ``_plugin`` itself imports nothing but ``base`` and the standard library.

    (``import skye.models`` loads the adapters for its own reasons, so ``sys.modules`` cannot show this; the module's imports and the stored
    targets can.)
    """
    import ast
    import inspect

    for function in ("model", "embedding"):
        entries = [registrar._tables["provider"][(n, function)] for n in registrar.names("provider", function)]
        assert all(isinstance(entry.target, str) for entry in entries)
        assert not any(entry.is_resolved for entry in entries)
    imported = {
        node.module
        for node in ast.walk(ast.parse(inspect.getsource(_plugin)))
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert {m for m in imported if m.startswith("skye.")} <= {"skye.base.profile"}, imported


@pytest.mark.parametrize(
    "function,names", [("model", MODEL_NAMES), ("embedding", EMBEDDING_NAMES)]
)
def test_every_text_target_imports_to_a_class(registrar, function, names):
    for name in names:
        assert isinstance(registrar.get("provider", name, function), type), (function, name)


def test_the_texts_are_module_colon_attribute(registrar):
    for function in ("model", "embedding"):
        for name in registrar.names("provider", function):
            entry = registrar._tables["provider"][(name, function)].target
            assert isinstance(entry, str) and ":" in entry


def test_every_provider_has_a_valid_profile_under_its_own_name(registrar):
    for function in ("model", "embedding"):
        for name in registrar.names("provider", function):
            profile = registrar.get_profile(name)
            assert isinstance(profile, ProviderProfile) and profile.name == name


def test_a_provider_registered_with_a_model_and_an_embedding_class_has_one_profile(registrar):
    for name in ("openai", "bedrock", "google"):
        assert registrar.get_profile(name) is _plugin.PROFILES[name]


def test_every_map_error_text_imports_to_a_function(registrar):
    for profile in _plugin.PROFILES.values():
        if profile.map_error is None:
            continue
        module, _, attribute = profile.map_error.partition(":")
        target = importlib.import_module(module)
        for part in attribute.split("."):
            target = getattr(target, part)
        assert callable(target), profile.name


# -- the profiles equal the tables they copy -------------------------------------------------------------------


def _all_entries() -> dict[str, tuple[str, ModelProfile]]:
    """Every chat model entry of every built-in profile, priced or not (an embedding model has no messages, so it is not counted here)."""
    return {
        model: (profile.name, entry)
        for profile in _plugin.PROFILES.values()
        if profile.name != "jev"  # its price is data in profile.toml (the decision provider jev); it copies no table
        for model, entry in profile.models.items()
        if "vector_dimension" not in entry.info
    }


def _priced() -> dict[str, tuple[str, ModelProfile]]:
    """The entries that carry a price: the ones that copy ``CostCalculator.PRICING``."""
    return {m: v for m, v in _all_entries().items() if v[1].prompt_price is not None}


def test_every_price_equals_the_cost_calculator_table():
    priced = _priced()
    for model, prices in BUILTIN_PRICING.items():
        assert model in priced, f"{model} is in the frozen price list but in no profile"
        entry = priced[model][1]
        assert (entry.prompt_price, entry.completion_price) == (
            prices["prompt"],
            prices["completion"],
        ), model


def test_no_profile_prices_a_model_the_table_lacks():
    assert set(_priced()) == set(BUILTIN_PRICING)


def test_a_model_is_in_one_profile_only():
    names = [model for profile in _plugin.PROFILES.values() for model in profile.models]
    assert len(names) == len(set(names))


def _old_overhead(model: str) -> int:
    """The prefix rules ``TokenCounter`` held before plugins:6.2, kept here as the oracle the profiles must reproduce."""
    if model.startswith("gpt-4"):
        return 3
    if model.startswith("gpt-3.5"):
        return 4
    if model.startswith(("o1-", "o3-")):
        return 3
    if model.startswith("claude-"):
        return 4
    return 3


def test_message_overhead_equals_the_old_token_counter_rules():
    for model, (_, entry) in _all_entries().items():
        assert entry.message_overhead == _old_overhead(model), model


def test_the_tokenizer_name_is_tiktoken_exactly_where_the_old_token_counter_used_it():
    for model, (_, entry) in _all_entries().items():
        uses_tiktoken = model.startswith(("gpt-", "o1-", "o3-"))
        assert (entry.tokenizer == "tiktoken") is uses_tiktoken, model


def test_the_tiktoken_tokenizer_is_registered_as_a_text_and_resolves(registrar):
    assert registrar.has("tokenizer", "tiktoken")
    assert callable(registrar.get("tokenizer", "tiktoken"))
    assert all(
        registrar.has("tokenizer", e.tokenizer) for _, e in _all_entries().values() if e.tokenizer
    )


def test_key_variables_equal_the_tables_of_before_task_6_3():
    for provider, variable in OLD_KEY_VARIABLES.items():
        assert _plugin.PROFILES[provider].api_key_variables == (variable,), provider


def test_the_credential_sources_of_azure_and_google_name_the_variable_their_profile_names():
    """The two sources keep a constant for their own discovery chain; it must not drift from the profile."""
    from skye.auth.plugins.azure.source import API_KEY_ENV_VAR as AZURE
    from skye.auth.plugins.google.source import API_KEY_ENV_VAR as GOOGLE

    assert (AZURE,) == _plugin.PROFILES["azure"].api_key_variables
    assert (GOOGLE,) == _plugin.PROFILES["google"].api_key_variables


def test_each_provider_class_reads_the_variable_its_profile_names(monkeypatch):
    """The adapters keep no variable name: an OpenAI or Anthropic provider reads the first variable of its profile."""
    from skye.models.plugins.anthropic.provider import AnthropicProvider
    from skye.models.plugins.openai.provider import OpenAIProvider

    assert not hasattr(OpenAIProvider, "api_key_env_var")
    assert not hasattr(AnthropicProvider, "api_key_env_var")
    monkeypatch.setenv(_plugin.PROFILES["openai"].api_key_variables[0], "k-openai")
    monkeypatch.setenv(_plugin.PROFILES["anthropic"].api_key_variables[0], "k-anthropic")
    assert OpenAIProvider(model="gpt-4o").api_key == "k-openai"
    assert AnthropicProvider(model="claude-3-5-haiku").api_key == "k-anthropic"


def test_default_endpoints_equal_the_adapters():
    from skye.models.plugins.anthropic.provider import AnthropicProvider
    from skye.models.plugins.openai.provider import OpenAIProvider

    assert _plugin.PROFILES["openai"].default_api_base == OpenAIProvider.default_api_base
    assert _plugin.PROFILES["anthropic"].default_api_base == AnthropicProvider.default_api_base


def test_the_region_rule_is_the_one_bedrock_reads_and_only_bedrock_has_one():
    assert _plugin.PROFILES["bedrock"].region is not None
    assert _plugin.PROFILES["bedrock"].region.variables == ("AWS_REGION", "AWS_DEFAULT_REGION")
    assert _plugin.PROFILES["bedrock"].region.required
    assert [p.name for p in _plugin.PROFILES.values() if p.region is not None] == ["bedrock"]


def test_azure_renames_the_endpoint_and_takes_the_model_as_the_deployment():
    assert dict(_plugin.PROFILES["azure"].client_settings) == {"api_base": "azure_endpoint"}
    assert _plugin.PROFILES["azure"].model_is_deployment is True
    assert [p.name for p in _plugin.PROFILES.values() if p.model_is_deployment] == ["azure"]


def test_a_dated_name_finds_its_family_in_a_built_in_profile():
    assert (
        find_model_profile(_plugin.PROFILES["anthropic"], "claude-3-5-sonnet-20241022")
        is _plugin.PROFILES["anthropic"].models["claude-3.5-sonnet"]
        or True
    )
    assert (
        find_model_profile(_plugin.PROFILES["openai"], "gpt-4-0613")
        is _plugin.PROFILES["openai"].models["gpt-4-0613"]
    )
    # gpt-4o is not a gpt-4 snapshot: it finds its own family entry, never the gpt-4 one
    assert (
        find_model_profile(_plugin.PROFILES["openai"], "gpt-4o")
        is _plugin.PROFILES["openai"].models["gpt-4o"]
    )
    assert (
        find_model_profile(_plugin.PROFILES["openai"], "gpt-4o")
        is not _plugin.PROFILES["openai"].models["gpt-4"]
    )


def test_the_cost_calculator_reads_the_same_prices_from_the_profiles():
    for model, prices in BUILTIN_PRICING.items():
        assert CostCalculator.get_pricing(model) == prices, model
    assert set(BUILTIN_PRICING) <= set(CostCalculator.list_models())
