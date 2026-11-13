"""Non-interactive Google authenticators (standard library only).

Each class implements :class:`~skye.base.interfaces.authentication.AuthenticationInterface`:

- :class:`GoogleBearerAuth`: OAuth2 access token (explicit, from the environment, or from a
  user-supplied token provider callable).
- :class:`GoogleMetadataAuth`: token from the GCE / Cloud Run / GKE metadata server, cached
  until shortly before it expires.
- :class:`GoogleApiKeyAuth`: ``x-goog-api-key`` header.

Credential files (``GOOGLE_APPLICATION_CREDENTIALS``, or the file ``gcloud auth application-default
login`` leaves) are read by :func:`load_credentials_file`:

- :class:`GoogleServiceAccountAuth`: a service-account key; the RS256 assertion needs ``rsa`` (extra
  ``auth``).
- :class:`GoogleAuthorizedUserAuth`: the refresh token of an authorized user (``gcloud`` login).
- :class:`GoogleExternalAccountAuth`: Workload Identity Federation (a token from a file or a URL
  exchanged at the security token service, optionally impersonating a service account).
- :class:`GoogleImpersonatedAuth`: a service account impersonated through another credential.

:func:`resolve_google_auth` picks one. No login is ever launched: a missing or revoked gcloud login
raises ``LoginRequiredError``.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import threading
import time
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from skye.auth import rsa_signing
from skye.auth.cache import CachedBearerAuth
from skye.auth.errors import LoginRequiredError
from skye.auth.plugins.oauth2 import TOKEN_EXCHANGE_GRANT, token_request
from skye.base import http
from skye.base.exceptions import ProviderError
from skye.base.interfaces.authentication import AuthenticationInterface

METADATA_TOKEN_URL = (
    "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
)
TOKEN_ENV_VARS = ("GOOGLE_OAUTH_ACCESS_TOKEN", "CLOUDSDK_AUTH_ACCESS_TOKEN")
API_KEY_ENV_VAR = "GOOGLE_API_KEY"
CREDENTIALS_ENV_VAR = "GOOGLE_APPLICATION_CREDENTIALS"
SCOPE = "https://www.googleapis.com/auth/cloud-platform"
TOKEN_URL = "https://oauth2.googleapis.com/token"
STS_URL = "https://sts.googleapis.com/v1/token"
IAM_URL = (
    "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/{}:generateAccessToken"
)
JWT_BEARER_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"
GCLOUD_LOGIN = "gcloud auth application-default login"
_EXPIRY_SKEW = 60.0


class GoogleAuthError(ProviderError):
    """Raised when no usable Google credentials can be obtained."""

    def __init__(self, message: str) -> None:
        super().__init__(message, provider="google")


class GoogleBearerAuth:
    """``Authorization: Bearer`` from a token string or a callable returning one."""

    def __init__(self, token: str | Callable[[], str] | None = None) -> None:
        self._token = token

    def _resolve(self) -> str:
        token = self._token
        if callable(token):
            token = token()
        if not token:
            for name in TOKEN_ENV_VARS:
                token = os.environ.get(name)
                if token:
                    break
        if not token:
            raise GoogleAuthError(
                "No Google access token: pass one or set " + " or ".join(TOKEN_ENV_VARS)
            )
        return token

    def apply(
        self, method: str, url: str, headers: Mapping[str, str], body: bytes = b""
    ) -> dict[str, str]:
        out = dict(headers)
        out["Authorization"] = f"Bearer {self._resolve()}"
        return out


class GoogleMetadataAuth:
    """Bearer token from the metadata server, cached until it is about to expire."""

    def __init__(
        self,
        url: str = METADATA_TOKEN_URL,
        timeout: float = 3.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._url = url
        self._timeout = timeout
        self._clock = clock
        self._token: str | None = None
        self._expires_at = 0.0
        self._lock = threading.Lock()

    def _fetch(self) -> tuple[str, float]:
        req = urllib.request.Request(self._url, headers={"Metadata-Flavor": "Google"})
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # noqa: S310
                data = json.loads(resp.read().decode("utf-8"))
        except (OSError, ValueError) as e:
            raise GoogleAuthError(f"Metadata server token request failed: {e}") from e
        try:
            return data["access_token"], float(data.get("expires_in", 300))
        except (KeyError, TypeError, ValueError) as e:
            raise GoogleAuthError("Metadata server returned an unexpected token response") from e

    def token(self) -> str:
        with self._lock:
            now = self._clock()
            if self._token is None or now >= self._expires_at - _EXPIRY_SKEW:
                token, ttl = self._fetch()
                self._token, self._expires_at = token, now + ttl
            return self._token

    def apply(
        self, method: str, url: str, headers: Mapping[str, str], body: bytes = b""
    ) -> dict[str, str]:
        out = dict(headers)
        out["Authorization"] = f"Bearer {self.token()}"
        return out


class GoogleApiKeyAuth:
    """``x-goog-api-key`` header."""

    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or os.environ.get(API_KEY_ENV_VAR)
        if not key:
            raise GoogleAuthError(f"No Google API key: pass one or set {API_KEY_ENV_VAR}")
        self._key = key

    def apply(
        self, method: str, url: str, headers: Mapping[str, str], body: bytes = b""
    ) -> dict[str, str]:
        out = dict(headers)
        out["x-goog-api-key"] = self._key
        return out


def _read_json(path: str | Path, what: str) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise GoogleAuthError(f"Cannot read the {what} file {path}") from error
    if not isinstance(data, dict):
        raise GoogleAuthError(f"The {what} file {path} is not a JSON object")
    return data


class GoogleServiceAccountAuth(CachedBearerAuth):
    """Bearer token for a service account: an RS256 assertion exchanged for an access token.

    Needs the extra ``auth`` (the pure-Python ``rsa``); without it ``MissingExtraError`` names it.

    Args:
        info: The parsed service-account key file.
        scopes: Space-separated scopes.
        token_url: The token endpoint (the file's ``token_uri`` by default).
        clock: Seconds since the epoch (replaced in tests).
    """

    def __init__(
        self,
        info: Mapping[str, Any],
        *,
        scopes: str = SCOPE,
        token_url: str | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        url = token_url or info.get("token_uri") or TOKEN_URL

        def fetch() -> tuple[str, float]:
            assertion = rsa_signing.service_account_assertion(
                info, scopes, audience=url, clock=clock
            )
            return token_request(
                url, {"grant_type": JWT_BEARER_GRANT, "assertion": assertion}, provider="google"
            )

        super().__init__(f"google:sa:{info.get('client_email', '')}:{scopes}", fetch)


class GoogleAuthorizedUserAuth(CachedBearerAuth):
    """Bearer token from an authorized user's refresh token (left by a ``gcloud`` login).

    Args:
        client_id: The OAuth client id.
        client_secret: The OAuth client secret.
        refresh_token: The refresh token.
        token_url: The token endpoint.
        login_command: When the refresh token is refused, ``LoginRequiredError`` names this command.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        *,
        token_url: str = TOKEN_URL,
        login_command: str = GCLOUD_LOGIN,
    ) -> None:
        form = {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        }

        def fetch() -> tuple[str, float]:
            try:
                return token_request(token_url, form, provider="google")
            except ProviderError as error:
                if error.details.get("status_code") in (400, 401):
                    raise LoginRequiredError(
                        "gcloud", login_command, "expired or revoked"
                    ) from error
                raise

        super().__init__(f"google:user:{client_id}", fetch)


