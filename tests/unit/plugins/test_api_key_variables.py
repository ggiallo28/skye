"""One home for the API-key variables: the ``api_key_variables`` of the profile of a provider (task
6.3, Requirements 60.3 and 11.6)."""

from __future__ import annotations

import pytest

import skye
from skye.auth.plugins import openai_compatible as oc
from skye.base.api_keys import api_key_from_environment, api_key_variable, api_key_variables
from skye.base.exceptions import ConfigurationError
from skye.base.plugins import Registrar
from skye.base.profile import ProviderProfile
from skye.models import OpenAICompatibleProvider
from skye.models.utilities.anthropic_compatible.provider import AnthropicCompatibleProvider
from skye.router.config_models import ModelTarget
from skye.router.model_router import expand_route_shorthand
from skye.router.skye_file import _target
from tests.unit.plugins.registrar_state import restored_default_registrar

# The names of the provider-standard variables (D18): the profiles must keep them.
BUILTIN_VARIABLES = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "azure": "AZURE_OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "cohere": "COHERE_API_KEY",
}


@pytest.fixture
def private() -> Registrar:
    registrar = Registrar()
    registrar.provider(
        "acme",
        object,
        function="model",
        profile=ProviderProfile("acme", api_key_variables=("ACME_FIRST_KEY", "ACME_SECOND_KEY")),
    )
    registrar.provider("keyless", object, function="model", profile=ProviderProfile("keyless"))
    return registrar


# -- the helper
# --------------------------------------------------------------------------------------------------


def test_the_variables_are_the_ones_of_the_profile_in_order(private):
    assert api_key_variables("acme", private) == ("ACME_FIRST_KEY", "ACME_SECOND_KEY")
    assert api_key_variable("acme", private) == "ACME_FIRST_KEY"


def test_a_provider_with_no_profile_or_no_variable_has_none(private):
    assert api_key_variables("nobody", private) == ()
    assert api_key_variable("nobody", private) is None
    assert api_key_variables("keyless", private) == ()
    assert api_key_from_environment("keyless", {"ANY_KEY": "x"}, private) is None


def test_the_first_variable_that_is_set_wins_and_an_empty_one_is_skipped(private):
    both = {"ACME_FIRST_KEY": "one", "ACME_SECOND_KEY": "two"}
    assert api_key_from_environment("acme", both, private) == "one"
    assert (
        api_key_from_environment("acme", {"ACME_FIRST_KEY": "", "ACME_SECOND_KEY": "two"}, private)
        == "two"
    )
    assert api_key_from_environment("acme", {"ACME_SECOND_KEY": "two"}, private) == "two"
    assert api_key_from_environment("acme", {}, private) is None


def test_the_environment_is_read_at_each_call(private, monkeypatch):
    monkeypatch.delenv("ACME_FIRST_KEY", raising=False)
    assert api_key_from_environment("acme", registrar=private) is None
    monkeypatch.setenv("ACME_FIRST_KEY", "late")
    assert api_key_from_environment("acme", registrar=private) == "late"


@pytest.mark.parametrize(("provider", "variable"), sorted(BUILTIN_VARIABLES.items()))
def test_every_built_in_provider_names_its_standard_variable(provider, variable):
    assert api_key_variables(provider) == (variable,)
    assert api_key_from_environment(provider, {variable: "secret"}) == "secret"


# -- the tables are gone
# --------------------------------------------------------------------------------------------------


def test_the_tables_of_auth_and_the_router_no_longer_exist():
    from skye.router import skye_file

    assert not hasattr(oc, "STANDARD_ENV_VARS")
    assert not hasattr(skye_file, "API_KEY_VARIABLES")
    with pytest.raises(ImportError):
        from skye.auth.plugins.openai_compatible.source import STANDARD_ENV_VARS  # noqa: F401


# -- auth
# --------------------------------------------------------------------------------------------------


