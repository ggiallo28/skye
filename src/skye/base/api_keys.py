"""The API-key variables of a provider, read from its profile (Requirement 60.3, 11.6).

The names of the variables live in one place: ``api_key_variables`` of the ``ProviderProfile`` that the provider is registered with. Nothing else
holds a table of them. ``auth``, the router and the adapters call these functions with the name of the provider.

Raises: nothing; a provider with no profile, or a profile with no variable, gives an empty tuple and no key.
Missing: the functions never read a file; they read the registrar and the process environment.
Concurrency: a read of the registrar takes no lock; the environment is read at each call.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from skye.base.plugins import Registrar, get_registrar

__all__ = ["api_key_from_environment", "api_key_variable", "api_key_variables"]


def api_key_variables(provider: str, registrar: Registrar | None = None) -> tuple[str, ...]:
    """The variables that hold the key of ``provider``, in the order they are read; empty when it has none.

    Args:
        provider: The registered name of the provider, for example ``"openai"``.
        registrar: The registrar to read; the default registrar of the process when omitted.

    Returns:
        ``api_key_variables`` of the profile of ``provider``.
    """
    profile = (registrar or get_registrar()).get_profile(provider)
    return tuple(profile.api_key_variables) if profile is not None else ()


def api_key_variable(provider: str, registrar: Registrar | None = None) -> str | None:
    """The first variable that holds the key of ``provider`` (the one an error names), or ``None`` when it has none."""
    variables = api_key_variables(provider, registrar)
    return variables[0] if variables else None


def api_key_from_environment(
    provider: str,
    environ: Mapping[str, str] | None = None,
    registrar: Registrar | None = None,
) -> str | None:
    """The key of ``provider`` from the environment: the value of the first variable of its profile that is set and not empty.

    Args:
        provider: The registered name of the provider.
        environ: The mapping to read; ``os.environ`` when omitted.
        registrar: The registrar to read; the default registrar of the process when omitted.

    Returns:
        The key, or ``None`` when the provider has no variable or none is set.

    Example:
        >>> api_key_from_environment("openai", {"OPENAI_API_KEY": "sk-1"})
        'sk-1'
    """
    source = os.environ if environ is None else environ
    for name in api_key_variables(provider, registrar):
        value = source.get(name)
        if value:
            return value
    return None
