# Requirement 59, plugins:3.1, Requirement 59.10
"""The provider profile: everything that is specific to one provider, declared once (to 3.3).

A ``ProviderProfile`` is registered with the provider class (``registrar.provider(name, cls,
profile=...)``). Cost, token counting,
the router and ``auth`` read it instead of keeping a table of their own. ``ModelProfile`` is the
entry of one model, ``RegionRule`` says
where the region comes from, ``find_model_profile`` finds the entry of a model name and
``resolve_region`` applies the rule.

A profile is data and references to functions: frozen, with its mappings read-only. Nothing in it is
looked at until a component asks, so
a provider with no profile, or a model that the profile lacks, is not an error: the cost is unknown
(``None``), the token count is the
standard-library estimate and ``get_model_info()`` returns what the adapter knows.

Raises: ``ValidationError`` for an invalid field (a negative price or overhead, an empty name);
``ConfigurationError`` from ``resolve_region``
    when a required region is not found, naming the variables.
Missing: ``find_model_profile`` returns ``None`` for no profile or an unknown model;
``resolve_region`` returns ``None`` when the rule is
    absent or the region is optional and not found. There is never a default region.
Concurrency: profiles are immutable and shared freely between threads and tasks.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from skye.base.exceptions import ConfigurationError, ProviderError, ValidationError


def _frozen(mapping: Mapping[Any, Any] | None) -> Mapping[Any, Any]:
    """A read-only copy of ``mapping``."""
    return MappingProxyType(dict(mapping or {}))


def _price(name: str, value: Any) -> None:
    if value is None:
        return
    if (
        isinstance(value, bool) or not isinstance(value, int | float) or not value >= 0
    ):  # `not >=` also refuses NaN
        raise ValidationError(
            f"{name} must be 0 or more (USD per 1M tokens), or None when unknown; got {value!r}",
            name,
            value,
        )


# Requirement 59.2
@dataclass(frozen=True)
class ModelProfile:
    """What is known about one model of a provider.

    Attributes:
        prompt_price: USD per 1M input tokens, 0 or more, ``None`` when unknown.
        completion_price: USD per 1M output tokens, 0 or more, ``None`` when unknown.
        tokenizer: ``None``, or the name of a tokenizer registered with ``registrar.tokenizer``.
        message_overhead: Tokens added per message, 0 or more.
        info: Merged into the result of ``get_model_info()``, for example
            ``{"supports_structured_output": True}``.
    """

    prompt_price: float | None = None
    completion_price: float | None = None
    tokenizer: str | None = None
    message_overhead: int = 0
    info: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _price("prompt_price", self.prompt_price)
        _price("completion_price", self.completion_price)
        if self.tokenizer is not None and (
            not isinstance(self.tokenizer, str) or not self.tokenizer
        ):
            raise ValidationError(
                f"tokenizer must be None or a non-empty name; got {self.tokenizer!r}",
                "tokenizer",
                self.tokenizer,
            )
        overhead = self.message_overhead
        if isinstance(overhead, bool) or not isinstance(overhead, int) or overhead < 0:
            raise ValidationError(
                f"message_overhead must be an integer of 0 or more; got {overhead!r}",
                "message_overhead",
                overhead,
            )
        object.__setattr__(self, "info", _frozen(self.info))


# Requirement 59.5
@dataclass(frozen=True)
class RegionRule:
    """Where the region of a provider comes from.

    Attributes:
        variables: The environment variables that hold the region, read in order.
        required: When true and no region is found, ``resolve_region`` raises.
    """

    variables: tuple[str, ...]
    required: bool = True

    def __post_init__(self) -> None:
        variables = (self.variables,) if isinstance(self.variables, str) else tuple(self.variables)
        if not all(isinstance(v, str) and v for v in variables):
            raise ValidationError(
                f"the region variables must be non-empty names; got {self.variables!r}",
                "variables",
                self.variables,
            )
        object.__setattr__(self, "variables", variables)


# Requirement 59.1, Requirement 11.6
@dataclass(frozen=True)
class ProviderProfile:
    """Everything specific to one provider, declared once.

    Attributes:
        name: The provider name, the one the registrar and ``skye.provider`` use.
        api_key_variables: The variables that hold the API key, read in order; the provider-standard
            names.
        region: A ``RegionRule``, or ``None`` when the provider has no region.
        default_api_base: The endpoint used when none is given.
        client_settings: Renames a generic setting to the name the provider uses, for example
            ``{"api_base": "azure_endpoint"}``.
        model_is_deployment: The model name is a deployment name (Azure).
        models: A model name mapped to its ``ModelProfile``.
        map_error: A function that turns a failed response into a ``ProviderError``, or a
            ``"module:attribute"`` text for it.
    """

    name: str
    api_key_variables: tuple[str, ...] = ()
    region: RegionRule | None = None
    default_api_base: str | None = None
    client_settings: Mapping[str, str] = field(default_factory=dict)
    model_is_deployment: bool = False
    models: Mapping[str, ModelProfile] = field(default_factory=dict)
    map_error: Callable[..., ProviderError] | str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValidationError(
                f"the name of a provider profile must be a non-empty string; got {self.name!r}",
                "name",
                self.name,
            )
        variables = (
            (self.api_key_variables,)
            if isinstance(self.api_key_variables, str)
            else tuple(self.api_key_variables)
        )
        if not all(isinstance(v, str) and v for v in variables):
            raise ValidationError(
                f"api_key_variables of {self.name!r} must be non-empty names; got "
                f"{self.api_key_variables!r}",
                "api_key_variables",
                self.api_key_variables,
            )
        if self.region is not None and not isinstance(self.region, RegionRule):
            raise ValidationError(
                f"region of {self.name!r} must be a RegionRule or None; got {self.region!r}",
                "region",
                self.region,
            )
        bad = [
            k
            for k, v in self.models.items()
            if not isinstance(k, str) or not k or not isinstance(v, ModelProfile)
        ]
        if bad:
            raise ValidationError(
                f"models of {self.name!r} must map a name to a ModelProfile; bad entries: {bad!r}",
                "models",
                bad,
            )
        object.__setattr__(self, "api_key_variables", variables)
        object.__setattr__(self, "client_settings", _frozen(self.client_settings))
        object.__setattr__(self, "models", _frozen(self.models))


_PROFILE_KEYS = {
    "name",
    "api_key_variables",
    "default_api_base",
    "model_is_deployment",
    "map_error",
    "region",
    "client_settings",
    "models",
}
_MODEL_KEYS = {"prompt_price", "completion_price", "tokenizer", "message_overhead", "info"}
_REGION_KEYS = {"variables", "required"}


def _check_keys(where: str, table: Mapping[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise ConfigurationError(
            f"{where}: unknown key(s) {', '.join(unknown)}; the keys are "
            f"{', '.join(sorted(allowed))}",
            {"where": where, "unknown": unknown},
        )


def profile_from_mapping(data: Mapping[str, Any], source: str = "profile") -> ProviderProfile:
    """Build a ``ProviderProfile`` from a plain mapping, such as the one a TOML file decodes to.

    The keys are the fields of ``ProviderProfile``; ``region`` is a table with ``variables`` and
    ``required``, ``client_settings`` a table,
    and ``models`` a table of ``ModelProfile`` tables (``prompt_price``, ``completion_price``,
    ``tokenizer``, ``message_overhead``, ``info``).
    Reading the file is not done here, because ``base`` does no file I/O: the owner of the file
    decodes it and passes the mapping.

    Raises:
        ConfigurationError: A key the format does not know (a typo is not silently ignored), or a
            table of the wrong shape; ``source`` is named.
        ValidationError: A value the dataclasses refuse, such as a negative price.
    """
    _check_keys(source, data, _PROFILE_KEYS)
    if "name" not in data:
        raise ConfigurationError(f"{source}: the key 'name' is required", {"where": source})
    region = None
    if "region" in data:
        _check_keys(f"{source} [region]", data["region"], _REGION_KEYS)
        region = RegionRule(
            tuple(data["region"].get("variables", ())), data["region"].get("required", True)
        )
    models: dict[str, ModelProfile] = {}
    for model, table in data.get("models", {}).items():
        _check_keys(f"{source} [models.{model!r}]", table, _MODEL_KEYS)
        models[model] = ModelProfile(**table)
    fields = {k: v for k, v in data.items() if k not in {"region", "models"}}
    return ProviderProfile(region=region, models=models, **fields)


# A name that continues a registered one with a date or a version: -2024-08-06, -20240620, -0613,
# -v1:0, @001, the alias -latest (and runs of them, as in
# a Bedrock id: -20240620-v1:0). Anything else, such as the "o" of gpt-4o after gpt-4, is a
# different model.
_SUFFIX = re.compile(r"^(?:-(?:\d{4}-\d{2}-\d{2}|\d{8}|\d{4}|v\d+(?::\d+)?|latest)|@\d+)+$")


# : The Skye-level name of the setting that carries a deployment name; ``client_settings`` of a
# profile renames it when the provider calls it otherwise.
DEPLOYMENT_SETTING = "deployment_name"


# Requirement 60.4
def apply_client_settings(
    profile: ProviderProfile | None, model: str, config: Mapping[str, Any]
) -> dict[str, Any]:
    """The configuration of a client, with the names the provider of ``profile`` uses.

    ``config`` holds the generic settings (``api_base``, ``api_key``, ...). When the profile says
    the model is a deployment
    (``model_is_deployment``), the name of ``model`` is added as the ``deployment_name`` setting
    unless ``config`` already has one; then every setting
    that ``client_settings`` renames takes its new name, for example ``api_base`` becomes
    ``azure_endpoint``. A setting not named by the profile is
    kept as it is, and ``config`` is not modified. No profile, no change: that is a provider with
    nothing special.
    """
    settings = dict(config)
    if profile is None:
        return settings
    if profile.model_is_deployment:
        settings.setdefault(DEPLOYMENT_SETTING, model)
    rename = profile.client_settings
    return {rename.get(key, key): value for key, value in settings.items()}


# Requirement 59.10
def find_model_profile(profile: ProviderProfile | None, model: str) -> ModelProfile | None:
    """The ``ModelProfile`` of ``model``: the exact name first, then the longest registered name
    followed by a date or version suffix.

    ``gpt-4o`` never matches ``gpt-4``, because ``o`` is not a date or a version. ``None`` when the
    provider has no profile or the model is
    not in it; that is not an error.
    """
    if profile is None or not isinstance(model, str) or not model:
        return None
    found = profile.models.get(model)
    if found is not None:
        return found
    for name in sorted(profile.models, key=len, reverse=True):
        if model.startswith(name) and _SUFFIX.match(model[len(name) :]):
            return profile.models[name]
    return None


# Requirement 59.5, Requirement 59.6
def resolve_region(
    rule: RegionRule | None,
    passed: str | None = None,
    authenticator: Any | None = None,
    environ: Mapping[str, str] | None = None,
) -> str | None:
    """The region for a provider: the one passed, then the authenticator's, then the variables of
    ``rule`` in order.

    Args:
        rule: The provider's ``RegionRule``, or ``None`` for a provider with no region.
        passed: A region given by the caller.
        authenticator: An object with a ``region`` attribute, as the authenticators of ``auth``
            have.
        environ: The environment to read; ``os.environ`` when omitted.

    Returns:
        The region, or ``None`` when none is found and the region is not required.

    Raises:
        ConfigurationError: A required region is not found; the error names the variables. There is
            no default region.
    """
    if passed:
        return passed
    from_authenticator = getattr(authenticator, "region", None)
    if isinstance(from_authenticator, str) and from_authenticator:
        return from_authenticator
    if rule is None:
        return None
    env = os.environ if environ is None else environ
    for variable in rule.variables:
        value = env.get(variable)
        if value:
            return value
    if rule.required:
        raise ConfigurationError(
            f"no region found: pass one or set {' or '.join(rule.variables)}",
            {"variables": list(rule.variables)},
        )
    return None
