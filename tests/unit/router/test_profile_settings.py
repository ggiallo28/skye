"""The router applies the profile of a target's provider: renamed settings and a model that is a deployment (Requirement 60.4, plugins:6.4).

The router names no provider. What Azure needed (its endpoint called ``azure_endpoint``, the model taken as a deployment name) is in the profile of
``azure``, and any provider registered with a profile of the same kind gets the same treatment.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from skye.base.interfaces.registry import set_provider_registry
from skye.base.plugins import Registrar
from skye.base.profile import ProviderProfile, apply_client_settings
from skye.router import ModelRouter, ModelTarget, RouteConfig
from tests.unit.router.fakes import FakeModel


class Builds:
    """A provider registry that records what the router asks it to build, and answers with a fake model."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get_model_provider(self, name: str, **config: Any) -> FakeModel:
        self.calls.append((name, config))
        return FakeModel(str(config.get("model", "?")))


@pytest.fixture
def builds() -> Iterator[Builds]:
    registry = Builds()
    set_provider_registry(registry)
    yield registry
    set_provider_registry(None)


def build(provider: str, **fields: Any) -> dict[str, Any]:
    """The configuration the router passes to the provider of a target."""
    return fields


def route(provider: str, model: str = "m1", **fields: Any) -> list[RouteConfig]:
    return [
        RouteConfig(alias="main", targets=[ModelTarget(model=model, provider=provider, **fields)])
    ]


# -- the generic function ----------------------------------------------------------------------------------------


def test_no_profile_means_no_change():
    config = {"model": "m", "api_base": "https://x"}
    assert apply_client_settings(None, "m", config) == config


def test_a_setting_is_renamed_as_the_profile_says():
    profile = ProviderProfile("acme", client_settings={"api_base": "endpoint"})
    assert apply_client_settings(
        profile, "m", {"model": "m", "api_base": "https://x", "api_key": "k"}
    ) == {
        "model": "m",
        "endpoint": "https://x",
        "api_key": "k",
    }


def test_a_setting_the_target_does_not_have_is_not_invented():
    profile = ProviderProfile("acme", client_settings={"api_base": "endpoint"})
    assert apply_client_settings(profile, "m", {"model": "m"}) == {"model": "m"}


def test_the_model_is_added_as_the_deployment_name():
    profile = ProviderProfile("acme", model_is_deployment=True)
    assert apply_client_settings(profile, "gpt-prod", {"model": "gpt-prod"}) == {
        "model": "gpt-prod",
        "deployment_name": "gpt-prod",
    }


def test_a_deployment_name_the_target_gave_is_kept():
    profile = ProviderProfile("acme", model_is_deployment=True)
    assert (
        apply_client_settings(profile, "m", {"model": "m", "deployment_name": "mine"})[
            "deployment_name"
        ]
        == "mine"
    )


def test_the_deployment_setting_can_be_renamed_too():
    profile = ProviderProfile(
        "acme", model_is_deployment=True, client_settings={"deployment_name": "deployment"}
    )
    assert apply_client_settings(profile, "m", {"model": "m"}) == {"model": "m", "deployment": "m"}


def test_renames_do_not_chain():
    profile = ProviderProfile("acme", client_settings={"a": "b", "b": "c"})
    assert apply_client_settings(profile, "m", {"a": 1, "b": 2}) == {"b": 1, "c": 2}


def test_the_given_configuration_is_not_modified():
    profile = ProviderProfile(
        "acme", model_is_deployment=True, client_settings={"api_base": "endpoint"}
    )
    config = {"model": "m", "api_base": "https://x"}
    apply_client_settings(profile, "m", config)
    assert config == {"model": "m", "api_base": "https://x"}


# -- the router: the built-in Azure keeps behaving as before -----------------------------------------------------


def test_an_azure_target_is_built_as_before(builds: Builds):
    ModelRouter(
        routes=route(
            "azure",
            model="my-deployment",
            api_base="https://r.openai.azure.com",
            api_key="k",
            api_version="2024-06-01",
        )
    )
    ((name, config),) = builds.calls
    assert name == "azure"
    assert config == {
        "model": "my-deployment",
        "api_key": "k",
        "azure_endpoint": "https://r.openai.azure.com",
        "api_version": "2024-06-01",
        "deployment_name": "my-deployment",
    }


def test_the_options_of_an_azure_target_still_win(builds: Builds):
    ModelRouter(
        routes=route(
            "azure",
            model="d",
            api_base="https://r",
            options={"deployment_name": "other", "azure_endpoint": "https://o"},
        )
    )
    ((_, config),) = builds.calls
    assert (
        config["deployment_name"] == "other"
        and config["azure_endpoint"] == "https://o"
        and "api_base" not in config
    )


def test_a_provider_with_no_special_settings_is_built_as_before(builds: Builds):
    ModelRouter(
        routes=route("openai", model="gpt-4o", api_base="https://api.example/v1", api_key="k")
    )
    ((_, config),) = builds.calls
    assert config == {"model": "gpt-4o", "api_key": "k", "api_base": "https://api.example/v1"}


# -- the router: a provider of a plugin gets the same treatment ---------------------------------------------------


def test_a_plugin_provider_with_its_own_setting_names_and_deployments(
    builds: Builds, monkeypatch: pytest.MonkeyPatch
):
    registrar = Registrar()
    registrar.provider(
        "acme-cloud",
        object,
        profile=ProviderProfile(
            "acme-cloud",
            client_settings={"api_base": "host", "api_key": "token"},
            model_is_deployment=True,
        ), function="model",
    )
    monkeypatch.setattr("skye.router.model_router.get_registrar", lambda: registrar)
    ModelRouter(
        routes=route(
            "acme-cloud", model="prod-1", api_base="https://acme.example", api_key="secret"
        )
    )
    ((name, config),) = builds.calls
    assert name == "acme-cloud"
    assert config == {
        "model": "prod-1",
        "token": "secret",
        "host": "https://acme.example",
        "deployment_name": "prod-1",
    }


def test_a_provider_without_a_profile_is_untouched(builds: Builds, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("skye.router.model_router.get_registrar", lambda: Registrar())
    ModelRouter(routes=route("acme-bare", model="m1", api_base="https://x"))
    ((_, config),) = builds.calls
    assert config == {"model": "m1", "api_base": "https://x"}


def test_the_router_names_no_provider_in_its_code():
    """No provider name is compared in ``router/model_router.py`` (Requirement 60.4): the Azure branch is gone."""
    import ast
    import inspect

    import skye.router.model_router as module

    names = {"azure", "openai", "anthropic", "bedrock", "google", "cohere"}
    compared = [
        node.value
        for node in ast.walk(ast.parse(inspect.getsource(module)))
        if isinstance(node, ast.Compare)
        for comparator in [node.left, *node.comparators]
        if isinstance(comparator, ast.Constant) and isinstance(comparator.value, str)
        for node in [comparator]
        if node.value in names
    ]
    assert compared == []
