"""The credential-source registry: register a custom source and resolve it by name."""

import pytest

from skye.auth import registry
from skye.auth.plugins.openai_compatible.source import BearerAuth
from skye.base.exceptions import ConfigurationError
from skye.base.interfaces.authentication import AuthenticationInterface
from skye.base.plugins import Registrar


class VaultAuth:
    def __init__(self, token="t"):
        self._token = token

    def apply(self, method, url, headers, body=b""):
        return {**headers, "X-Vault-Token": self._token}


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    """Each test works on a registrar of its own, so a source it registers never reaches the default one."""
    fresh = Registrar()
    monkeypatch.setattr(registry, "get_registrar", lambda: fresh)
    return fresh


def test_a_custom_source_is_registered_and_resolved_by_name():
    registry.register_credential_source("vault", VaultAuth)
    assert "vault" in registry.list_credential_sources()
    source = registry.resolve_credential_source("vault", token="abc")
    assert isinstance(source, AuthenticationInterface)
    assert source.apply("GET", "u", {}) == {"X-Vault-Token": "abc"}


def test_a_name_in_use_needs_replace_and_unregister_removes_it():
    registry.register_credential_source("vault", VaultAuth)
    with pytest.raises(ConfigurationError, match="already registered"):
        registry.register_credential_source("vault", VaultAuth)
    registry.register_credential_source("vault", lambda **kw: "replaced", replace=True)
    assert registry.resolve_credential_source("vault") == "replaced"
    registry.unregister_credential_source("vault")
    with pytest.raises(ConfigurationError, match="No credential source named 'vault'"):
        registry.resolve_credential_source("vault")


def test_a_built_in_name_cannot_be_taken_by_accident():
    with pytest.raises(ConfigurationError):
        registry.register_credential_source("google", VaultAuth)


def test_bad_registrations_are_rejected():
    with pytest.raises(ConfigurationError):
        registry.register_credential_source("", VaultAuth)
    with pytest.raises(ConfigurationError):
        registry.register_credential_source("x", "not callable")  # type: ignore[arg-type]


def test_the_built_in_sources_resolve_lazily():
    names = registry.list_credential_sources()
    for expected in ("openai", "google", "azure", "aws", "aws-secrets-manager", "azure-key-vault"):
        assert expected in names
    assert isinstance(registry.resolve_credential_source("openai", api_key="k"), BearerAuth)


def test_the_unknown_name_error_lists_what_exists():
    with pytest.raises(ConfigurationError) as caught:
        registry.resolve_credential_source("nope")
    assert "openai" in str(caught.value)


# -- the registry is a view of the registrar (plugins:7.2, Requirements 56.6 and 56.7) --------------------------


def test_there_is_no_table_of_its_own():
    assert not hasattr(registry, "BUILTIN_SOURCES") and not hasattr(registry, "_custom")


def test_the_built_ins_are_registered_by_text_and_import_nothing(isolated):
    import sys

    from skye.auth import plugins as _plugin

    for module in ("skye.auth.plugins.oauth2.source", "skye.auth.plugins.secrets.source"):
        sys.modules.pop(module, None)
    _plugin.register(isolated)
    assert isolated.names("credential_source") == sorted(_plugin.SOURCES)
    assert "skye.auth.plugins.oauth2.source" not in sys.modules and "skye.auth.plugins.secrets.source" not in sys.modules


def test_the_built_in_plugin_can_run_twice_and_does_not_overwrite_a_replacement(isolated):
    from skye.auth import plugins as _plugin

    isolated.credential_source("google", lambda **kw: "mine")
    _plugin.register(isolated)
    _plugin.register(isolated)
    assert registry.resolve_credential_source("google") == "mine"


def test_a_source_registered_through_the_registrar_is_seen_by_the_registry(isolated):
    isolated.credential_source("from-a-plugin", lambda **kw: ("plugin", kw))
    assert "from-a-plugin" in registry.list_credential_sources()
    assert registry.resolve_credential_source("from-a-plugin", a=1) == ("plugin", {"a": 1})


def test_a_source_registered_in_the_registry_is_seen_by_the_registrar(isolated):
    registry.register_credential_source("vault", VaultAuth)
    assert isolated.get("credential_source", "vault") is VaultAuth


def test_a_replaced_built_in_name_goes_back_to_the_built_in_on_unregister():
    registry.register_credential_source("openai", lambda **kw: "replaced", replace=True)
    assert registry.resolve_credential_source("openai") == "replaced"
    registry.unregister_credential_source("openai")
    assert isinstance(registry.resolve_credential_source("openai", api_key="k"), BearerAuth)


def test_unregistering_a_built_in_or_an_unknown_name_changes_nothing():
    before = registry.list_credential_sources()
    registry.unregister_credential_source("google")
    registry.unregister_credential_source("never-registered")
    assert registry.list_credential_sources() == before


def test_every_call_of_the_registry_of_today_works_as_before():
    """One case per public function: register, replace, unregister, list, resolve, and the three errors."""
    registry.register_credential_source("a", lambda **kw: ("a", kw))
    assert registry.resolve_credential_source("a", x=1) == ("a", {"x": 1})
    assert "a" in registry.list_credential_sources()
    with pytest.raises(ConfigurationError, match="already registered"):
        registry.register_credential_source("a", VaultAuth)
    registry.register_credential_source("a", VaultAuth, replace=True)
    assert isinstance(registry.resolve_credential_source("a"), VaultAuth)
    registry.unregister_credential_source("a")
    with pytest.raises(ConfigurationError) as caught:
        registry.resolve_credential_source("a")
    assert caught.value.details == {"name": "a"} and "known:" in str(caught.value)
