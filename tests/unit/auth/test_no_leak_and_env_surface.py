"""No secret in a log, repr or error; no background thread, subprocess or interactive login; credentials only
from provider-standard variables, and no prefixed variable beyond the three owned by ``base``
(Requirements 11.3, 11.6; decision D18)."""

import ast
import json
import logging
import re
from pathlib import Path

import pytest

from skye.auth.plugins.aws import source as aws
from skye.auth.plugins.azure import source as azure
from skye.auth.plugins.google import source as google
from skye.auth.plugins.oauth2 import source as oauth2
from skye.auth.plugins.openai_compatible import source as openai_compatible
from skye.auth.plugins.secrets import source as secrets
from skye.auth.cache import CachedBearerAuth
from skye.base.config import ALL_ENV_VARS
from skye.base.exceptions import ConfigurationError, SkyeError

AUTH = Path(__file__).resolve().parents[3] / "src" / "skye" / "auth"
# Every module of ``auth``, the plugin folders included (D110): the scan must not stop at the root.
MODULES = sorted(p for p in AUTH.rglob("*.py") if "__pycache__" not in p.parts)
FORBIDDEN_CALLS = {
    "Thread",
    "Timer",
    "Popen",
    "run",
    "call",
    "check_output",
    "system",
    "input",
    "open_new",
    "open_new_tab",
}
FORBIDDEN_IMPORTS = {"subprocess", "multiprocessing", "webbrowser", "sched"}
#: Prefixes of the provider-standard variables ``auth`` may read.
STANDARD_PREFIXES = (
    "AWS_",
    "GOOGLE_",
    "CLOUDSDK_",
    "AZURE_",
    "IDENTITY_",
    "OPENAI_",
    "ANTHROPIC_",
    "COHERE_",
    "MISTRAL_",
    "GROQ_",
    "TOGETHER_",
    "OPENROUTER_",
    "DEEPSEEK_",
    "XAI_",
)


def _trees():
    return [(path, ast.parse(path.read_text(encoding="utf-8"))) for path in MODULES]


