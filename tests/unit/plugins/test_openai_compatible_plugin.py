"""An OpenAI-compatible endpoint is a plugin with no class of its own: ``OpenAICompatibleProvider`` plus a ``ProviderProfile`` (plugins:5.3, Requirement 59.9).

The provider is registered on a private ``Registrar`` with the profile of a made-up vendor, Acme, and called offline: ``rest.post_json`` is patched, so
nothing leaves the machine. What the test fixes today, so that a later task that moves more of the profile into the adapter changes it on purpose:

* the registrar returns the class itself, and the profile it holds is the one that was given;
* the call goes to ``{default_api_base}/chat/completions`` with the bearer key; the class does not yet read ``default_api_base`` or the key variable
  from the profile (plugins:6.3 and 6.4), so the caller passes both, as the profile declares them;
* the cost comes from the profile: a dated name finds its family, and a model with no price, or not in the profile, has an unknown cost (59.10);
* one provider name has one profile: a second, different profile raises unless ``replace=True`` (59.8).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

import skye.base.plugins as plugins_module
from skye.base.completion import CompleteRequest, CompleteResponse, TokenUsage
from skye.base.exceptions import ConfigurationError, ProviderError
from skye.base.messages import UserMessage
from skye.base.plugins import Registrar
from skye.base.profile import ModelProfile, ProviderProfile, find_model_profile
from skye.models import CostCalculator, OpenAICompatibleProvider
from skye.models.registry import ProviderRegistry
from skye.models.utilities.rest import JsonObject

POST = "skye.models.utilities.rest.post_json"
URL = "https://api.acme.example/v1/chat/completions"

PROFILE = ProviderProfile(
    "acme",
    ("ACME_API_KEY",),
    default_api_base="https://api.acme.example/v1",
    models={
        "acme-small": ModelProfile(prompt_price=0.10, completion_price=0.40),
        "acme-large": ModelProfile(prompt_price=2.00, completion_price=8.00),
        "acme-preview": ModelProfile(),  # in the profile, with no price yet
    },
)


def _response(model: str = "acme-large") -> JsonObject:
    return JsonObject(
        {
            "id": "chatcmpl-acme-1",
            "model": model,
            "created": 1234567890,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "Bonjour"},
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
    )


@pytest.fixture
def registrar() -> Registrar:
    """A private registrar with Acme registered the way a plugin does it: the class and a profile, no subclass."""
    fresh = Registrar()
    fresh.provider("acme", OpenAICompatibleProvider, profile=PROFILE, function="model")
    return fresh


@pytest.fixture
def default_registrar(registrar: Registrar, monkeypatch: pytest.MonkeyPatch) -> Registrar:
    """Make ``registrar`` the default of the process for the test, so ``CostCalculator`` and ``skye.provider`` read it; restored afterwards."""
    monkeypatch.setattr(plugins_module, "_default", registrar)
    return registrar


def _client(registrar: Registrar, api_key: str | None = "acme-secret") -> Any:
    """The client a user gets from what the registrar holds: the class, with the endpoint and key the profile declares."""
    provider_class = registrar.get("provider", "acme", "model")
    profile = registrar.get_profile("acme")
    return provider_class(api_key=api_key, api_base=profile.default_api_base)


# -- registered with no class of its own ------------------------------------------------------------------------


def test_the_registrar_holds_the_class_itself_and_the_profile(registrar):
    assert (
        registrar.get("provider", "acme", "model") is OpenAICompatibleProvider
    )  # no subclass: Requirement 59.9
    assert registrar.get_profile("acme") is PROFILE
    assert registrar.names("provider", "model") == ["acme"]


# -- the call, offline ------------------------------------------------------------------------------------------


def test_complete_goes_to_the_endpoint_of_the_profile_with_the_bearer_key(registrar):
    with patch(POST, return_value=_response()) as post:
        result = _client(registrar).complete(
            CompleteRequest(messages=[UserMessage(content="Hello")], model="acme-large")
        )

    post.assert_called_once()
    assert post.call_args.args[0] == URL
    assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer acme-secret"}
    payload = post.call_args.args[1]
    assert payload["model"] == "acme-large"
    assert payload["messages"] == [{"role": "user", "content": "Hello"}]

    assert isinstance(result, CompleteResponse)
    assert result.content == "Bonjour"
    assert result.model == "acme-large"
    assert (
        result.usage.prompt_tokens,
        result.usage.completion_tokens,
        result.usage.total_tokens,
    ) == (10, 5, 15)


def test_a_trailing_slash_in_the_endpoint_is_harmless(registrar):
    provider_class = registrar.get("provider", "acme", "model")
    with patch(POST, return_value=_response()) as post:
        provider_class(api_key="k", api_base="https://api.acme.example/v1/").complete(
            CompleteRequest(messages=[UserMessage(content="Hi")], model="acme-small")
        )
    assert post.call_args.args[0] == URL


def test_the_class_does_not_read_the_endpoint_or_the_key_variable_from_the_profile_yet(
    registrar, monkeypatch
):
    """True today: the caller passes both, and a missing ``api_base`` surfaces as a ``ProviderError`` at the call (the ``ConfigurationError`` is its cause).

    Plugins 6.3 and 6.4 move the key variable and the endpoint into the profile; update this test then.
    """
    monkeypatch.setenv("ACME_API_KEY", "from-the-environment")
    provider_class = registrar.get("provider", "acme", "model")
    with pytest.raises(ConfigurationError, match="No API key"):
        provider_class(
            api_base="https://api.acme.example/v1"
        )  # the variable of the profile is not read
    with (
        patch(POST, return_value=_response()),
        pytest.raises(ProviderError, match="api_base is required"),
    ):
        provider_class(api_key="k").complete(
            CompleteRequest(messages=[UserMessage(content="Hi")], model="acme-small")
        )


# -- the cost comes from the profile ----------------------------------------------------------------------------


def test_the_cost_is_priced_from_the_profile(default_registrar):
    usage = TokenUsage(prompt_tokens=1_000_000, completion_tokens=500_000, total_tokens=1_500_000)
    assert CostCalculator.pricing_for("acme-large") == {"prompt": 2.0, "completion": 8.0}
    assert CostCalculator.calculate_cost("acme-large", usage) == pytest.approx(2.0 + 4.0)
    assert CostCalculator.calculate_cost("acme-small", usage) == pytest.approx(0.10 + 0.20)


def test_a_dated_name_finds_its_family(default_registrar):
    assert CostCalculator.pricing_for("acme-large-2026-01-15") == {"prompt": 2.0, "completion": 8.0}
    assert find_model_profile(PROFILE, "acme-large-2026-01-15") is PROFILE.models["acme-large"]
    assert find_model_profile(PROFILE, "acme-largest") is None  # "est" is not a date or a version


def test_a_model_with_no_price_or_not_in_the_profile_has_an_unknown_cost(default_registrar):
    usage = TokenUsage(prompt_tokens=1000, completion_tokens=1000, total_tokens=2000)
    for model in ("acme-preview", "acme-not-listed"):
        assert CostCalculator.pricing_for(model) is None, (
            model
        )  # unknown, not zero (Requirement 59.10)
        assert CostCalculator.calculate_cost(model, usage) == 0.0, (
            model
        )  # as for any model the table does not know


def test_a_provider_without_a_profile_has_no_price():
    bare = Registrar()
    bare.provider(
        "acme", OpenAICompatibleProvider, function="model"
    )  # registered with no profile: still works as a provider
    assert bare.get_profile("acme") is None
    assert bare.get("provider", "acme", "model") is OpenAICompatibleProvider


# -- one provider name, one profile -----------------------------------------------------------------------------

OTHER = ProviderProfile("acme", ("ACME_KEY",), default_api_base="https://api.acme.example/v2")


def test_the_same_name_registered_again_is_refused_unless_replaced(registrar):
    with pytest.raises(ConfigurationError, match="already registered"):
        registrar.provider("acme", OpenAICompatibleProvider, profile=PROFILE, function="model")
    assert registrar.get_profile("acme") is PROFILE

    registrar.provider("acme", OpenAICompatibleProvider, profile=OTHER, replace=True, function="model")
    assert registrar.get_profile("acme") is OTHER
    assert registrar.get("provider", "acme", "model") is OpenAICompatibleProvider


def test_a_second_different_profile_for_the_same_provider_name_is_refused(registrar):
    """The embedding side of the same vendor may not bring a different profile (59.8); the same one is accepted."""
    with pytest.raises(ConfigurationError, match="different profile") as caught:
        registrar.provider(
            "acme", "skye.models.plugins.openai:OpenAIEmbeddingProvider", profile=OTHER, function="embedding"
        )
    assert caught.value.details["name"] == "acme"
    assert registrar.names("provider", "embedding") == []  # nothing was registered
    assert registrar.get_profile("acme") is PROFILE

    registrar.provider(
        "acme", "skye.models.plugins.openai:OpenAIEmbeddingProvider", profile=PROFILE, function="embedding"
    )
    assert registrar.names("provider", "embedding") == ["acme"]


# -- by name, through skye.provider -----------------------------------------------------------------------------


@pytest.mark.skipif(
    hasattr(ProviderRegistry, "_model_providers"),
    reason="waits for plugins:5.2: ProviderRegistry still keeps a table of its own and does not read the registrar",
)
def test_skye_provider_reaches_a_plugin_registered_on_the_registrar(default_registrar):
    import skye

    client = skye.provider("acme", api_key="acme-secret", api_base="https://api.acme.example/v1")
    assert isinstance(client, OpenAICompatibleProvider)
    with patch(POST, return_value=_response()) as post:
        client.complete(
            CompleteRequest(messages=[UserMessage(content="Hello")], model="acme-large")
        )
    assert post.call_args.args[0] == URL
