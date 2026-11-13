# Requirement 11.6
"""API-key and bearer strategies for OpenAI-compatible providers, Anthropic and Cohere.

Each provider's key comes from the ``api_key_variables`` of its profile (the provider-standard
variable, never a prefixed one); no table of the names is kept here. A missing key raises
``ConfigurationError`` naming the variable, never a value;
``repr`` shows the class name only; ``apply`` returns a new dict and leaves the input alone.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from skye.base.api_keys import api_key_variable
from skye.base.exceptions import ConfigurationError


def _key(api_key: str | None, variables: tuple[str, ...]) -> str:
    key = api_key
    if not key:
        for name in variables:
            key = os.environ.get(name)
            if key:
                break
    if not key:
        named = " or ".join(variables)
        raise ConfigurationError(
            f"No API key: pass api_key or set {named}" if named else "No API key: pass api_key",
            details={"variable": variables[0] if variables else None},
        )
    return key


class ApiKeyAuth:
    """The key in a header of its own (``x-api-key`` for Anthropic).

    Args:
        env_var: The variable to read when no key is passed (the first variable of the profile of
            the provider); ``None`` means the key must be passed.
        api_key: The key; the variable is not read when it is given.
        header: The header that carries the key.
    """

    def __init__(
        self, env_var: str | None, api_key: str | None = None, *, header: str = "x-api-key"
    ) -> None:
        self._key = _key(api_key, (env_var,) if env_var else ())
        self._header = header

    def apply(
        self, method: str, url: str, headers: Mapping[str, str], body: bytes = b""
    ) -> dict[str, str]:
        """The headers with the key added."""
        return {**headers, self._header: self._key}

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


class BearerAuth:
    """``Authorization: Bearer <key>``, the scheme of OpenAI and of the providers that copy it.

    Args:
        env_var: The variable to read when no key is passed (the first variable of the profile of
            the provider); ``None`` means the key must be passed.
        api_key: The key; the variable is not read when it is given.
    """

    def __init__(self, env_var: str | None, api_key: str | None = None) -> None:
        self._key = _key(api_key, (env_var,) if env_var else ())

    def apply(
        self, method: str, url: str, headers: Mapping[str, str], body: bytes = b""
    ) -> dict[str, str]:
        """The headers with the bearer key added."""
        return {**headers, "Authorization": f"Bearer {self._key}"}

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


def openai_authenticator(api_key: str | None = None, *, env_var: str | None = None) -> BearerAuth:
    """Bearer authentication for OpenAI and OpenAI-compatible servers.

    Args:
        api_key: The key; the variable is not read when it is given.
        env_var: The variable to read; the one of the profile of ``openai`` when omitted.
    """
    return BearerAuth(env_var or api_key_variable("openai"), api_key)


def anthropic_authenticator(api_key: str | None = None) -> ApiKeyAuth:
    """The ``x-api-key`` header of Anthropic, with the key from the variable of the profile of
    ``anthropic``."""
    return ApiKeyAuth(api_key_variable("anthropic"), api_key, header="x-api-key")


def cohere_authenticator(api_key: str | None = None) -> BearerAuth:
    """Bearer authentication for Cohere, with the key from the variable of the profile of
    ``cohere``."""
    return BearerAuth(api_key_variable("cohere"), api_key)


def api_key_authenticator(provider: str, api_key: str | None = None) -> ApiKeyAuth | BearerAuth:
    """The strategy of a provider by name: Anthropic uses ``x-api-key``, the others a bearer key.

    The variable is the first of ``api_key_variables`` of the profile of ``provider``.

    Raises:
        ConfigurationError: For a provider with no variable in its profile (register it with
            ``ProviderProfile(api_key_variables=...)``, or pass ``env_var`` to ``BearerAuth``
            yourself).
    """
    variable = api_key_variable(provider)
    if variable is None:
        raise ConfigurationError(
            f"No standard API-key variable is known for provider {provider!r}",
            details={"provider": provider},
        )
    if provider == "anthropic":
        return anthropic_authenticator(api_key)
    return BearerAuth(variable, api_key)


__all__ = [
    "ApiKeyAuth",
    "BearerAuth",
    "openai_authenticator",
    "anthropic_authenticator",
    "cohere_authenticator",
    "api_key_authenticator",
]