def test_no_background_thread_subprocess_or_interactive_login():
    problems = []
    for path, tree in _trees():
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = (
                    [a.name for a in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                )
                problems += [
                    f"{path.name} imports {n}"
                    for n in names
                    if n.split(".")[0] in FORBIDDEN_IMPORTS
                ]
            if isinstance(node, ast.Call):
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                owner = ast.unparse(func.value) if isinstance(func, ast.Attribute) else ""
                if name in FORBIDDEN_CALLS and owner in {
                    "",
                    "threading",
                    "subprocess",
                    "os",
                    "webbrowser",
                }:
                    problems.append(f"{path.name} calls {owner + '.' if owner else ''}{name}")
    assert not problems, problems


def _env_names():
    """Every string constant that looks like an environment variable name, by module."""
    found = {}
    for path, tree in _trees():
        exported = {
            c.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            # the public names a module or a plugin door exports: ``__all__``, and the keys of the ``_LAZY`` table of a door (D110)
            and any(getattr(t, "id", "") in {"__all__", "_LAZY"} for t in node.targets)
            for c in ast.walk(node.value)
            if isinstance(c, ast.Constant)
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and re.fullmatch(r"[A-Z][A-Z0-9]*(_[A-Z0-9]+)+", node.value)
                and node.value not in exported
            ):
                found.setdefault(node.value, set()).add(path.name)
    return found


def test_credentials_come_only_from_provider_standard_variables():
    names = _env_names()
    assert names, "the scan found no variable names: it is broken"
    odd = {n: sorted(m) for n, m in names.items() if not n.startswith(STANDARD_PREFIXES)}
    assert not odd, f"variables that are not provider-standard: {odd}"


def test_auth_adds_no_prefixed_variable_beyond_the_ones_of_base():
    # Two since D106 removed `enable_telemetry` and its variable.
    assert sorted(ALL_ENV_VARS) == ["SKYE_CONFIG", "SKYE_LOG_LEVEL"]
    for path in MODULES:
        assert "SKYE_" not in path.read_text(
            encoding="utf-8"
        ), f"{path.name} mentions a prefixed variable"


SECRET = "S3CR3T-VALUE-9f2c"


def _authenticators(rsa_pem):
    return [
        openai_compatible.openai_authenticator(SECRET),
        openai_compatible.anthropic_authenticator(SECRET),
        openai_compatible.cohere_authenticator(SECRET),
        google.GoogleBearerAuth(SECRET),
        google.GoogleApiKeyAuth(SECRET),
        google.GoogleAuthorizedUserAuth("cid", SECRET, SECRET),
        google.GoogleServiceAccountAuth({"client_email": "e", "private_key": SECRET}),
        azure.AzureApiKeyAuth(SECRET),
        azure.AzureClientSecretAuth("t", "c", SECRET),
        azure.AzureCertificateAuth("t", "c", SECRET),
        azure.AzureFederatedTokenAuth("t", "c", "/f"),
        oauth2.ClientCredentialsAuth("https://t", "id", SECRET),
        oauth2.TokenExchangeAuth("https://t", SECRET),
        aws.BedrockApiKeyAuthenticator(SECRET),
        aws.SigV4Authenticator("us-east-1", "bedrock", aws.AwsCredentials("AKIA", SECRET, SECRET)),
        CachedBearerAuth("k", lambda: (SECRET, 10)),
        secrets.AwsSecretsManager("us-east-1", access_key="AKIA", secret_key=SECRET),
        secrets.AzureKeyVault(
            "https://v", authenticator=CachedBearerAuth("k", lambda: (SECRET, 10))
        ),
        secrets.GoogleSecretManager("p", authenticator=CachedBearerAuth("k", lambda: (SECRET, 10))),
    ]


def test_no_secret_in_a_repr_or_str(rsa_pem):
    for auth in _authenticators(rsa_pem):
        assert SECRET not in repr(auth) and SECRET not in str(auth), type(auth).__name__
    assert SECRET not in repr(aws.AwsCredentials("AKIA", SECRET, SECRET))


def test_a_missing_credential_error_names_the_variable_not_a_value(monkeypatch):
    for name in (
        "OPENAI_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "AWS_BEARER_TOKEN_BEDROCK",
        "GOOGLE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    cases = [
        (lambda: openai_compatible.openai_authenticator(), "OPENAI_API_KEY"),
        (lambda: azure.AzureApiKeyAuth(), "AZURE_OPENAI_API_KEY"),
        (lambda: aws.BedrockApiKeyAuthenticator(), "AWS_BEARER_TOKEN_BEDROCK"),
        (lambda: google.GoogleApiKeyAuth(), "GOOGLE_API_KEY"),
    ]
    monkeypatch.setenv("SOME_OTHER_VARIABLE", SECRET)
    for build, variable in cases:
        with pytest.raises(SkyeError) as caught:
            build()
        assert variable in str(caught.value) and SECRET not in str(caught.value)


def test_errors_and_logs_of_a_failed_exchange_do_not_carry_the_secret(server, caplog):
    server.respond(lambda seen: (401, {"error": "invalid_client"}))
    auth = oauth2.ClientCredentialsAuth(server.url + "/token", "id", SECRET)
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(SkyeError) as caught:
            auth.apply("GET", "u", {})
    assert SECRET not in str(caught.value) and SECRET not in repr(caught.value)
    assert SECRET not in caplog.text


def test_a_bad_private_key_never_appears_in_the_error(rsa_pem):
    bad = "-----BEGIN PRIVATE KEY-----\n" + SECRET + "\n-----END PRIVATE KEY-----"
    with pytest.raises(ConfigurationError) as caught:
        google.GoogleServiceAccountAuth({"client_email": "e", "private_key": bad}).apply(
            "GET", "u", {}
        )
    assert SECRET not in str(caught.value)


def test_credential_files_are_not_echoed_when_malformed(tmp_path):
    path = tmp_path / "creds.json"
    path.write_text(
        json.dumps({"type": "authorized_user", "client_id": "a", "client_secret": SECRET})
    )
    with pytest.raises(SkyeError) as caught:
        google.load_credentials_file(path)
    assert SECRET not in str(caught.value)