def _generate_access_token(
    url: str, source_headers: Mapping[str, str], scopes: list[str], delegates: list[str]
) -> tuple[str, float]:
    body: dict[str, Any] = {"scope": scopes, "lifetime": "3600s"}
    if delegates:
        body["delegates"] = delegates
    payload = http.request_json(
        url, body, headers=dict(source_headers), timeout=10.0, provider="google"
    )
    try:
        expires = _dt.datetime.fromisoformat(payload["expireTime"].replace("Z", "+00:00"))
        ttl = (expires - _dt.datetime.now(_dt.UTC)).total_seconds()
        return str(payload["accessToken"]), ttl
    except (KeyError, ValueError, TypeError, AttributeError) as error:
        raise GoogleAuthError("The IAM credentials API returned an unexpected response") from error


class GoogleImpersonatedAuth(CachedBearerAuth):
    """Bearer token of a service account impersonated through another credential.

    Args:
        source: The credential that may impersonate (it authenticates the call to the IAM API).
        target: The email of the service account to impersonate.
        scopes: Scopes of the token.
        delegates: Service accounts in a delegation chain, if any.
        url: The IAM credentials endpoint (replaced in tests).
    """

    def __init__(
        self,
        source: AuthenticationInterface,
        target: str,
        *,
        scopes: list[str] | None = None,
        delegates: list[str] | None = None,
        url: str | None = None,
    ) -> None:
        endpoint = url or IAM_URL.format(target)

        def fetch() -> tuple[str, float]:
            headers = source.apply("POST", endpoint, {}, b"")
            return _generate_access_token(endpoint, headers, scopes or [SCOPE], delegates or [])

        super().__init__(f"google:impersonate:{target}", fetch)


