"""Authentication and credentials.

Component: auth. Layer: 0 (next to base). Imports only base.

Every outbound request is authenticated through one Port (``AuthenticationInterface``); this
component implements it for each provider's documented non-interactive modes and never launches a
login. The credential sources are in ``plugins/``, one folder per family, each with one ``__init__.py`` as its only door (D110):

- ``plugins/aws`` (``source``, ``aws_profile``, ``sts``, ``sigv4``): AWS (SigV4, Bedrock API key, environment, profile,
  container and instance credentials, assume-role, web identity, IAM Identity Center cache).
- ``plugins/google``: bearer, metadata server, API key, service account, authorized user, impersonation,
  Workload Identity Federation.
- ``plugins/azure``: API key, client secret, certificate, federated token, managed identity, CLI cache.
- ``plugins/openai_compatible``: API key and bearer for OpenAI-compatible providers, Anthropic and Cohere.
- ``plugins/oauth2``: client-credentials and token-exchange flows.
- ``plugins/secrets``: AWS Secrets Manager, SSM Parameter Store, Azure Key Vault, Google Secret Manager.

What more than one family uses stays in the root:

- ``cache``, ``refresh``: the lazy token cache and the 401 refresh-and-retry-once helper.
- ``rsa_signing``: RS256 assertions with the pure-Python ``rsa`` (extra ``auth``).
- ``errors``: the login-required error.
- ``registry``: the one extension point, a registry of credential sources (a view of the registrar).

`auth` is authentication and credentials; `policy` is authorization.

Codename: ozone.
"""

from typing import Any

# The commonest classes, importable as ``from skye.auth import SigV4Authenticator``; each is loaded on first use so that
# ``import skye.auth`` stays light.
_LAZY = {
    "AwsCredentials": "skye.auth.plugins.aws",
    "CredentialProvider": "skye.auth.plugins.aws",
    "SigV4Authenticator": "skye.auth.plugins.aws",
    "BedrockApiKeyAuthenticator": "skye.auth.plugins.aws",
    "aws_authenticator": "skye.auth.plugins.aws",
    "bedrock_authenticator": "skye.auth.plugins.aws",
    "register_credential_source": "skye.auth.registry",
    "resolve_credential_source": "skye.auth.registry",
}

__all__ = list(_LAZY)


def __getattr__(name: str) -> Any:
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module 'skye.auth' has no attribute {name!r}")
    import importlib

    value = getattr(importlib.import_module(module), name)
    globals()[name] = value
    return value
