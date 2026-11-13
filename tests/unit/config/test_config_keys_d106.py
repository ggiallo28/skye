"""Configuration keys that nothing reads are removed, and an unknown key is an error (D106)."""

from __future__ import annotations

import dataclasses
import logging
from pathlib import Path

import pytest

from skye.base.config import ALL_ENV_VARS, ConfigLoader, SkyeConfig, substitute_env_vars
from skye.base.exceptions import ConfigurationError
from skye.utils.config_files import load_config

REMOVED = [
    "enable_telemetry",
    "default_routing_strategy",
    "enable_fallbacks",
    "enable_rate_limiting",
    "models",
]


@pytest.mark.parametrize("key", REMOVED)
def test_the_unread_keys_are_not_fields(key: str) -> None:
    assert key not in {f.name for f in dataclasses.fields(SkyeConfig)}


def test_the_fields_left() -> None:
    assert [f.name for f in dataclasses.fields(SkyeConfig)] == [
        "log_level",
        "correlation_id_header",
        "component_log_levels",
        "plugins",  # came back with the code that reads it: the plugin scan (plugins:4.3, D106)
    ]


@pytest.mark.parametrize("key", [*REMOVED, "log_levle"])
def test_an_unknown_key_in_a_file_is_a_configuration_error_naming_it(
    key: str, tmp_path: Path
) -> None:
    path = tmp_path / "skye.json"
    path.write_text(f'{{"log_level": "INFO", "{key}": true}}', encoding="utf-8")
    with pytest.raises(ConfigurationError, match=key) as info:
        load_config(path)
    assert info.value.details["unknown_keys"] == [key]
    with pytest.raises(ConfigurationError, match=key):
        ConfigLoader.from_text(f'{{"{key}": 1}}', source="skye.json")


def test_an_unknown_override_is_a_configuration_error() -> None:
    with pytest.raises(ConfigurationError, match="enable_fallbacks"):
        ConfigLoader.load(overrides={"enable_fallbacks": False})


def test_a_removed_keyword_is_refused_by_the_dataclass() -> None:
    with pytest.raises((TypeError, ValueError)):
        SkyeConfig(enable_telemetry=True)  # type: ignore[call-arg]


def test_load_config_applies_the_log_levels(tmp_path: Path) -> None:
    path = tmp_path / "skye.json"
    path.write_text(
        '{"log_level": "WARNING", "component_log_levels": {"router": "DEBUG"}}', encoding="utf-8"
    )
    logging.getLogger("skye").setLevel(logging.NOTSET)
    logging.getLogger("skye.router").setLevel(logging.NOTSET)
    load_config(path)
    assert logging.getLogger("skye").level == logging.WARNING
    assert logging.getLogger("skye.router").level == logging.DEBUG


def test_load_config_without_a_file_applies_the_log_levels() -> None:
    logging.getLogger("skye").setLevel(logging.NOTSET)
    load_config(overrides={"log_level": "ERROR"})
    assert logging.getLogger("skye").level == logging.ERROR


def test_the_skye_prefixed_variables_are_the_two_left() -> None:
    assert ALL_ENV_VARS == {"SKYE_LOG_LEVEL", "SKYE_CONFIG"}


def test_substitute_env_vars_docstring_does_not_promise_a_cache() -> None:
    """D66 removed the cache of environment lookups."""
    assert "cach" not in (substitute_env_vars.__doc__ or "").lower()
