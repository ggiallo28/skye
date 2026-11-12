"""Microsoft Entra ID for Azure OpenAI against a fake login endpoint, and the Azure CLI cache."""

import json

import pytest

from skye.auth.plugins.azure import source as az
from skye.auth.errors import LoginRequiredError
from skye.base.exceptions import ConfigurationError

from .conftest import jwt_parts


def _token(seen):
    return 200, {"access_token": "AZ-AT", "expires_in": "3600"}


def test_api_key_header_and_missing_key(monkeypatch):
    monkeypatch.delenv(az.API_KEY_ENV_VAR, raising=False)
    assert az.AzureApiKeyAuth("k").apply("POST", "u", {"A": "b"}) == {"A": "b", "api-key": "k"}
    with pytest.raises(ConfigurationError, match=az.API_KEY_ENV_VAR):
        az.AzureApiKeyAuth()


def test_client_secret(server):
    server.respond(_token)
    auth = az.AzureClientSecretAuth("tenant", "client", "shh", authority=server.url)
    assert auth.apply("POST", "u", {})["Authorization"] == "Bearer AZ-AT"
    seen = server.seen[0]
    assert seen.path == "/tenant/oauth2/v2.0/token"
    assert seen.form()["scope"] == az.OPENAI_SCOPE and seen.form()["client_secret"] == "shh"
    assert "shh" not in repr(auth)
    with pytest.raises(ConfigurationError, match="client_secret"):
        az.AzureClientSecretAuth("tenant", "client", "")


def test_certificate_sends_a_signed_client_assertion(server, rsa_pem):
    server.respond(_token)
    pem = rsa_pem["pkcs8"] + "-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----\n"
    auth = az.AzureCertificateAuth("tenant", "client", pem, authority=server.url, clock=lambda: 100)
    assert auth.apply("POST", "u", {})["Authorization"] == "Bearer AZ-AT"
    form = server.seen[0].form()
    assert form["client_assertion_type"] == az.ASSERTION_TYPE
    header, payload = jwt_parts(form["client_assertion"])
    assert header["alg"] == "RS256" and "x5t#S256" in header
    assert (
        payload["iss"] == payload["sub"] == "client"
        and payload["aud"] == server.url + "/tenant/oauth2/v2.0/token"
    )


def test_federated_token_file(server, tmp_path):
    (tmp_path / "fed").write_text("federated-jwt\n")
    server.respond(_token)
    auth = az.AzureFederatedTokenAuth(
        "tenant", "client", str(tmp_path / "fed"), authority=server.url
    )
    assert auth.apply("POST", "u", {})["Authorization"] == "Bearer AZ-AT"
    assert server.seen[0].form()["client_assertion"] == "federated-jwt"


def test_managed_identity_on_app_service_and_on_a_vm(server):
    server.respond(_token)
    app = az.AzureManagedIdentityAuth("cid", endpoint=server.url + "/msi", identity_header="hdr")
    assert app.apply("GET", "u", {})["Authorization"] == "Bearer AZ-AT"
    seen = server.seen[0]
    assert seen.headers["x-identity-header"] == "hdr" and "client_id=cid" in seen.path
    assert (
        "resource=https%3A%2F%2Fcognitiveservices.azure.com" in seen.path
        and "api-version=2019-08-01" in seen.path
    )
    vm = az.AzureManagedIdentityAuth(endpoint=server.url + "/imds")
    vm.apply("GET", "u", {})
    assert (
        server.seen[1].headers["metadata"] == "true"
        and "api-version=2018-02-01" in server.seen[1].path
    )


def _cache(tmp_path, *, expires_on, target="https://cognitiveservices.azure.com/.default"):
    path = tmp_path / "msal_token_cache.json"
    path.write_text(
        json.dumps(
            {
                "AccessToken": {
                    "k": {"secret": "cli-token", "target": target, "expires_on": str(expires_on)}
                }
            }
        )
    )
    return path


def test_azure_cli_cache_is_read_and_never_refreshed(tmp_path):
    path = _cache(tmp_path, expires_on=10_000)
    auth = az.AzureCliCacheAuth(path=path, clock=lambda: 1000)
    assert auth.apply("POST", "u", {})["Authorization"] == "Bearer cli-token"
    assert "cli-token" not in repr(auth)
    with pytest.raises(LoginRequiredError, match="az login"):
        az.AzureCliCacheAuth(path=path, clock=lambda: 20_000).token()
    with pytest.raises(LoginRequiredError, match="az login"):
        az.AzureCliCacheAuth(
            path=_cache(tmp_path, expires_on=10_000, target="https://other/.default"),
            clock=lambda: 1,
        ).token()
    with pytest.raises(LoginRequiredError, match="missing"):
        az.AzureCliCacheAuth(path=tmp_path / "none.json").token()


def test_resolve_order(tmp_path, monkeypatch):
    for name in (
        "AZURE_OPENAI_API_KEY",
        "AZURE_TENANT_ID",
        "AZURE_CLIENT_ID",
        "AZURE_CLIENT_SECRET",
        "AZURE_FEDERATED_TOKEN_FILE",
        "AZURE_CLIENT_CERTIFICATE_PATH",
        "IDENTITY_ENDPOINT",
        "IDENTITY_HEADER",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AZURE_CONFIG_DIR", str(tmp_path / "azure"))
    with pytest.raises(az.AzureAuthError, match="az login"):
        az.resolve_azure_auth()
    (tmp_path / "azure").mkdir()
    _cache(tmp_path / "azure", expires_on=1)
    assert isinstance(az.resolve_azure_auth(), az.AzureCliCacheAuth)
    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://x")
    monkeypatch.setenv("IDENTITY_HEADER", "h")
    assert isinstance(az.resolve_azure_auth(), az.AzureManagedIdentityAuth)
    monkeypatch.setenv("AZURE_TENANT_ID", "t")
    monkeypatch.setenv("AZURE_CLIENT_ID", "c")
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "s")
    assert isinstance(az.resolve_azure_auth(), az.AzureClientSecretAuth)
    monkeypatch.setenv("AZURE_FEDERATED_TOKEN_FILE", "/f")
    assert isinstance(az.resolve_azure_auth(), az.AzureFederatedTokenAuth)
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "key")
    assert isinstance(az.resolve_azure_auth(), az.AzureApiKeyAuth)
    assert isinstance(az.resolve_azure_auth("explicit-key"), az.AzureApiKeyAuth)
    with pytest.raises(az.AzureAuthError):
        az.resolve_azure_auth(42)
