"""Google credential files: service account (RS256), authorized user, impersonation, Workload Identity Federation."""

import datetime as dt
import json

import pytest

from skye.auth.plugins.google import source as g
from skye.auth.errors import LoginRequiredError
from skye.base.exceptions import MissingExtraError

from .conftest import jwt_parts


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for name in (*g.TOKEN_ENV_VARS, g.API_KEY_ENV_VAR, g.CREDENTIALS_ENV_VAR):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CLOUDSDK_CONFIG", str(tmp_path / "gcloud"))


def _token(seen):
    return 200, {"access_token": "GOOGLE-AT", "expires_in": 3600}


def test_service_account_exchanges_a_signed_assertion(server, rsa_pem):
    server.respond(_token)
    info = {
        "type": "service_account",
        "client_email": "sa@p.iam",
        "private_key": rsa_pem["pkcs8"],
        "private_key_id": "k1",
        "token_uri": server.url + "/token",
    }
    auth = g.GoogleServiceAccountAuth(info)
    assert auth.apply("GET", "u", {})["Authorization"] == "Bearer GOOGLE-AT"
    auth.apply("GET", "u", {})
    assert len(server.seen) == 1
    form = server.seen[0].form()
    assert form["grant_type"] == g.JWT_BEARER_GRANT
    header, payload = jwt_parts(form["assertion"])
    assert header["alg"] == "RS256" and header["kid"] == "k1"
    assert (
        payload["iss"] == "sa@p.iam"
        and payload["scope"] == g.SCOPE
        and payload["aud"] == server.url + "/token"
    )
    assert rsa_pem["pkcs8"] not in repr(auth)


def test_service_account_without_rsa_names_the_extra(monkeypatch, rsa_pem):
    import sys

    monkeypatch.setitem(sys.modules, "rsa", None)
    auth = g.GoogleServiceAccountAuth({"client_email": "a", "private_key": rsa_pem["pkcs1"]})
    with pytest.raises(MissingExtraError, match="auth"):
        auth.apply("GET", "u", {})


def test_authorized_user_refreshes_and_a_revoked_login_says_to_log_in_again(server):
    server.respond(_token)
    auth = g.GoogleAuthorizedUserAuth("cid", "csecret", "rtoken", token_url=server.url + "/token")
    assert auth.apply("GET", "u", {})["Authorization"] == "Bearer GOOGLE-AT"
    form = server.seen[0].form()
    assert form["grant_type"] == "refresh_token" and form["refresh_token"] == "rtoken"
    server.respond(lambda seen: (400, {"error": "invalid_grant"}))
    auth.refresh()
    with pytest.raises(LoginRequiredError, match="gcloud auth application-default login"):
        auth.apply("GET", "u", {})


def test_impersonation_calls_the_iam_api_with_the_source_credential(server):
    expiry = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    server.respond(lambda seen: (200, {"accessToken": "IMPERSONATED", "expireTime": expiry}))
    auth = g.GoogleImpersonatedAuth(
        g.GoogleBearerAuth("source-token"), "target@p.iam", url=server.url + "/iam"
    )
    assert auth.apply("GET", "u", {})["Authorization"] == "Bearer IMPERSONATED"
    seen = server.seen[0]
    assert seen.headers["authorization"] == "Bearer source-token" and seen.json()["scope"] == [
        g.SCOPE
    ]


def test_workload_identity_federation_from_a_file(server, tmp_path):
    (tmp_path / "subject").write_text("oidc-subject\n")
    server.respond(_token)
    info = {
        "type": "external_account",
        "audience": "//iam/aud",
        "token_url": server.url + "/sts",
        "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
        "credential_source": {"file": str(tmp_path / "subject")},
    }
    auth = g.GoogleExternalAccountAuth(info)
    assert auth.apply("GET", "u", {})["Authorization"] == "Bearer GOOGLE-AT"
    form = server.seen[0].form()
    assert (
        form["subject_token"] == "oidc-subject"
        and form["audience"] == "//iam/aud"
        and form["grant_type"].endswith("token-exchange")
    )


