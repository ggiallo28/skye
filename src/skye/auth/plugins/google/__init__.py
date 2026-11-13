# D110
"""Google (plugin of ``auth``): the Google sources: bearer, metadata server, API key, service
account, authorized user, impersonation and Workload Identity Federation.

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
    from skye.auth.plugins.google.source import (  # noqa: F401
        API_KEY_ENV_VAR,
        CREDENTIALS_ENV_VAR,
        GCLOUD_LOGIN,
        IAM_URL,
        JWT_BEARER_GRANT,
        METADATA_TOKEN_URL,
        SCOPE,
        STS_URL,
        TOKEN_ENV_VARS,
        TOKEN_URL,
        GoogleApiKeyAuth,
        GoogleAuthError,
        GoogleAuthorizedUserAuth,
        GoogleBearerAuth,
        GoogleExternalAccountAuth,
        GoogleImpersonatedAuth,
        GoogleMetadataAuth,
        GoogleServiceAccountAuth,
        adc_file_path,
        load_credentials_file,
        resolve_google_auth,
    )

#: The credential sources of this folder: name -> the attribute of this package that builds it.
SOURCES: dict[str, str] = {
    "google": "resolve_google_auth",
}

_LAZY = {
    "API_KEY_ENV_VAR": "source",
    "CREDENTIALS_ENV_VAR": "source",
    "GCLOUD_LOGIN": "source",
    "GoogleApiKeyAuth": "source",
    "GoogleAuthError": "source",
    "GoogleAuthorizedUserAuth": "source",
    "GoogleBearerAuth": "source",
    "GoogleExternalAccountAuth": "source",
    "GoogleImpersonatedAuth": "source",
    "GoogleMetadataAuth": "source",
    "GoogleServiceAccountAuth": "source",
    "IAM_URL": "source",
    "JWT_BEARER_GRANT": "source",
    "METADATA_TOKEN_URL": "source",
    "SCOPE": "source",
    "STS_URL": "source",
    "TOKEN_ENV_VARS": "source",
    "TOKEN_URL": "source",
    "adc_file_path": "source",
    "load_credentials_file": "source",
    "resolve_google_auth": "source",
}
__all__ = [  # a literal list, so that the type checker sees the names as exported
    "API_KEY_ENV_VAR",
    "CREDENTIALS_ENV_VAR",
    "GCLOUD_LOGIN",
    "GoogleApiKeyAuth",
    "GoogleAuthError",
    "GoogleAuthorizedUserAuth",
    "GoogleBearerAuth",
    "GoogleExternalAccountAuth",
    "GoogleImpersonatedAuth",
    "GoogleMetadataAuth",
    "GoogleServiceAccountAuth",
    "IAM_URL",
    "JWT_BEARER_GRANT",
    "METADATA_TOKEN_URL",
    "SCOPE",
    "STS_URL",
    "TOKEN_ENV_VARS",
    "TOKEN_URL",
    "adc_file_path",
    "load_credentials_file",
    "resolve_google_auth",
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
