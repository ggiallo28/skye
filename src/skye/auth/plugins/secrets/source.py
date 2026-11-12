"""Native secret managers over ``base/http.py``: each call authenticated by its own strategy.

- :class:`AwsSecretsManager` and :class:`AwsParameterStore`: SigV4 (``secretsmanager`` and ``ssm``).
- :class:`AzureKeyVault`: an Entra ID bearer token for ``https://vault.azure.net``.
- :class:`GoogleSecretManager`: a Google bearer token.

Each is a credential source reachable through the registry (``aws-secrets-manager``, ``aws-ssm``,
``azure-key-vault``, ``google-secret-manager``). A 401 refreshes the credential and retries once
(``skye.auth.refresh``). A secret is returned to the caller and never logged, put in an error, or
kept in a ``repr``.
"""

from __future__ import annotations

import base64
import json
import urllib.parse
from collections.abc import Mapping
from typing import Any

from skye.auth.plugins.aws import CredentialProvider, SigV4Authenticator
from skye.auth.refresh import send_with_refresh
from skye.base import http
from skye.base.exceptions import ConfigurationError, ProviderError
from skye.base.interfaces.authentication import AuthenticationInterface

_AWS_JSON = "application/x-amz-json-1.1"
KEY_VAULT_SCOPE = "https://vault.azure.net/.default"


def _call(
    authenticator: AuthenticationInterface,
    url: str,
    *,
    method: str,
    headers: Mapping[str, str],
    body: bytes,
    provider: str,
) -> Any:
    def send(signed: dict[str, str]) -> bytes:
        return http.send_bytes(
            url, body or None, headers=signed, method=method, timeout=10.0, provider=provider
        )

    raw = send_with_refresh(send, authenticator, method, url, headers, body)
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError as error:
        raise ProviderError(
            f"The {provider} secret service returned an unexpected response", provider=provider
        ) from error


class _AwsJson:
    """An AWS JSON-1.1 service called with SigV4."""

    service = ""
    target_prefix = ""

    def __init__(
        self,
        region: str,
        *,
        authenticator: AuthenticationInterface | None = None,
        endpoint: str | None = None,
        **credentials: Any,
    ) -> None:
        self._region = region
        self._endpoint = endpoint or f"https://{self.service}.{region}.amazonaws.com/"
        self._auth = authenticator or SigV4Authenticator(
            region, self.service, CredentialProvider(**credentials)
        )

    def _invoke(self, operation: str, payload: Mapping[str, Any]) -> Any:
        body = json.dumps(dict(payload)).encode("utf-8")
        headers = {"Content-Type": _AWS_JSON, "X-Amz-Target": f"{self.target_prefix}.{operation}"}
        return _call(
            self._auth, self._endpoint, method="POST", headers=headers, body=body, provider="aws"
        )

    def __repr__(self) -> str:
        return f"{type(self).__name__}(region={self._region!r})"


class AwsSecretsManager(_AwsJson):
    """AWS Secrets Manager: ``get(secret_id)`` returns the secret string (binary as text)."""

    service = "secretsmanager"
    target_prefix = "secretsmanager"

    def get(
        self, secret_id: str, *, version_stage: str | None = None, version_id: str | None = None
    ) -> str:
        """The value of a secret.

        Args:
            secret_id: The name or ARN.
            version_stage: A staging label (``AWSCURRENT`` by default).
            version_id: A specific version id.
        """
        payload: dict[str, Any] = {"SecretId": secret_id}
        if version_stage:
            payload["VersionStage"] = version_stage
        if version_id:
            payload["VersionId"] = version_id
        data = self._invoke("GetSecretValue", payload)
        if "SecretString" in data:
            return str(data["SecretString"])
        if "SecretBinary" in data:
            return base64.b64decode(data["SecretBinary"]).decode("utf-8")
        raise ProviderError("The secret has no value", provider="aws")


class AwsParameterStore(_AwsJson):
    """AWS SSM Parameter Store: ``get(name)`` returns the parameter value (decrypted by default)."""

    service = "ssm"
    target_prefix = "AmazonSSM"

    def get(self, name: str, *, decrypt: bool = True) -> str:
        """The value of a parameter.

        Args:
            name: The parameter name (``/app/prod/key``).
            decrypt: Decrypt a ``SecureString``.
        """
        data = self._invoke("GetParameter", {"Name": name, "WithDecryption": decrypt})
        try:
            return str(data["Parameter"]["Value"])
        except (KeyError, TypeError) as error:
            raise ProviderError("The parameter has no value", provider="aws") from error


class AzureKeyVault:
    """Azure Key Vault: ``get(name)`` returns the secret value.

    Args:
        vault_url: The vault (``https://myvault.vault.azure.net``).
        authenticator: An Entra ID authenticator for the vault scope; one is resolved from the
            standard Azure variables when omitted.
    """

    def __init__(
        self, vault_url: str, *, authenticator: AuthenticationInterface | None = None
    ) -> None:
        if not vault_url:
            raise ConfigurationError("Azure Key Vault needs the vault URL")
        self._vault = vault_url.rstrip("/")
        if authenticator is None:
            from skye.auth.plugins.azure import resolve_azure_auth

            authenticator = resolve_azure_auth(scope=KEY_VAULT_SCOPE)
        self._auth = authenticator

    def get(self, name: str, *, version: str | None = None) -> str:
        """The value of a secret (the latest version unless ``version`` is given)."""
        path = f"/secrets/{urllib.parse.quote(name, safe='')}" + (
            f"/{urllib.parse.quote(version, safe='')}" if version else ""
        )
        data = _call(
            self._auth,
            f"{self._vault}{path}?api-version=7.4",
            method="GET",
            headers={},
            body=b"",
            provider="azure",
        )
        try:
            return str(data["value"])
        except (KeyError, TypeError) as error:
            raise ProviderError("The secret has no value", provider="azure") from error

    def __repr__(self) -> str:
        return f"{type(self).__name__}(vault={self._vault!r})"


class GoogleSecretManager:
    """Google Secret Manager: ``get(name)`` returns the secret payload as text.

    Args:
        project: The project id.
        authenticator: A Google authenticator; one is resolved when omitted.
        endpoint: The API host (replaced in tests).
    """

    def __init__(
        self,
        project: str,
        *,
        authenticator: AuthenticationInterface | None = None,
        endpoint: str = "https://secretmanager.googleapis.com",
    ) -> None:
        if not project:
            raise ConfigurationError("Google Secret Manager needs the project id")
        self._project = project
        self._endpoint = endpoint.rstrip("/")
        if authenticator is None:
            from skye.auth.plugins.google import resolve_google_auth

            authenticator = resolve_google_auth()
        self._auth = authenticator

    def get(self, name: str, *, version: str = "latest") -> str:
        """The payload of a secret version."""
        secret = urllib.parse.quote(name, safe="")
        path = f"/v1/projects/{self._project}/secrets/{secret}/versions/{version}:access"
        data = _call(
            self._auth,
            f"{self._endpoint}{path}",
            method="GET",
            headers={},
            body=b"",
            provider="google",
        )
        try:
            return base64.b64decode(data["payload"]["data"]).decode("utf-8")
        except (KeyError, TypeError, ValueError) as error:
            raise ProviderError("The secret has no payload", provider="google") from error

    def __repr__(self) -> str:
        return f"{type(self).__name__}(project={self._project!r})"


__all__ = [
    "AwsSecretsManager",
    "AwsParameterStore",
    "AzureKeyVault",
    "GoogleSecretManager",
    "KEY_VAULT_SCOPE",
]
