# D110
"""Azure (plugin of ``auth``): the Azure sources: API key, client secret, certificate, federated
token, managed identity and the CLI cache.

This ``__init__.py`` is the only module that code outside the folder imports. Its public names
resolve lazily from ``source.py``, so importing the
folder imports no inner file; ``register`` adds what the folder offers to a registrar, by
``"module:attribute"`` text.

Raises: nothing from ``register``: a name the registrar already holds is skipped, so it never
overwrites what user code registered with ``replace=True``.
Missing: a missing inner file breaks only the name that lives in it (an ``ImportError`` on first
access, turned into a ``ConfigurationError`` by the registrar).
Concurrency: ``register`` is called at start-up, or at the first lookup of the kind, from one
thread; running it again is harmless.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from skye.base.lazy_import import lazy_names
from skye.base.plugins import Registrar

if (
    TYPE_CHECKING
):  # the names resolve lazily at run time; the type checker reads them from the source
    from skye.auth.plugins.azure.source import (  # noqa: F401
        API_KEY_ENV_VAR,
        ASSERTION_TYPE,
        AUTHORITY,
        IMDS_URL,
        OPENAI_SCOPE,
        AzureApiKeyAuth,
        AzureAuthError,
        AzureCertificateAuth,
        AzureCliCacheAuth,
        AzureClientSecretAuth,
        AzureFederatedTokenAuth,
        AzureManagedIdentityAuth,
        cli_cache_path,
        resolve_azure_auth,
    )

#: The credential sources of this folder: name -> the attribute of this package that builds it.
SOURCES: dict[str, str] = {
    "azure": "resolve_azure_auth",
}

_LAZY = {
    "API_KEY_ENV_VAR": "source",
    "ASSERTION_TYPE": "source",
    "AUTHORITY": "source",
    "AzureApiKeyAuth": "source",
    "AzureAuthError": "source",
    "AzureCertificateAuth": "source",
    "AzureCliCacheAuth": "source",
    "AzureClientSecretAuth": "source",
    "AzureFederatedTokenAuth": "source",
    "AzureManagedIdentityAuth": "source",
    "IMDS_URL": "source",
    "OPENAI_SCOPE": "source",
    "cli_cache_path": "source",
    "resolve_azure_auth": "source",
}
__all__ = [  # a literal list, so that the type checker sees the names as exported
    "API_KEY_ENV_VAR",
    "ASSERTION_TYPE",
    "AUTHORITY",
    "AzureApiKeyAuth",
    "AzureAuthError",
    "AzureCertificateAuth",
    "AzureCliCacheAuth",
    "AzureClientSecretAuth",
    "AzureFederatedTokenAuth",
    "AzureManagedIdentityAuth",
    "IMDS_URL",
    "OPENAI_SCOPE",
    "cli_cache_path",
    "resolve_azure_auth",
    "SOURCES",
    "register",
]
__getattr__ = lazy_names(__name__, _LAZY)


def register(registrar: Registrar) -> None:
    """Add the credential sources of this folder to ``registrar``, skipping a name it already
    has."""
    for name, attribute in SOURCES.items():
        if not registrar.has("credential_source", name):
            registrar.credential_source(name, f"{__name__}:{attribute}")