def test_auth_reads_the_variable_of_the_profile(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ConfigurationError) as caught:
        oc.openai_authenticator()
    assert "OPENAI_API_KEY" in str(caught.value)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-1")
    assert oc.openai_authenticator().apply("POST", "u", {}) == {"Authorization": "Bearer sk-1"}


def test_a_provider_with_a_profile_is_known_by_name_to_auth(monkeypatch):
    with restored_default_registrar() as registrar:
        registrar.provider(
            "acme-auth",
            object,
            function="model",
            profile=ProviderProfile("acme-auth", api_key_variables=("ACME_AUTH_KEY",)),
        )
        monkeypatch.setenv("ACME_AUTH_KEY", "ak")
        assert oc.api_key_authenticator("acme-auth").apply("POST", "u", {}) == {
            "Authorization": "Bearer ak"
        }
    with pytest.raises(ConfigurationError):
        oc.api_key_authenticator("acme-auth")  # restored: the provider is gone


# -- a plugin provider: no change in auth or the router
# -------------------------------------------------------------------------------------


def test_a_plugin_provider_gets_its_key_from_its_profile(monkeypatch):
    plugins = skye.Plugins()
    with restored_default_registrar():
        plugins.provider(
            "acme-openai",
            OpenAICompatibleProvider,
            profile=ProviderProfile(
                "acme-openai",
                api_key_variables=("ACME_OPENAI_API_KEY",),
                default_api_base="https://api.acme.example/v1",
            ),
        )
        monkeypatch.setenv("ACME_OPENAI_API_KEY", "from-env")
        assert skye.provider("acme-openai").api_key == "from-env"  # type: ignore[attr-defined]
        assert skye.provider("acme-openai", api_key="given").api_key == "given"  # type: ignore[attr-defined]
        monkeypatch.delenv("ACME_OPENAI_API_KEY")
        with pytest.raises(ConfigurationError) as caught:
            skye.provider("acme-openai")
        assert "ACME_OPENAI_API_KEY" in str(caught.value)
        assert caught.value.details["variable"] == "ACME_OPENAI_API_KEY"


def test_a_plugin_provider_of_the_anthropic_format_gets_its_key_too(monkeypatch):
    plugins = skye.Plugins()
    with restored_default_registrar():
        plugins.provider(
            "acme-claude",
            AnthropicCompatibleProvider,
            profile=ProviderProfile(
                "acme-claude",
                api_key_variables=("ACME_CLAUDE_KEY",),
                default_api_base="https://claude.acme.example",
            ),
        )
        monkeypatch.setenv("ACME_CLAUDE_KEY", "ck")
        assert skye.provider("acme-claude", api_base="https://claude.acme.example").api_key == "ck"  # type: ignore[attr-defined]


def test_a_built_in_provider_still_reads_its_own_variable(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "ko")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ka")
    assert skye.provider("openai").api_key == "ko"  # type: ignore[attr-defined]
    assert skye.provider("anthropic").api_key == "ka"  # type: ignore[attr-defined]


# -- the router
# --------------------------------------------------------------------------------------------------


def test_the_router_reads_the_variable_of_the_profile_of_a_target(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ra")
    target = ModelTarget(model="claude-3-5-haiku", provider="anthropic")
    assert _target(target)["api_key"] == "${ANTHROPIC_API_KEY}"
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert "api_key" not in _target(target)


def test_the_router_shorthand_takes_the_key_from_the_profile(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "rk")
    routes, _ = expand_route_shorthand({"smart": ["openai/gpt-4o"]})
    assert routes[0].targets[0].api_key == "rk"
    with restored_default_registrar() as registrar:
        registrar.provider(
            "acme-route",
            object,
            function="model",
            profile=ProviderProfile("acme-route", api_key_variables=("ACME_ROUTE_KEY",)),
        )
        monkeypatch.setenv("ACME_ROUTE_KEY", "ark")
        routes, _ = expand_route_shorthand({"x": ["acme-route/m1"]})
        assert routes[0].targets[0].api_key == "ark"
