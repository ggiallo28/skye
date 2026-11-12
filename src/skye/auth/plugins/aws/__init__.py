"""AWS (plugin of ``auth``, D110): the AWS credential sources: the environment, a named profile, the container and instance endpoints, assume-role, web identity, IAM Identity Center, and the Bedrock API key.

This ``__init__.py`` is the only module that code outside the folder imports. Its public names resolve lazily from ``source.py``, so importing the
folder imports no inner file; ``register`` adds what the folder offers to a registrar, by ``"module:attribute"`` text.
``aws_profile``, ``sts`` and ``sigv4`` are used by these sources only, so they live in this folder.

Raises: nothing from ``register``: a name the registrar already holds is skipped, so it never overwrites what user code registered with ``replace=True``.
Missing: a missing inner file breaks only the name that lives in it (an ``ImportError`` on first access, turned into a ``ConfigurationError`` by the registrar).
Concurrency: ``register`` is called at start-up, or at the first lookup of the kind, from one thread; running it again is harmless.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from skye.base.lazy_import import lazy_names
from skye.base.plugins import Registrar

if (
    TYPE_CHECKING
):  # the names resolve lazily at run time; the type checker reads them from the source
    from skye.auth.plugins.aws.source import (  # noqa: F401
        AwsCredentials,
        BedrockApiKeyAuthenticator,
        CredentialProvider,
        SigV4Authenticator,
        aws_authenticator,
        bedrock_authenticator,
    )

#: The credential sources of this folder: name -> the attribute of this package that builds it.
SOURCES: dict[str, str] = {
    "aws": "aws_authenticator",
    "bedrock": "bedrock_authenticator",
}

_LAZY = {
    "AwsCredentials": "source",
    "BedrockApiKeyAuthenticator": "source",
    "CredentialProvider": "source",
    "SigV4Authenticator": "source",
    "aws_authenticator": "source",
    "bedrock_authenticator": "source",
}
__all__ = [  # a literal list, so that the type checker sees the names as exported
    "AwsCredentials",
    "BedrockApiKeyAuthenticator",
    "CredentialProvider",
    "SigV4Authenticator",
    "aws_authenticator",
    "bedrock_authenticator",
    "SOURCES",
    "register",
]
__getattr__ = lazy_names(__name__, _LAZY)


def register(registrar: Registrar) -> None:
    """Add the credential sources of this folder to ``registrar``, skipping a name it already has."""
    for name, attribute in SOURCES.items():
        if not registrar.has("credential_source", name):
            registrar.credential_source(name, f"{__name__}:{attribute}")
