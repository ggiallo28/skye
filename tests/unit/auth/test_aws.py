"""Tests for skye.auth.plugins.aws.source."""

import datetime as dt
import json
from unittest.mock import patch

import pytest

from skye.auth.plugins.aws import source as aws
from skye.base.exceptions import ConfigurationError
from skye.base.interfaces.authentication import AuthenticationInterface

URL = "https://bedrock-runtime.us-east-1.amazonaws.com/model/m/converse"


def test_sigv4_authenticator_signs():
    auth = aws.SigV4Authenticator("us-east-1", "bedrock", aws.AwsCredentials("AK", "SK", "TOK"))
    assert isinstance(auth, AuthenticationInterface)
    headers = {"Content-Type": "application/json"}
    out = auth.apply("POST", URL, headers, b"{}")
    assert out["Authorization"].startswith("AWS4-HMAC-SHA256 Credential=AK/")
    assert "bedrock" in out["Authorization"]
    assert out["x-amz-security-token"] == "TOK"
    assert headers == {"Content-Type": "application/json"}


def test_api_key_authenticator(monkeypatch):
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "envkey")
    assert aws.BedrockApiKeyAuthenticator().apply("POST", URL, {"a": "b"})["Authorization"] == "Bearer envkey"
    assert aws.BedrockApiKeyAuthenticator("x").apply("POST", URL, {})["Authorization"] == "Bearer x"
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK")
    with pytest.raises(ConfigurationError):
        aws.BedrockApiKeyAuthenticator()


def test_bedrock_authenticator_selection(monkeypatch):
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)
    assert isinstance(aws.bedrock_authenticator("us-east-1"), aws.SigV4Authenticator)
    assert isinstance(aws.bedrock_authenticator("us-east-1", api_key="k"), aws.BedrockApiKeyAuthenticator)


def test_explicit_beats_env():
    p = aws.CredentialProvider(access_key="A", secret_key="B", env={"AWS_ACCESS_KEY_ID": "E", "AWS_SECRET_ACCESS_KEY": "F"})
    assert p.get().access_key == "A"


def test_env_credentials():
    env = {"AWS_ACCESS_KEY_ID": "E", "AWS_SECRET_ACCESS_KEY": "F", "AWS_SESSION_TOKEN": "T"}
    c = aws.CredentialProvider(env=env).get()
    assert (c.access_key, c.secret_key, c.session_token) == ("E", "F", "T")


def test_profile_static_keys(tmp_path):
    f = tmp_path / "credentials"
    f.write_text("[dev]\naws_access_key_id = PK\naws_secret_access_key = PS\n")
    c = aws.CredentialProvider(profile_name="dev", env={"AWS_SHARED_CREDENTIALS_FILE": str(f)}).get()
    assert c.access_key == "PK"


def test_unresolvable_profile_error(tmp_path):
    p = aws.CredentialProvider(profile_name="sso", env={"AWS_SHARED_CREDENTIALS_FILE": str(tmp_path / "none")})
    with pytest.raises(ConfigurationError, match="SSO"):
        p.get()


def test_container_credentials_with_expiry_cache():
    future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = json.dumps({"AccessKeyId": "CA", "SecretAccessKey": "CS", "Token": "CT", "Expiration": future}).encode()
    env = {"AWS_CONTAINER_CREDENTIALS_RELATIVE_URI": "/creds", "AWS_CONTAINER_AUTHORIZATION_TOKEN": "tok"}
    with patch("skye.base.http.send_bytes", return_value=body) as send:
        p = aws.CredentialProvider(env=env)
        assert p.get().session_token == "CT"
        p.get()
    assert send.call_count == 1
    assert send.call_args.args[0] == "http://169.254.170.2/creds"
    assert send.call_args.kwargs["headers"] == {"Authorization": "tok"}


def test_expired_credentials_refresh():
    soon = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = json.dumps({"AccessKeyId": "A", "SecretAccessKey": "S", "Expiration": soon}).encode()
    with patch("skye.base.http.send_bytes", return_value=body) as send:
        p = aws.CredentialProvider(env={"AWS_CONTAINER_CREDENTIALS_FULL_URI": "http://x/c"})
        p.get()
        p.get()
    assert send.call_count == 2


def test_imds_v2():
    def fake(url, data=None, **kw):
        if url.endswith("/api/token"):
            assert kw["method"] == "PUT"
            return b"TKN"
        if url.endswith("security-credentials/"):
            assert kw["headers"]["X-aws-ec2-metadata-token"] == "TKN"
            return b"role1\n"
        return json.dumps({"AccessKeyId": "IA", "SecretAccessKey": "IS", "Token": "IT"}).encode()

    with patch("skye.base.http.send_bytes", side_effect=fake):
        assert aws.CredentialProvider(env={}).get().access_key == "IA"


def test_nothing_found_raises():
    with patch("skye.base.http.send_bytes", side_effect=OSError("no route")):
        with pytest.raises(ConfigurationError, match="No AWS credentials"):
            aws.CredentialProvider(env={}).get()
