"""OAuth2 flows against a fake token endpoint, and the API-key strategies."""

import pytest

from skye.auth.plugins.openai_compatible import source as oc
from skye.auth.plugins.oauth2.source import ClientCredentialsAuth, TokenExchangeAuth, file_token, token_request
from skye.base.exceptions import ConfigurationError, ProviderError


def test_client_credentials_fetches_once_and_caches(server):
    server.respond(lambda seen: (200, {"access_token": "AT", "expires_in": 3600}))
    auth = ClientCredentialsAuth(server.url + "/token", "id", "shh", scope="s1 s2", audience="aud")
    assert auth.apply("GET", "u", {})["Authorization"] == "Bearer AT"
    assert auth.apply("GET", "u", {})["Authorization"] == "Bearer AT"
    assert len(server.seen) == 1
    form = server.seen[0].form()
    assert (
        form["grant_type"] == "client_credentials"
        and form["scope"] == "s1 s2"
        and form["audience"] == "aud"
    )
    assert "shh" not in repr(auth)


def test_client_credentials_refresh_fetches_again(server):
    tokens = iter(["A1", "A2"])
    server.respond(lambda seen: (200, {"access_token": next(tokens), "expires_in": 3600}))
    auth = ClientCredentialsAuth(server.url + "/token", "id", "shh")
    auth.apply("GET", "u", {})
    auth.refresh()
    assert auth.apply("GET", "u", {})["Authorization"] == "Bearer A2"


def test_client_credentials_need_all_three_values():
    with pytest.raises(ConfigurationError):
        ClientCredentialsAuth("", "id", "shh")


def test_token_exchange_reads_the_subject_token_each_time(server, tmp_path):
    path = tmp_path / "subject"
    path.write_text("subject-1\n")
    server.respond(
        lambda seen: (200, {"access_token": "X-" + seen.form()["subject_token"], "expires_in": 0})
    )
    auth = TokenExchangeAuth(
        server.url + "/sts", file_token(str(path)), audience="//aud", scope="sc"
    )
    assert auth.apply("GET", "u", {})["Authorization"] == "Bearer X-subject-1"
    path.write_text("subject-2")
    assert (
        auth.apply("GET", "u", {})["Authorization"] == "Bearer X-subject-2"
    )  # expires_in 0: not cached
    form = server.seen[0].form()
    assert form["grant_type"].endswith("token-exchange") and form["audience"] == "//aud"


def test_a_missing_token_file_names_the_path_only():
    with pytest.raises(ConfigurationError) as caught:
        file_token("/no/such/token")()
    assert "/no/such/token" in str(caught.value)


def test_a_bad_response_is_a_provider_error_without_the_request_body(server):
    server.respond(lambda seen: (200, {"nope": 1}))
    with pytest.raises(ProviderError) as caught:
        token_request(server.url + "/t", {"client_secret": "shh"})
    assert "shh" not in str(caught.value)


def test_an_http_error_is_a_provider_error_with_the_status(server):
    server.respond(lambda seen: (401, {"error": "invalid_client"}))
    with pytest.raises(ProviderError) as caught:
        token_request(server.url + "/t", {})
    assert caught.value.details["status_code"] == 401


@pytest.fixture
def no_keys(monkeypatch):
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "COHERE_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def test_bearer_and_api_key_strategies(no_keys, monkeypatch):
    assert oc.openai_authenticator("k").apply("POST", "u", {"A": "b"}) == {
        "A": "b",
        "Authorization": "Bearer k",
    }
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ak")
    assert oc.anthropic_authenticator().apply("POST", "u", {}) == {"x-api-key": "ak"}
    monkeypatch.setenv("COHERE_API_KEY", "ck")
    assert oc.cohere_authenticator().apply("POST", "u", {}) == {"Authorization": "Bearer ck"}
    # A provider that has a profile with `api_key_variables` is known by name (here a plugin provider, the one of the profile).
    from skye.base.plugins import Registrar
    from skye.base.profile import ProviderProfile

    registrar = Registrar()
    registrar.provider(
        "groq-6-3", object, function="model", profile=ProviderProfile("groq-6-3", api_key_variables=("GROQ_API_KEY",))
    )
    monkeypatch.setenv("GROQ_API_KEY", "gk")
    monkeypatch.setattr("skye.base.api_keys.get_registrar", lambda: registrar)
    assert oc.api_key_authenticator("groq-6-3").apply("POST", "u", {}) == {"Authorization": "Bearer gk"}


def test_the_input_headers_are_not_mutated_and_the_key_is_not_in_repr(no_keys):
    headers = {"A": "b"}
    auth = oc.openai_authenticator("sk-secret")
    auth.apply("POST", "u", headers)
    assert headers == {"A": "b"} and "sk-secret" not in repr(auth)


def test_a_missing_key_names_the_variable_not_a_value(no_keys, monkeypatch):
    with pytest.raises(ConfigurationError) as caught:
        oc.openai_authenticator()
    assert "OPENAI_API_KEY" in str(caught.value)
    with pytest.raises(ConfigurationError):
        oc.api_key_authenticator("nobody")


def test_the_variable_can_be_changed_for_a_compatible_server(no_keys, monkeypatch):
    monkeypatch.setenv("MY_SERVER_KEY", "mk")
    assert (
        oc.openai_authenticator(env_var="MY_SERVER_KEY").apply("POST", "u", {})["Authorization"]
        == "Bearer mk"
    )
