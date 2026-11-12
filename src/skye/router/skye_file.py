"""Read a router from a file: a ``router`` block of a ``.skye`` file, or a JSON object (decisions
D59, D62).

``base`` parses the text and builds a :class:`~skye.base.dsl.RouterSpec`; this module turns that
spec into the dictionary that :meth:`ModelRouter.from_config_dict` already accepts, so a router has
one path from configuration to object whatever the format. The library reads no YAML: a ``.yaml`` or
``.yml`` file is rejected with a message that names the supported formats (Requirement 54.12).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, cast

from skye.base.config import reject_yaml, substitute_env_vars
from skye.base.dsl import (
    AllowedFailsPolicySpec,
    RetryPolicySpec,
    RouterSpec,
    RouteSpec,
    SkyeSyntaxError,
    TargetSpec,
    format_duration,
    parse_duration,
)
from skye.base.api_keys import api_key_variables
from skye.base.exceptions import ConfigurationError
from skye.utils.skye_files import load_document, read_text

_TARGET_FIELDS = (
    "model",
    "provider",
    "api_key",
    "api_base",
    "api_version",
    "region",
    "max_retries",
    "weight",
    "tpm",
    "rpm",
    "cost_per_1k_prompt_tokens",
    "cost_per_1k_completion_tokens",
)


def _target(target: Any) -> dict[str, Any]:
    out = {
        name: getattr(target, name) for name in _TARGET_FIELDS if getattr(target, name) is not None
    }
    if "api_key" not in out:
        for variable in api_key_variables(target.provider):
            if os.environ.get(variable):
                out["api_key"] = f"${{{variable}}}"
                break
    if target.timeout is not None:
        out["timeout"] = parse_duration(target.timeout)
    if target.tags:
        out["tags"] = list(target.tags)
    if target.metadata:
        out["metadata"] = dict(target.metadata)
    if target.options:
        out["options"] = dict(target.options)
    return out


def _retry_policy(policy: RetryPolicySpec) -> dict[str, Any]:
    """A retry policy of the block as a dictionary (``retry_after = "5s"`` is ``retry_after_seconds``)."""
    out: dict[str, Any] = {"error_type": policy.error_type, "max_retries": policy.max_retries}
    if policy.retry_after is not None:
        out["retry_after_seconds"] = parse_duration(policy.retry_after)
    if policy.exponential_backoff:
        out["exponential_backoff"] = True
    return out


def router_spec_to_config(spec: RouterSpec) -> dict[str, Any]:
    """The configuration dictionary of a router block, ``${NAME}`` references left in place.

    The shorthand ``route "x" = ["provider/model", ...]`` gives the first entry to the route and one
    route ``x/fallback<N>`` to each of the others, chained as the fallbacks of ``x`` (as the
    dictionary shorthand of ``ModelRouter`` does); a ``fallback = [...]`` written in the route is
    added after them.
    """
    routes: list[dict[str, Any]] = []
    fallbacks: list[dict[str, Any]] = []
    for route in spec.routes:
        entry: dict[str, Any] = {
            "alias": route.alias,
            "targets": [_target(t) for t in route.targets],
            "fallback_on_error": route.fallback_on_error,
        }
        if route.strategy:
            entry["strategy"] = route.strategy
        routes.append(entry)
        names: list[str] = []
        for number, target in enumerate(route.fallback_targets, start=1):
            name = f"{route.alias}/fallback{number}"
            routes.append({"alias": name, "targets": [_target(target)]})
            names.append(name)
        names.extend(route.fallback)
        if names:
            fallbacks.append({"primary": route.alias, "fallbacks": names})
    config: dict[str, Any] = {
        "routes": routes,
        "fallbacks": fallbacks,
        "enable_pre_call_checks": spec.enable_pre_call_checks,
        "retry_policies": [_retry_policy(p) for p in spec.retry_policies],
        "allowed_fails_policies": [
            {"error_type": p.error_type, "allowed_fails_per_minute": p.allowed_fails_per_minute}
            for p in spec.allowed_fails_policies
        ],
    }
    if spec.strategy:
        config["strategy"] = spec.strategy
    if spec.cooldown is not None:
        config["cooldown_seconds"] = parse_duration(spec.cooldown)
    return config


_TARGET_SPEC_FIELDS = (
    "model",
    "provider",
    "api_key",
    "api_base",
    "api_version",
    "region",
    "max_retries",
    "weight",
    "tpm",
    "rpm",
    "cost_per_1k_prompt_tokens",
    "cost_per_1k_completion_tokens",
    "tags",
    "metadata",
    "options",
)


def _target_spec(target: dict[str, Any]) -> TargetSpec:
    fields = {name: target[name] for name in _TARGET_SPEC_FIELDS if name in target}
    if target.get("timeout") is not None:
        fields["timeout"] = format_duration(float(target["timeout"]))
    return TargetSpec(**fields)


def config_to_router_spec(config: dict[str, Any], name: str | None = None) -> RouterSpec:
    """The ``router`` block model of a configuration dictionary (the opposite of
    :func:`router_spec_to_config`).

    A route's strategy is kept only when it differs from the router's, the cooldown only when it is
    not 60 seconds, and ``fallbacks`` entries become the ``fallback`` list of their route. Fields a
    block cannot hold (extra fields of a target) are dropped. ``${NAME}`` strings stay as they are; ``skye.base.dsl.to_text``
    writes them as ``env.NAME``.

    Args:
        config: A dictionary in the shape of ``ModelRouter.to_config()``.
        name: The label of the block.
    """
    default = str(config.get("strategy", "round_robin"))
    chains = {
        str(entry["primary"]): list(entry["fallbacks"]) for entry in config.get("fallbacks", [])
    }
    routes: list[RouteSpec] = []
    for entry in config.get("routes", []):
        alias = str(entry["alias"])
        strategy = str(entry.get("strategy", default))
        routes.append(
            RouteSpec(
                alias=alias,
                targets=[_target_spec(t) for t in entry.get("targets", [])],
                strategy=cast(
                    Any, strategy if strategy != default else None
                ),  # checked by the model
                fallback_on_error=bool(entry.get("fallback_on_error", True)),
                fallback=chains.get(alias, []),
            )
        )
    cooldown = float(config.get("cooldown_seconds", 60.0))
    return RouterSpec(
        name=name,
        strategy=cast(Any, default if default != "round_robin" else None),  # checked by the model
        cooldown=format_duration(cooldown) if cooldown != 60.0 else None,
        enable_pre_call_checks=bool(config.get("enable_pre_call_checks", True)),
        routes=routes,
        retry_policies=[
            RetryPolicySpec(
                error_type=p["error_type"],
                max_retries=p["max_retries"],
                retry_after=(
                    format_duration(float(p["retry_after_seconds"]))
                    if p.get("retry_after_seconds") is not None
                    else None
                ),
                exponential_backoff=bool(p.get("exponential_backoff", False)),
            )
            for p in config.get("retry_policies", [])
        ],
        allowed_fails_policies=[
            AllowedFailsPolicySpec(
                error_type=p["error_type"], allowed_fails_per_minute=p["allowed_fails_per_minute"]
            )
            for p in config.get("allowed_fails_policies", [])
        ],
    )


def load_router_config(
    path: str | Path, name: str | None = None, *, keep_target_references: bool = False
) -> dict[str, Any]:
    """Read a router configuration dictionary from a ``.skye`` or JSON file, with ``${NAME}``
    substituted.

    Args:
        path: A ``.skye`` file (its ``router`` block) or a JSON file holding the configuration
            object.
        name: The label of the router block when a ``.skye`` file holds several.
        keep_target_references: Leave ``${NAME}`` in the string fields of the targets
            (``ModelTarget`` substitutes them and remembers them as written, so that
            ``ModelRouter.to_config`` and ``to_skye`` can write ``env.NAME`` back).
            ``ModelRouter.from_file`` sets it; the default returns every value substituted.

    Raises:
        ConfigurationError: If the file is missing, is YAML, does not parse, or names a variable
            that is not set.
    """
    path = Path(path)
    if not path.exists():
        raise ConfigurationError(
            f"Router configuration file not found: {path}", details={"path": str(path)}
        )
    reject_yaml(path)
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(read_text(path))
        except json.JSONDecodeError as e:
            raise ConfigurationError(
                f"Failed to parse JSON configuration file: {path}",
                details={"path": str(path), "error": str(e)},
            ) from e
        if not isinstance(data, dict):
            raise ConfigurationError(
                "Router configuration file must contain an object at root level",
                details={"path": str(path), "type": type(data).__name__},
            )
        config: dict[str, Any] = data
    elif path.suffix.lower() == ".skye":
        try:
            # From memory when the file did not change (skye.utils.skye_files); the document is
            # read-only, the dictionary is new.
            document = load_document(path).raise_for_errors()
            config = router_spec_to_config(document.router(name))
        except SkyeSyntaxError as e:
            raise ConfigurationError(str(e), details={"path": str(path)}) from e
        except KeyError as e:
            raise ConfigurationError(str(e.args[0]), details={"path": str(path)}) from e
    else:
        raise ConfigurationError(
            f"Unsupported router configuration file: {path.name}. Use a .skye or a .json file.",
            details={"path": str(path), "supported": [".skye", ".json"]},
        )
    if keep_target_references:
        return substitute_env_vars_keeping_target_references(config)
    substituted: dict[str, Any] = substitute_env_vars(config)
    return substituted


#: The string fields of a target that ``ModelTarget`` substitutes itself (and remembers as written,
#: for ``to_skye``).
_TARGET_STRING_FIELDS = ("model", "provider", "api_key", "api_base", "api_version", "region")


def substitute_env_vars_keeping_target_references(config: dict[str, Any]) -> dict[str, Any]:
    """Replace ``${NAME}`` everywhere in a router configuration except in the string fields of the
    targets.

    ``ModelTarget`` substitutes those itself and remembers the reference as written (``env_refs``),
    which is what lets ``ModelRouter.to_config`` and ``to_skye`` write ``env.NAME`` back instead of
    the secret. The result is the same router.
    """
    held: list[tuple[int, int, dict[str, str], dict[str, str]]] = []
    for r, route in enumerate(config.get("routes", [])):
        for t, target in enumerate(route.get("targets", [])):
            fields = {
                k: target[k]
                for k in _TARGET_STRING_FIELDS
                if isinstance(target.get(k), str) and "${" in target[k]
            }
            options = target.get("options")
            option_refs = {
                k: v
                for k, v in (options.items() if isinstance(options, dict) else ())
                if isinstance(v, str) and "${" in v
            }
            if fields or option_refs:
                held.append((r, t, fields, option_refs))
                for key in fields:
                    del target[key]
                if option_refs:
                    target["options"] = {k: v for k, v in options.items() if k not in option_refs}
    substituted: dict[str, Any] = substitute_env_vars(config)
    for r, t, fields, option_refs in held:
        target_out = substituted["routes"][r]["targets"][t]
        target_out.update(fields)
        if option_refs:
            target_out["options"] = {**target_out.get("options", {}), **option_refs}
    return substituted
