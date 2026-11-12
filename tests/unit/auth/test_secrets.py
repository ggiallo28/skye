"""The native secret managers against fake endpoints."""

import base64
import json

import pytest

from skye.auth import registry
from skye.auth.plugins.secrets import source as secrets
from skye.auth.cache import CachedBearerAuth
from skye.base.exceptions import ProviderError


@pytest.fixture(autouse=True)
def aws_keys(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKSECRET")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "shh")
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)


def test_aws_secrets_manager_signs_and_reads_the_secret_string(server):
    server.respond(lambda seen: (200, {"SecretString": "s3cr3t"}))
    manager = secrets.AwsSecretsManager("eu-west-1", endpoint=server.url + "/")
    assert manager.get("prod/db", version_stage="AWSCURRENT") == "s3cr3t"
    seen = server.seen[0]
    assert seen.headers["x-amz-target"] == "secretsmanager.GetSecretValue"
    assert (
        "AKSECRET" in seen.headers["authorization"]
        and "/secretsmanager/" in seen.headers["authorization"]
    )
    assert seen.json() == {"SecretId": "prod/db", "VersionStage": "AWSCURRENT"}
    assert "s3cr3t" not in repr(manager)


def test_aws_secrets_manager_binary_and_empty(server):
    server.respond(lambda seen: (200, {"SecretBinary": base64.b64encode(b"bin").decode()}))
    assert secrets.AwsSecretsManager("us-east-1", endpoint=server.url + "/").get("x") == "bin"
    server.respond(lambda seen: (200, {}))
    with pytest.raises(ProviderError, match="no value"):
        secrets.AwsSecretsManager("us-east-1", endpoint=server.url + "/").get("x")


def test_aws_parameter_store(server):
    server.respond(lambda seen: (200, {"Parameter": {"Value": "param-value"}}))
    store = secrets.AwsParameterStore("us-east-1", endpoint=server.url + "/")
    assert store.get("/app/key") == "param-value"
    seen = server.seen[0]
    assert seen.headers["x-amz-target"] == "AmazonSSM.GetParameter" and seen.json() == {
        "Name": "/app/key",
        "WithDecryption": True,
    }


def test_azure_key_vault_uses_a_bearer_token(server):
    server.respond(lambda seen: (200, {"value": "kv-secret"}))
    vault = secrets.AzureKeyVault(
        server.url, authenticator=CachedBearerAuth("k", lambda: ("kv-token", 100))
    )
    assert vault.get("db password", version="v1") == "kv-secret"
    seen = server.seen[0]
    assert seen.headers["authorization"] == "Bearer kv-token"
    assert seen.path == "/secrets/db%20password/v1?api-version=7.4"


def test_google_secret_manager_decodes_the_payload(server):
    server.respond(
        lambda seen: (200, {"payload": {"data": base64.b64encode(b"g-secret").decode()}})
    )
    manager = secrets.GoogleSecretManager(
        "proj", authenticator=CachedBearerAuth("k", lambda: ("g-token", 100)), endpoint=server.url
    )
    assert manager.get("name") == "g-secret"
    seen = server.seen[0]
    assert (
        seen.path == "/v1/projects/proj/secrets/name/versions/latest:access"
        and seen.headers["authorization"] == "Bearer g-token"
    )


def test_a_401_refreshes_the_credential_once_and_retries_once(server):
    tokens = iter(["old", "new", "newer"])
    server.respond(
        lambda seen: (
            (200, {"value": "ok"}) if seen.headers["authorization"] == "Bearer new" else (401, {})
        )
    )
    vault = secrets.AzureKeyVault(
        server.url, authenticator=CachedBearerAuth("k", lambda: (next(tokens), 1000))
    )
    assert vault.get("n") == "ok"
    assert [s.headers["authorization"] for s in server.seen] == ["Bearer old", "Bearer new"]


def test_a_second_401_is_raised_and_never_leaks_the_secret(server):
    server.respond(lambda seen: (401, {"message": "denied"}))
    vault = secrets.AzureKeyVault(
        server.url, authenticator=CachedBearerAuth("k", lambda: ("tok", 1000))
    )
    with pytest.raises(ProviderError) as caught:
        vault.get("n")
    assert caught.value.details["status_code"] == 401 and len(server.seen) == 2


def test_the_secret_sources_are_reachable_through_the_registry(server):
    server.respond(lambda seen: (200, {"Parameter": {"Value": "via-registry"}}))
    store = registry.resolve_credential_source(
        "aws-ssm", region="us-east-1", endpoint=server.url + "/"
    )
    assert store.get("/p") == "via-registry"
    assert json.loads(server.seen[0].body)["Name"] == "/p"