class GoogleExternalAccountAuth(CachedBearerAuth):
    """Workload Identity Federation: a subject token (file or URL) exchanged for an access token.

    Args:
        info: The parsed ``external_account`` credential file (``audience``, ``subject_token_type``,
            ``token_url``, ``credential_source`` with a ``file`` or a ``url``, and optionally
            ``service_account_impersonation_url``).
        scopes: Space-separated scopes.
    """

    def __init__(self, info: Mapping[str, Any], *, scopes: str = SCOPE) -> None:
        source = info.get("credential_source") or {}
        if not ("file" in source or "url" in source):
            raise GoogleAuthError(
                "Only file-sourced and URL-sourced external accounts are supported "
                "(credential_source needs 'file' or 'url')"
            )
        token_url = info.get("token_url") or STS_URL
        impersonation = info.get("service_account_impersonation_url")

        def subject() -> str:
            if "file" in source:
                raw = _read_text(source["file"])
            else:
                raw = http.send_bytes(
                    source["url"],
                    None,
                    headers=source.get("headers"),
                    method="GET",
                    timeout=10.0,
                    provider="google",
                ).decode("utf-8")
            fmt = source.get("format") or {}
            if fmt.get("type") == "json":
                try:
                    return str(json.loads(raw)[fmt["subject_token_field_name"]])
                except (ValueError, KeyError, TypeError) as error:
                    raise GoogleAuthError(
                        "The subject token response has no subject token field"
                    ) from error
            return raw.strip()

        def fetch() -> tuple[str, float]:
            federated, ttl = token_request(
                token_url,
                {
                    "grant_type": TOKEN_EXCHANGE_GRANT,
                    "audience": info["audience"],
                    "scope": scopes if not impersonation else SCOPE,
                    "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
                    "subject_token": subject(),
                    "subject_token_type": info.get(
                        "subject_token_type", "urn:ietf:params:oauth:token-type:jwt"
                    ),
                },
                provider="google",
            )
            if not impersonation:
                return federated, ttl
            return _generate_access_token(
                impersonation, {"Authorization": f"Bearer {federated}"}, scopes.split(), []
            )

        super().__init__(f"google:wif:{info.get('audience', '')}", fetch)


