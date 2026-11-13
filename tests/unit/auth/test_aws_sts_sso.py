"""AWS assume-role, web identity and IAM Identity Center (SSO) against fake STS and portal endpoints."""

import datetime as dt
import hashlib
import json

import pytest

from skye.auth.plugins.aws import source as aws
from skye.auth.errors import LoginRequiredError
from skye.base.exceptions import ConfigurationError, ProviderError

EXPIRY = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
STS_XML = f"""<AssumeRoleResponse xmlns="https://sts.amazonaws.com/doc/2011-06-15/"><AssumeRoleResult><Credentials>
<AccessKeyId>ASIAROLE</AccessKeyId><SecretAccessKey>role-secret</SecretAccessKey><SessionToken>role-token</SessionToken>
<Expiration>{EXPIRY}</Expiration></Credentials></AssumeRoleResult></AssumeRoleResponse>"""


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_ROLE_ARN",
        "AWS_WEB_IDENTITY_TOKEN_FILE",
        "AWS_PROFILE",
        "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
        "AWS_CONTAINER_CREDENTIALS_FULL_URI",
    ):
        monkeypatch.delenv(name, raising=False)


def test_credentials_never_show_secrets_in_repr():
    creds = aws.AwsCredentials("AKIA123", "very-secret", "tok")
    assert (
        "very-secret" not in repr(creds)
        and "AKIA123" not in repr(creds)
        and "tok" not in repr(creds)
    )


def test_assume_role_is_signed_and_returns_the_role_session(server):
    server.respond(lambda seen: (200, STS_XML.encode()))
    provider = aws.CredentialProvider(
        access_key="AKSRC",
        secret_key="SRC",
        region="us-east-1",  # AssumeRole is signed: it needs a region (there is no default)
        role_arn="arn:aws:iam::222222222222:role/cross",
        role_session_name="s1",
        external_id="ext",
        sts_endpoint=server.url + "/",
    )
    creds = provider.get()
    assert (creds.access_key, creds.secret_key, creds.session_token) == (
        "ASIAROLE",
        "role-secret",
        "role-token",
    )
    seen = server.seen[0]
    assert (
        seen.headers["authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKSRC/")
        and "/sts/" in seen.headers["authorization"]
    )
    form = seen.form()
    assert (
        form["Action"] == "AssumeRole"
        and form["RoleArn"].endswith("role/cross")
        and form["ExternalId"] == "ext"
    )
    provider.get()
    assert len(server.seen) == 1  # cached until near expiry


def test_web_identity_from_the_standard_variables(server, tmp_path):
    token = tmp_path / "token"
    token.write_text("oidc-token\n")
    server.respond(lambda seen: (200, STS_XML.encode()))
    env = {"AWS_ROLE_ARN": "arn:aws:iam::1:role/web", "AWS_WEB_IDENTITY_TOKEN_FILE": str(token)}
    creds = aws.CredentialProvider(env=env, sts_endpoint=server.url + "/").get()
    assert creds.access_key == "ASIAROLE"
    seen = server.seen[0]
    assert "authorization" not in seen.headers and seen.form()["WebIdentityToken"] == "oidc-token"
    assert seen.form()["Action"] == "AssumeRoleWithWebIdentity"


def test_an_unreadable_web_identity_file_names_the_path(tmp_path):
    env = {"AWS_ROLE_ARN": "arn", "AWS_WEB_IDENTITY_TOKEN_FILE": str(tmp_path / "gone")}
    with pytest.raises(ConfigurationError, match="gone"):
        aws.CredentialProvider(env=env).get()


def test_an_sts_error_is_a_provider_error(server):
    server.respond(lambda seen: (403, b"<Error>AccessDenied</Error>"))
    with pytest.raises(ProviderError) as caught:
        aws.CredentialProvider(
            access_key="a",
            secret_key="b",
            role_arn="arn",
            region="us-east-1",
            sts_endpoint=server.url + "/",
        ).get()
    assert caught.value.details["status_code"] == 403


def test_a_profile_that_assumes_a_role_from_another_profile(server, tmp_path):
    (tmp_path / "credentials").write_text(
        "[base]\naws_access_key_id = AKBASE\naws_secret_access_key = BASE\n"
    )
    (tmp_path / "config").write_text(
        "[profile admin]\nrole_arn = arn:aws:iam::3:role/admin\nsource_profile = base\nrole_session_name = prof\n"
    )
    server.respond(lambda seen: (200, STS_XML.encode()))
    env = {
        "AWS_SHARED_CREDENTIALS_FILE": str(tmp_path / "credentials"),
        "AWS_CONFIG_FILE": str(tmp_path / "config"),
    }
    creds = aws.CredentialProvider(
        profile_name="admin", env=env, region="us-east-1", sts_endpoint=server.url + "/"
    ).get()
    assert creds.access_key == "ASIAROLE"
    assert (
        "AKBASE" in server.seen[0].headers["authorization"]
        and server.seen[0].form()["RoleSessionName"] == "prof"
    )


def _sso_env(tmp_path, expires):
    session = "my-sso"
    (tmp_path / "config").write_text(
        "[profile work]\nsso_session = my-sso\nsso_account_id = 123\nsso_role_name = Dev\n"
        "[sso-session my-sso]\nsso_start_url = https://x.awsapps.com/start\nsso_region = eu-west-1\n"
    )
    cache = tmp_path / "cache"
    cache.mkdir()
    if expires is not None:
        (cache / f"{hashlib.sha1(session.encode()).hexdigest()}.json").write_text(
            json.dumps({"accessToken": "sso-token", "expiresAt": expires})
        )
    return {
        "AWS_CONFIG_FILE": str(tmp_path / "config"),
        "AWS_SSO_CACHE_DIR": str(cache),
        "AWS_SHARED_CREDENTIALS_FILE": str(tmp_path / "none"),
    }


def test_sso_reads_the_login_cache_and_asks_the_portal(server, tmp_path):
    future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    env = _sso_env(tmp_path, future)
    expiry_ms = int((dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).timestamp() * 1000)
    server.respond(
        lambda seen: (
            200,
            {
                "roleCredentials": {
                    "accessKeyId": "ASIASSO",
                    "secretAccessKey": "sso-secret",
                    "sessionToken": "sso-session",
                    "expiration": expiry_ms,
                }
            },
        )
    )
    creds = aws.CredentialProvider(profile_name="work", env=env, sso_endpoint=server.url).get()
    assert creds.access_key == "ASIASSO"
    seen = server.seen[0]
    assert (
        seen.headers["x-amz-sso_bearer_token"] == "sso-token"
        and "account_id=123" in seen.path
        and "role_name=Dev" in seen.path
    )


@pytest.mark.parametrize(
    "expires, reason", [(None, "missing"), ("2001-01-01T00:00:00Z", "expired")]
)
def test_sso_without_a_usable_login_says_to_log_in_again(tmp_path, expires, reason):
    env = _sso_env(tmp_path, expires)
    with pytest.raises(LoginRequiredError) as caught:
        aws.CredentialProvider(profile_name="work", env=env).get()
    assert "aws sso login --profile work" in str(caught.value) and reason in str(caught.value)
    assert isinstance(caught.value, ConfigurationError)
