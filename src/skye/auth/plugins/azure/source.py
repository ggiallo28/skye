"""Microsoft Entra ID authentication for Azure OpenAI, non-interactive.

Modes: API key, client secret, certificate (an RS256 client assertion, needs ``rsa`` from the extra
``auth``), federated token file (workload identity), managed identity (IMDS and App Service), and
the access token an earlier ``az login`` left in the Azure CLI cache. The cache is read, never
refreshed by a login: when it is missing or expired ``LoginRequiredError`` says to log in again.

Credentials come from the standard Azure variables (``AZURE_TENANT_ID``, ``AZURE_CLIENT_ID``,
``AZURE_CLIENT_SECRET``, ``AZURE_CLIENT_CERTIFICATE_PATH``, ``AZURE_FEDERATED_TOKEN_FILE``,
``AZURE_AUTHORITY_HOST``, ``AZURE_OPENAI_API_KEY``, ``AZURE_CONFIG_DIR``, ``IDENTITY_ENDPOINT``,
``IDENTITY_HEADER``), never from a prefixed variable.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from skye.auth import rsa_signing
from skye.auth.cache import CachedBearerAuth
from skye.auth.errors import LoginRequiredError
from skye.auth.plugins.oauth2 import file_token, token_request
from skye.base import http
from skye.base.exceptions import ConfigurationError, ProviderError
from skye.base.interfaces.authentication import AuthenticationInterface

OPENAI_SCOPE = "https://cognitiveservices.azure.com/.default"
AUTHORITY = "https://login.microsoftonline.com"
IMDS_URL = "http://169.254.169.254/metadata/identity/oauth2/token"
ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
API_KEY_ENV_VAR = "AZURE_OPENAI_API_KEY"


class AzureAuthError(ProviderError):
    """Raised when no usable Azure credentials can be obtained."""

    def __init__(self, message: str) -> None:
        super().__init__(message, provider="azure")


def _token_url(tenant_id: str, authority: str | None) -> str:
    return f"{(authority or AUTHORITY).rstrip('/')}/{tenant_id}/oauth2/v2.0/token"


def _need(**values: str | None) -> None:
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ConfigurationError(
            f"Azure credentials need {', '.join(missing)}", details={"missing": missing}
        )


class AzureApiKeyAuth:
    """The ``api-key`` header of an Azure OpenAI resource.

    Args:
        api_key: The key; ``AZURE_OPENAI_API_KEY`` when omitted.
    """

    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or os.environ.get(API_KEY_ENV_VAR)
        if not key:
            raise ConfigurationError(
                f"No Azure OpenAI API key: pass one or set {API_KEY_ENV_VAR}",
                details={"variable": API_KEY_ENV_VAR},
            )
        self._key = key

    def apply(
        self, method: str, url: str, headers: Mapping[str, str], body: bytes = b""
    ) -> dict[str, str]:
        """The headers with the key added."""
        return {**headers, "api-key": self._key}

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


class AzureClientSecretAuth(CachedBearerAuth):
    """Bearer token from the client-credentials flow with a client secret.

    Args:
        tenant_id: The directory (tenant) id.
        client_id: The application (client) id.
        client_secret: The secret.
        scope: The scope to ask for.
        authority: The login host (``AZURE_AUTHORITY_HOST``; Microsoft's by default).
    """

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        *,
        scope: str = OPENAI_SCOPE,
        authority: str | None = None,
    ) -> None:
        _need(tenant_id=tenant_id, client_id=client_id, client_secret=client_secret)
        url = _token_url(tenant_id, authority)
        form = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": scope,
        }
        super().__init__(
            f"azure:secret:{tenant_id}:{client_id}:{scope}",
            lambda: token_request(url, form, provider="azure"),
        )


class AzureCertificateAuth(CachedBearerAuth):
    """Bearer token from client-credentials with a certificate (RS256 assertion, needs ``rsa``).

    Args:
        tenant_id: The directory (tenant) id.
        client_id: The application (client) id.
        pem: The PEM text holding the certificate and its RSA private key.
        scope: The scope to ask for.
        authority: The login host.
        clock: Seconds since the epoch (replaced in tests).
    """

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        pem: str,
        *,
        scope: str = OPENAI_SCOPE,
        authority: str | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        _need(tenant_id=tenant_id, client_id=client_id, pem=pem)
        url = _token_url(tenant_id, authority)

        def fetch() -> tuple[str, float]:
            assertion = rsa_signing.entra_client_assertion(
                tenant_id, client_id, pem, pem, audience=url, clock=clock
            )
            form = {
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_assertion_type": ASSERTION_TYPE,
                "client_assertion": assertion,
                "scope": scope,
            }
            return token_request(url, form, provider="azure")

        super().__init__(f"azure:cert:{tenant_id}:{client_id}:{scope}", fetch)


class AzureFederatedTokenAuth(CachedBearerAuth):
    """Bearer token from a federated token file (workload identity): read on each exchange.

    Args:
        tenant_id: The directory (tenant) id.
        client_id: The application (client) id.
        token_file: The file holding the federated (OIDC) token.
        scope: The scope to ask for.
        authority: The login host.
    """

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        token_file: str,
        *,
        scope: str = OPENAI_SCOPE,
        authority: str | None = None,
    ) -> None:
        _need(tenant_id=tenant_id, client_id=client_id, token_file=token_file)
        url = _token_url(tenant_id, authority)
        read = file_token(token_file)

        def fetch() -> tuple[str, float]:
            form = {
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_assertion_type": ASSERTION_TYPE,
                "client_assertion": read(),
                "scope": scope,
            }
            return token_request(url, form, provider="azure")

        super().__init__(f"azure:federated:{tenant_id}:{client_id}:{scope}", fetch)


class AzureManagedIdentityAuth(CachedBearerAuth):
    """Bearer token of a managed identity: App Service (``IDENTITY_ENDPOINT``) or VM metadata.

    Args:
        client_id: The client id of a user-assigned identity (the system-assigned one when omitted).
        scope: The scope to ask for (the resource is the scope without ``/.default``).
        endpoint: The token endpoint (``IDENTITY_ENDPOINT`` or the IMDS address by default).
        identity_header: The ``IDENTITY_HEADER`` secret of App Service.
    """

    def __init__(
        self,
        client_id: str | None = None,
        *,
        scope: str = OPENAI_SCOPE,
        endpoint: str | None = None,
        identity_header: str | None = None,
    ) -> None:
        endpoint = endpoint or os.environ.get("IDENTITY_ENDPOINT")
        identity_header = identity_header or os.environ.get("IDENTITY_HEADER")
        resource = scope[: -len("/.default")] if scope.endswith("/.default") else scope
        app_service = bool(endpoint and identity_header)
        query = {"resource": resource, "api-version": "2019-08-01" if app_service else "2018-02-01"}
        if client_id:
            query["client_id"] = client_id
        url = f"{endpoint or IMDS_URL}?{urllib.parse.urlencode(query)}"
        headers = (
            {"X-IDENTITY-HEADER": identity_header}
            if app_service and identity_header
            else {"Metadata": "true"}
        )

        def fetch() -> tuple[str, float]:
            raw = http.send_bytes(
                url, None, headers=headers, method="GET", timeout=5.0, provider="azure"
            )
            try:
                payload = json.loads(raw.decode("utf-8"))
                return str(payload["access_token"]), float(payload.get("expires_in", 3600))
            except (ValueError, KeyError, TypeError) as error:
                raise AzureAuthError(
                    "The managed identity endpoint returned an unexpected response"
                ) from error

        super().__init__(f"azure:mi:{client_id or 'system'}:{resource}", fetch)


def cli_cache_path(env: Mapping[str, str] | None = None) -> Path:
    """The Azure CLI cache: ``$AZURE_CONFIG_DIR`` or ``~/.azure``, ``msal_token_cache.json``."""
    env = os.environ if env is None else env
    return Path(env.get("AZURE_CONFIG_DIR") or Path.home() / ".azure") / "msal_token_cache.json"


class AzureCliCacheAuth:
    """The access token an earlier ``az login`` left in the Azure CLI cache; it never logs in.

    Args:
        scope: The scope the token must cover.
        path: The cache file (the Azure CLI's by default).
        clock: Seconds since the epoch (replaced in tests).
        margin: Seconds before expiry at which a cached token no longer counts.

    Raises:
        LoginRequiredError: (when a request is authenticated) no unexpired token for the scope is
            cached: run ``az login`` again.
    """

    def __init__(
        self,
        *,
        scope: str = OPENAI_SCOPE,
        path: str | Path | None = None,
        clock: Callable[[], float] = time.time,
        margin: float = 60.0,
    ) -> None:
        self._scope = scope
        self._path = Path(path) if path else cli_cache_path()
        self._clock = clock
        self._margin = margin

    def token(self) -> str:
        """The cached token for the scope."""
        command = f"az login --scope {self._scope}"
        try:
            entries: Mapping[str, Any] = json.loads(self._path.read_text(encoding="utf-8")).get(
                "AccessToken", {}
            )
        except (OSError, ValueError, AttributeError):
            raise LoginRequiredError("az", command, "missing") from None
        wanted = self._scope.replace("/.default", "").rstrip("/")
        now = self._clock()
        for entry in entries.values():
            targets = str(entry.get("target", "")).replace("/.default", "").split()
            try:
                expires = float(entry["expires_on"])
                secret = entry["secret"]
            except (KeyError, TypeError, ValueError):
                continue
            if any(t.rstrip("/") == wanted for t in targets) and expires - self._margin > now:
                return str(secret)
        raise LoginRequiredError("az", command, "expired or without this scope")

    def apply(
        self, method: str, url: str, headers: Mapping[str, str], body: bytes = b""
    ) -> dict[str, str]:
        """The headers with the cached bearer token added."""
        return {**headers, "Authorization": f"Bearer {self.token()}"}

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


def resolve_azure_auth(
    credentials: Any = None, *, scope: str = OPENAI_SCOPE, env: Mapping[str, str] | None = None
) -> AuthenticationInterface:
    """Pick an authenticator for Azure OpenAI.

    Order: one passed explicitly (an authenticator, or an API-key string), an API key in
    ``AZURE_OPENAI_API_KEY``, a federated token file, a client secret, a certificate, App Service
    managed identity, the Azure CLI cache of an earlier ``az login``.

    Raises:
        AzureAuthError: Nothing is available.
    """
    if credentials is not None:
        if isinstance(credentials, AuthenticationInterface):
            return credentials
        if isinstance(credentials, str):
            return AzureApiKeyAuth(credentials)
        raise AzureAuthError(
            f"Unsupported credentials type {type(credentials).__name__}; pass an "
            "AuthenticationInterface or an API key"
        )
    env = os.environ if env is None else env
    tenant, client = env.get("AZURE_TENANT_ID"), env.get("AZURE_CLIENT_ID")
    authority = env.get("AZURE_AUTHORITY_HOST")
    if env.get(API_KEY_ENV_VAR):
        return AzureApiKeyAuth(env[API_KEY_ENV_VAR])
    if tenant and client and env.get("AZURE_FEDERATED_TOKEN_FILE"):
        return AzureFederatedTokenAuth(
            tenant, client, env["AZURE_FEDERATED_TOKEN_FILE"], scope=scope, authority=authority
        )
    if tenant and client and env.get("AZURE_CLIENT_SECRET"):
        return AzureClientSecretAuth(
            tenant, client, env["AZURE_CLIENT_SECRET"], scope=scope, authority=authority
        )
    if tenant and client and env.get("AZURE_CLIENT_CERTIFICATE_PATH"):
        try:
            pem = Path(env["AZURE_CLIENT_CERTIFICATE_PATH"]).read_text(encoding="utf-8")
        except OSError as error:
            raise AzureAuthError(
                f"Cannot read the certificate file {env['AZURE_CLIENT_CERTIFICATE_PATH']}"
            ) from error
        return AzureCertificateAuth(tenant, client, pem, scope=scope, authority=authority)
    if env.get("IDENTITY_ENDPOINT") and env.get("IDENTITY_HEADER"):
        return AzureManagedIdentityAuth(client, scope=scope)
    if cli_cache_path(env).exists():
        return AzureCliCacheAuth(scope=scope, path=cli_cache_path(env))
    raise AzureAuthError(
        "No Azure credentials available: set AZURE_OPENAI_API_KEY, or AZURE_TENANT_ID and "
        "AZURE_CLIENT_ID with AZURE_FEDERATED_TOKEN_FILE, AZURE_CLIENT_SECRET or "
        "AZURE_CLIENT_CERTIFICATE_PATH, run with a managed identity (AzureManagedIdentityAuth), "
        "or log in with `az login`"
    )


__all__ = [
    "AzureAuthError",
    "AzureApiKeyAuth",
    "AzureClientSecretAuth",
    "AzureCertificateAuth",
    "AzureFederatedTokenAuth",
    "AzureManagedIdentityAuth",
    "AzureCliCacheAuth",
    "resolve_azure_auth",
    "cli_cache_path",
    "OPENAI_SCOPE",
]