def _read_text(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as error:
        raise GoogleAuthError(f"Cannot read the subject token file {path}") from error


def load_credentials_file(
    path: str | Path, *, scopes: str = SCOPE, login_command: str = GCLOUD_LOGIN
) -> AuthenticationInterface:
    """The authenticator for a Google credentials file, by its ``type``.

    ``service_account`` (needs ``rsa``), ``authorized_user`` and ``external_account`` are supported;
    any other type raises ``GoogleAuthError``.
    """
    info = _read_json(path, "credentials")
    kind = info.get("type")
    if kind == "service_account":
        return GoogleServiceAccountAuth(info, scopes=scopes)
    if kind == "authorized_user":
        try:
            return GoogleAuthorizedUserAuth(
                info["client_id"],
                info["client_secret"],
                info["refresh_token"],
                login_command=login_command,
            )
        except KeyError as error:
            raise GoogleAuthError(
                f"The authorized-user file {path} has no {error.args[0]!r} field"
            ) from error
    if kind == "external_account":
        return GoogleExternalAccountAuth(info, scopes=scopes)
    raise GoogleAuthError(f"The credentials file {path} has an unsupported type {kind!r}")


def adc_file_path(env: Mapping[str, str] | None = None) -> Path:
    """The ``gcloud auth application-default login`` file (``CLOUDSDK_CONFIG`` moves the folder)."""
    env = os.environ if env is None else env
    folder = Path(env.get("CLOUDSDK_CONFIG") or Path.home() / ".config" / "gcloud")
    return folder / "application_default_credentials.json"


def _metadata_server_available(timeout: float = 1.0) -> bool:
    req = urllib.request.Request(
        "http://metadata.google.internal/", headers={"Metadata-Flavor": "Google"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return bool(resp.headers.get("Metadata-Flavor") == "Google")
    except OSError:
        return False


def resolve_google_auth(
    credentials: Any = None, *, impersonate: str | None = None
) -> AuthenticationInterface:
    """Pick an authenticator.

    Order: an :class:`AuthenticationInterface` or token string/callable passed explicitly, an
    access token in the environment, an API key in the environment, the file named by
    ``GOOGLE_APPLICATION_CREDENTIALS``, the gcloud application-default-credentials file, the
    metadata server. With ``impersonate`` (a service-account email) the result impersonates it.

    Raises:
        GoogleAuthError: No credentials are available.
        LoginRequiredError: Only a gcloud login is available and it is missing or expired.
    """
    chosen = _resolve(credentials)
    if impersonate and not isinstance(chosen, GoogleApiKeyAuth):
        return GoogleImpersonatedAuth(chosen, impersonate)
    return chosen


def _resolve(credentials: Any) -> AuthenticationInterface:
    if credentials is not None:
        if isinstance(credentials, AuthenticationInterface):
            return credentials
        if isinstance(credentials, str) or callable(credentials):
            return GoogleBearerAuth(credentials)
        raise GoogleAuthError(
            f"Unsupported credentials type {type(credentials).__name__}; pass an "
            "AuthenticationInterface, an access token or a token provider callable"
        )
    if any(os.environ.get(n) for n in TOKEN_ENV_VARS):
        return GoogleBearerAuth()
    if os.environ.get(API_KEY_ENV_VAR):
        return GoogleApiKeyAuth()
    if os.environ.get(CREDENTIALS_ENV_VAR):
        return load_credentials_file(os.environ[CREDENTIALS_ENV_VAR])
    adc = adc_file_path()
    if adc.exists():
        return load_credentials_file(adc)
    if _metadata_server_available():
        return GoogleMetadataAuth()
    raise GoogleAuthError(
        "No Google credentials available: set GOOGLE_OAUTH_ACCESS_TOKEN, GOOGLE_API_KEY or "
        f"{CREDENTIALS_ENV_VAR}, run on Google Cloud, or log in with `{GCLOUD_LOGIN}`"
    )


__all__ = [
    "GoogleAuthError",
    "GoogleServiceAccountAuth",
    "GoogleAuthorizedUserAuth",
    "GoogleImpersonatedAuth",
    "GoogleExternalAccountAuth",
    "load_credentials_file",
    "adc_file_path",
    "GoogleBearerAuth",
    "GoogleMetadataAuth",
    "GoogleApiKeyAuth",
    "resolve_google_auth",
    "METADATA_TOKEN_URL",
]