def test_workload_identity_federation_from_a_url_and_then_impersonation(server):
    expiry = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    def handler(seen):
        if seen.path == "/subject":
            return 200, {"token": "from-url"}
        if seen.path == "/sts":
            return 200, {"access_token": "FEDERATED", "expires_in": 3600}
        return 200, {"accessToken": "FINAL", "expireTime": expiry}

    server.respond(handler)
    info = {
        "audience": "//aud",
        "token_url": server.url + "/sts",
        "credential_source": {
            "url": server.url + "/subject",
            "format": {"type": "json", "subject_token_field_name": "token"},
        },
        "service_account_impersonation_url": server.url + "/iam",
    }
    assert (
        g.GoogleExternalAccountAuth(info).apply("GET", "u", {})["Authorization"] == "Bearer FINAL"
    )
    assert server.seen[1].form()["subject_token"] == "from-url"
    assert server.seen[2].headers["authorization"] == "Bearer FEDERATED"


def test_unsupported_external_account_sources_are_rejected():
    with pytest.raises(g.GoogleAuthError, match="file"):
        g.GoogleExternalAccountAuth(
            {"audience": "a", "credential_source": {"environment_id": "aws1"}}
        )


def test_credentials_files_are_dispatched_by_type(tmp_path, rsa_pem, monkeypatch):
    def write(name, data):
        path = tmp_path / name
        path.write_text(json.dumps(data))
        return path

    assert isinstance(
        g.load_credentials_file(
            write(
                "sa.json",
                {"type": "service_account", "client_email": "e", "private_key": rsa_pem["pkcs8"]},
            )
        ),
        g.GoogleServiceAccountAuth,
    )
    assert isinstance(
        g.load_credentials_file(
            write(
                "u.json",
                {
                    "type": "authorized_user",
                    "client_id": "a",
                    "client_secret": "b",
                    "refresh_token": "c",
                },
            )
        ),
        g.GoogleAuthorizedUserAuth,
    )
    assert isinstance(
        g.load_credentials_file(
            write(
                "e.json",
                {"type": "external_account", "audience": "a", "credential_source": {"file": "x"}},
            )
        ),
        g.GoogleExternalAccountAuth,
    )
    with pytest.raises(g.GoogleAuthError, match="unsupported type"):
        g.load_credentials_file(write("x.json", {"type": "mystery"}))
    with pytest.raises(g.GoogleAuthError, match="refresh_token"):
        g.load_credentials_file(
            write("bad.json", {"type": "authorized_user", "client_id": "a", "client_secret": "b"})
        )
    with pytest.raises(g.GoogleAuthError):
        g.load_credentials_file(tmp_path / "missing.json")


def test_resolve_uses_the_credentials_variable_then_the_gcloud_file_then_impersonates(
    tmp_path, monkeypatch, rsa_pem
):
    sa = tmp_path / "sa.json"
    sa.write_text(
        json.dumps(
            {"type": "service_account", "client_email": "e", "private_key": rsa_pem["pkcs8"]}
        )
    )
    monkeypatch.setenv(g.CREDENTIALS_ENV_VAR, str(sa))
    assert isinstance(g.resolve_google_auth(), g.GoogleServiceAccountAuth)
    monkeypatch.delenv(g.CREDENTIALS_ENV_VAR)
    adc = g.adc_file_path()
    adc.parent.mkdir(parents=True)
    adc.write_text(
        json.dumps(
            {
                "type": "authorized_user",
                "client_id": "a",
                "client_secret": "b",
                "refresh_token": "c",
            }
        )
    )
    assert isinstance(g.resolve_google_auth(), g.GoogleAuthorizedUserAuth)
    assert isinstance(g.resolve_google_auth(impersonate="t@p.iam"), g.GoogleImpersonatedAuth)
