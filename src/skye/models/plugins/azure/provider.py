"""Azure OpenAI: the OpenAI wire format behind an Azure resource and a deployment name.

Authentication is an API key (``api_key``, or ``AZURE_OPENAI_API_KEY``) or Microsoft Entra ID:
pass ``credentials=`` an authenticator of ``skye.auth.plugins.azure`` (client secret, certificate,
federated token, managed identity, the ``az login`` cache), or nothing and let
``resolve_azure_auth`` pick one from the standard Azure variables.

Example:
    >>> from skye.models.plugins.azure.provider import AzureOpenAIProvider
    >>> provider = AzureOpenAIProvider(
    ...     azure_endpoint="https://myresource.openai.azure.com/", api_key="...",
    ...     api_version="2024-10-21", deployment_name="gpt-4o",
    ... )
"""

from typing import Any

from skye.auth.plugins.azure import (
    AzureApiKeyAuth,
    AzureAuthError,
    resolve_azure_auth,
)
from skye.base.api_keys import api_key_variable
from skye.base.completion import CompleteRequest
from skye.base.exceptions import ConfigurationError
from skye.base.interfaces.authentication import AuthenticationInterface
from skye.models.base import BaseModelProvider
from skye.models.utilities.openai_compatible import OpenAICompatibleProvider


class AzureOpenAIProvider(OpenAICompatibleProvider):
    """Azure OpenAI expressed as configuration of the OpenAI-compatible adapter.

    Azure differs only in client construction (endpoint + api_version), the deployment name
    standing in for the model, the ``azure_`` metadata prefix, no ``system_fingerprint``, and its
    authentication (an ``api-key`` header or an Entra ID bearer token).

    Args:
        azure_endpoint: Azure OpenAI endpoint URL (e.g. https://myresource.openai.azure.com/)
        api_key: Azure OpenAI API key; when omitted (and no ``credentials``), the credentials come
            from the environment: ``AZURE_OPENAI_API_KEY``, then the Entra ID variables
            (``resolve_azure_auth``)
        api_version: Azure OpenAI API version (e.g. 2024-10-21)
        deployment_name: Name of the deployment (e.g. gpt-4o)
        credentials: An authenticator of ``skye.auth.plugins.azure`` (Entra ID:
            ``AzureClientSecretAuth``,
            ``AzureCertificateAuth``, ``AzureFederatedTokenAuth``, ``AzureManagedIdentityAuth``,
            ``AzureCliCacheAuth``), any ``AuthenticationInterface``, or an API key string

    Raises:
        ConfigurationError: No credentials are given or found; the message names
            ``AZURE_OPENAI_API_KEY`` and the Entra ID variables.
    """

    provider_name = "azure"
    metadata_prefix = "azure_"
    reports_fingerprint = False

    def __init__(
        self,
        azure_endpoint: str,
        api_key: str | None = None,
        api_version: str | None = None,
        deployment_name: str | None = None,
        credentials: AuthenticationInterface | str | None = None,
        **kwargs: Any,
    ) -> None:
        if not api_version or not deployment_name:
            raise ConfigurationError("Azure OpenAI needs api_version and deployment_name")
        BaseModelProvider.__init__(
            self,
            azure_endpoint=azure_endpoint,
            api_version=api_version,
            deployment_name=deployment_name,
            **kwargs,
        )
        self.azure_endpoint = azure_endpoint
        self.api_version = api_version
        self.deployment_name = deployment_name
        self.api_base = None
        try:
            auth = AzureApiKeyAuth(api_key) if api_key else resolve_azure_auth(credentials)
        except AzureAuthError as error:
            raise ConfigurationError(
                error.message, details={"variable": api_key_variable("azure")}
            ) from error
        self._auth: AuthenticationInterface = auth
        #: The API key when the credentials are a key; ``None`` with Entra ID.
        self.api_key = getattr(auth, "_key", None) if isinstance(auth, AzureApiKeyAuth) else None

    def _endpoint_url(self) -> str:
        return (
            f"{self.azure_endpoint.rstrip('/')}/openai/deployments/{self.deployment_name}"
            f"/chat/completions?api-version={self.api_version}"
        )

    def _auth_headers(self) -> dict[str, str]:
        return {}

    def _authenticator(self) -> AuthenticationInterface:
        return self._auth

    def _model_name(self, request: CompleteRequest) -> str:
        return str(self.deployment_name)


__all__ = ["AzureOpenAIProvider"]
