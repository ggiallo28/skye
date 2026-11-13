# Requirements 60.6, 59.5, 59.6
"""The cloud region of a provider, read through the rule of its profile.

The names of the region variables live in one place: ``region`` of the ``ProviderProfile`` that the
provider is registered with (the
``[region]`` table of its ``profile.toml``). ``region_for`` reads that rule through the registrar
and applies ``resolve_region``: the region
passed, then the one of the authenticator, then the variables in order. AWS code outside a provider
(the credential sources of ``auth``, the
backends of ``store``) asks for the region of the profile ``"bedrock"``, the one AWS profile, so the
names are written once.

Raises: ``ConfigurationError`` when the region is required and none is found (the error names the
variables); there is no default region.
Missing: a provider with no profile or no region rule has no rule: the result is ``None``, or an
error when ``required`` is true.
Concurrency: a read of the registrar takes no lock; the environment is read at each call.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Any

from skye.base.exceptions import ConfigurationError
from skye.base.plugins import Registrar, get_registrar
from skye.base.profile import resolve_region

__all__ = ["region_for"]


def region_for(
    provider: str,
    passed: str | None = None,
    authenticator: Any | None = None,
    *,
    required: bool | None = None,
    environ: Mapping[str, str] | None = None,
    registrar: Registrar | None = None,
) -> str | None:
    """The region for ``provider``: the one passed, then the authenticator's, then the variables of
    its profile in order.

    Args:
        provider: The registered name whose profile holds the rule, for example ``"bedrock"``.
        passed: A region given by the caller.
        authenticator: An object with a ``region`` attribute, as the authenticators of ``auth``
            have.
        required: ``True`` to raise when none is found, ``False`` to return ``None``; the rule of
            the profile decides when omitted.
        environ: The environment to read; ``os.environ`` when omitted.
        registrar: The registrar to read; the default registrar of the process when omitted.

    Returns:
        The region, or ``None`` when none is found and it is not required.

    Raises:
        ConfigurationError: A required region is not found; the error names the variables (or says
            the provider has no region rule).

    Example:
        >>> region_for("bedrock", "eu-west-1")
        'eu-west-1'
    """
    if passed:
        return passed
    profile = (registrar or get_registrar()).get_profile(provider)
    rule = profile.region if profile is not None else None
    if rule is not None and required is not None and rule.required != required:
        rule = dataclasses.replace(rule, required=required)
    if rule is None and required:
        raise ConfigurationError(
            f"no region found: pass one; the provider {provider!r} has no region rule",
            {"provider": provider},
        )
    return resolve_region(rule, passed, authenticator, environ)
