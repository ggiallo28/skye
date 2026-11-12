"""The AWS region comes through the rule of the profile (task 6.6, Requirements 60.6, 59.5, 59.6, O63 part 2 option A)."""

from __future__ import annotations

from typing import Any

import pytest

from skye.auth.plugins.aws import sts
from skye.auth.plugins.aws.source import CredentialProvider
from skye.base.exceptions import ConfigurationError
from skye.base.plugins import Registrar
from skye.base.profile import ProviderProfile, RegionRule
from skye.base.regions import region_for
from tests.unit.plugins.registrar_state import restored_default_registrar

VARIABLES = ("AWS_REGION", "AWS_DEFAULT_REGION")


@pytest.fixture(autouse=True)
def no_region_in_the_environment(monkeypatch: pytest.MonkeyPatch):
    for name in VARIABLES:
        monkeypatch.delenv(name, raising=False)
    with restored_default_registrar():
        yield


# --- the order of the rule ---


class Authenticator:
    region = "from-authenticator"


def test_the_region_passed_comes_first():
    env = {"AWS_REGION": "env"}
    assert region_for("bedrock", "passed", Authenticator(), environ=env) == "passed"


def test_the_authenticator_comes_before_the_variables():
    assert (
        region_for("bedrock", None, Authenticator(), environ={"AWS_REGION": "env"})
        == "from-authenticator"
    )


def test_the_variables_are_read_in_the_order_of_the_profile():
    both = {"AWS_REGION": "first", "AWS_DEFAULT_REGION": "second"}
    assert region_for("bedrock", environ=both) == "first"
    assert region_for("bedrock", environ={"AWS_DEFAULT_REGION": "second"}) == "second"


def test_a_required_region_that_is_missing_names_the_variables_and_has_no_default():
    with pytest.raises(ConfigurationError) as caught:
        region_for("bedrock", environ={})
    assert "AWS_REGION" in str(caught.value) and "AWS_DEFAULT_REGION" in str(caught.value)
    assert caught.value.details["variables"] == list(VARIABLES)


def test_required_false_returns_none_and_required_true_raises_for_the_same_rule():
    assert region_for("bedrock", required=False, environ={}) is None
    with pytest.raises(ConfigurationError):
        region_for("bedrock", required=True, environ={})


def test_a_provider_with_no_region_rule_is_an_error_only_when_required():
    registrar = Registrar(scan=False, builtin_plugins=())
    assert region_for("nobody", registrar=registrar, environ={}) is None
    with pytest.raises(ConfigurationError, match="no region rule"):
        region_for("nobody", required=True, registrar=registrar, environ={})


def test_a_provider_of_a_plugin_brings_its_own_variables():
    registrar = Registrar(scan=False, builtin_plugins=())
    registrar.provider(
        "acme",
        object,
        function="model",
        profile=ProviderProfile("acme", region=RegionRule(("ACME_REGION",))),
    )
    assert region_for("acme", registrar=registrar, environ={"ACME_REGION": "mars-1"}) == "mars-1"
    with pytest.raises(ConfigurationError, match="ACME_REGION"):
        region_for("acme", registrar=registrar, environ={})


# --- the places that need a region ---


def test_assume_role_without_a_region_raises_before_any_request(monkeypatch: pytest.MonkeyPatch):
    sent: list[Any] = []
    monkeypatch.setattr(sts.http, "send_bytes", lambda *a, **k: sent.append(a) or b"")
    with pytest.raises(ConfigurationError, match="AWS_REGION"):
        sts.assume_role("arn", access_key="a", secret_key="b")
    assert sent == []


def test_assume_role_signs_with_the_region_of_the_environment_of_the_provider(
    monkeypatch: pytest.MonkeyPatch,
):
    seen: list[str] = []

    def fake_assume(role_arn: str, **kwargs: Any) -> Any:
        seen.append(kwargs["region"])
        return ("k", "s", "t", None)

    from skye.auth.plugins.aws import source

    monkeypatch.setattr(source.sts, "assume_role", fake_assume)
    provider = CredentialProvider(
        access_key="a", secret_key="b", role_arn="arn", env={"AWS_DEFAULT_REGION": "eu-north-1"}
    )
    provider._assume(provider._explicit, "arn", "skye", None)  # type: ignore[arg-type]
    assert seen == ["eu-north-1"]


def test_a_credential_provider_with_no_role_needs_no_region():
    provider = CredentialProvider(access_key="a", secret_key="b")
    assert provider.get().access_key == "a"


def test_web_identity_with_an_endpoint_needs_no_region(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []
    monkeypatch.setattr(
        sts.http,
        "send_bytes",
        lambda url, *a, **k: calls.append(url) or b"<AssumeRoleWithWebIdentityResponse/>",
    )
    with pytest.raises(Exception) as caught:  # the empty answer is not a valid STS response
        sts.assume_role_with_web_identity("arn", "token", endpoint="https://sts.example/")
    assert not isinstance(caught.value, ConfigurationError)
    assert calls == ["https://sts.example/"]
