"""Tests for the Google authenticators (no network)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from skye.auth.plugins.google import source as g
from skye.base.interfaces.authentication import AuthenticationInterface

ENV = (*g.TOKEN_ENV_VARS, g.API_KEY_ENV_VAR, "GOOGLE_APPLICATION_CREDENTIALS")  # noqa: E501


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    for n in ENV:
        monkeypatch.delenv(n, raising=False)
    monkeypatch.setenv("CLOUDSDK_CONFIG", str(tmp_path / "no-gcloud"))


def test_bearer_explicit_and_protocol() -> None:
    auth = g.GoogleBearerAuth("tok")
    assert isinstance(auth, AuthenticationInterface)
    src = {"A": "b"}
    out = auth.apply("POST", "https://x", src)
    assert out == {"A": "b", "Authorization": "Bearer tok"}
    assert src == {"A": "b"}


def test_bearer_callable_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    assert g.GoogleBearerAuth(lambda: "dyn").apply("GET", "u", {})["Authorization"] == "Bearer dyn"
    monkeypatch.setenv("CLOUDSDK_AUTH_ACCESS_TOKEN", "envtok")
    assert g.GoogleBearerAuth().apply("GET", "u", {})["Authorization"] == "Bearer envtok"


def test_bearer_missing_raises() -> None:
    with pytest.raises(g.GoogleAuthError):
        g.GoogleBearerAuth().apply("GET", "u", {})


def test_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    assert g.GoogleApiKeyAuth("k").apply("GET", "u", {})["x-goog-api-key"] == "k"
    monkeypatch.setenv("GOOGLE_API_KEY", "envk")
    assert g.GoogleApiKeyAuth().apply("GET", "u", {})["x-goog-api-key"] == "envk"
    monkeypatch.delenv("GOOGLE_API_KEY")
    with pytest.raises(g.GoogleAuthError):
        g.GoogleApiKeyAuth()


def _resp(token: str, expires_in: int) -> MagicMock:
    r = MagicMock()
    r.read.return_value = json.dumps({"access_token": token, "expires_in": expires_in}).encode()
    r.__enter__.return_value = r
    return r


def test_metadata_caches_until_expiry() -> None:
    now = [0.0]
    auth = g.GoogleMetadataAuth(clock=lambda: now[0])
    with patch("urllib.request.urlopen", side_effect=[_resp("t1", 3600), _resp("t2", 3600)]) as uo:
        assert auth.apply("GET", "u", {})["Authorization"] == "Bearer t1"
        now[0] = 100
        assert auth.apply("GET", "u", {})["Authorization"] == "Bearer t1"
        assert uo.call_count == 1
        req = uo.call_args[0][0]
        assert req.full_url == g.METADATA_TOKEN_URL
        assert req.get_header("Metadata-flavor") == "Google"
        now[0] = 3600  # within the skew of expiry -> refresh
        assert auth.apply("GET", "u", {})["Authorization"] == "Bearer t2"
        assert uo.call_count == 2


def test_metadata_failure() -> None:
    with patch("urllib.request.urlopen", side_effect=OSError("boom")):
        with pytest.raises(g.GoogleAuthError):
            g.GoogleMetadataAuth().token()


def test_resolve_explicit() -> None:
    custom = g.GoogleBearerAuth("x")
    assert g.resolve_google_auth(custom) is custom
    assert isinstance(g.resolve_google_auth("tok"), g.GoogleBearerAuth)
    with pytest.raises(g.GoogleAuthError):
        g.resolve_google_auth(42)


def test_resolve_env_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "k")
    assert isinstance(g.resolve_google_auth(), g.GoogleApiKeyAuth)
    monkeypatch.setenv("GOOGLE_OAUTH_ACCESS_TOKEN", "t")
    assert isinstance(g.resolve_google_auth(), g.GoogleBearerAuth)


def test_resolve_metadata_and_the_nothing_available_message(monkeypatch: pytest.MonkeyPatch) -> None:
    with patch.object(g, "_metadata_server_available", return_value=True):
        assert isinstance(g.resolve_google_auth(), g.GoogleMetadataAuth)
    with patch.object(g, "_metadata_server_available", return_value=False):
        with pytest.raises(g.GoogleAuthError, match="gcloud auth application-default login"):
            g.resolve_google_auth()
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/no/such/sa.json")
    with pytest.raises(g.GoogleAuthError, match="/no/such/sa.json"):
        g.resolve_google_auth()
