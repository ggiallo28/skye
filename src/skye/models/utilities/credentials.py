# D18, Requirement 11.6, task 6.3
"""The API key and the AWS region of a client: the one passed, or the variable of the profile.

The key variables are the ``api_key_variables`` of the profile of the provider: the provider-standard
variable, never a prefixed one. A missing key or region raises ``ConfigurationError`` naming the variable, never a value.
"""

from __future__ import annotations

import os
from typing import Any

from skye.base.exceptions import ConfigurationError
from skye.base.regions import region_for


def resolve_api_key(api_key: str | None, env_var: str | tuple[str, ...] | None) -> str:
    """The key to use: ``api_key`` when given, else the value of the first variable of ``env_var`` that is set.

    Args:
        api_key: The key passed by the caller, or ``None``.
        env_var: The variables of the profile of the provider (``api_key_variables``, in the order they are read), one name,
            or ``None`` or empty when the provider has none (the key must be passed).

    Returns:
        The key.

    Raises:
        ConfigurationError: Neither is set; the message names the variables.
    """
    if api_key:
        return api_key
    variables = (env_var,) if isinstance(env_var, str) else tuple(env_var or ())
    for name in variables:
        key = os.environ.get(name)
        if key:
            return key
    if variables:
        return _raise_missing(variables)
    raise ConfigurationError("No API key: pass api_key", details={"variable": None})


def _raise_missing(variables: tuple[str, ...]) -> str:
    raise ConfigurationError(
        f"No API key: pass api_key or set {' or '.join(variables)}", details={"variable": variables[0]}
    )


def resolve_aws_region(region: str | None, authenticator: Any = None) -> str:
    """The AWS region: the one given, the authenticator's ``region``, then the variables of the ``bedrock`` profile.

    The names of the variables are in ``[region]`` of ``models/plugins/bedrock/profile.toml``, and ``region_for`` reads them.

    Raises:
        ConfigurationError: None is set; the message names the variables (no silent default).
    """
    found = region_for("bedrock", region, authenticator, required=True)
    assert found is not None  # a required region is found or the call raised
    return found


__all__ = ["resolve_api_key", "resolve_aws_region"]
