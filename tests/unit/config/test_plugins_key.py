"""The ``plugins`` key: the allowlist of the entry points that may load (plugins:4.3, Requirement 57.5, D91, D106)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from skye.base.config import ConfigLoader, SkyeConfig
from skye.base.exceptions import ConfigurationError, ValidationError
from skye.utils.config_files import configured_plugins, load_config


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "skye.json"
    path.write_text(body, encoding="utf-8")
    return path


def test_the_default_is_no_allowlist() -> None:
    assert SkyeConfig().plugins is None


def test_the_key_is_read_from_a_file(tmp_path: Path) -> None:
    assert load_config(write(tmp_path, '{"plugins": ["acme", "weather"]}')).plugins == [
        "acme",
        "weather",
    ]


def test_an_empty_list_is_kept_and_means_none_may_load(tmp_path: Path) -> None:
    assert load_config(write(tmp_path, '{"plugins": []}')).plugins == []


def test_plugins_is_a_known_key() -> None:
    """It is a field again, so the unknown-key check of D106 does not name it."""
    assert ConfigLoader.from_text('{"plugins": ["a"]}', source="skye.json").plugins == ["a"]


@pytest.mark.parametrize("value", ['"acme"', "[1]", '[""]', '["  "]', '{"a": 1}', "7", "true"])
def test_a_value_that_is_not_a_list_of_names_is_a_configuration_error_naming_the_key(
    value: str,
) -> None:
    with pytest.raises(ConfigurationError) as caught:
        ConfigLoader.from_text(f'{{"plugins": {value}}}', source="skye.json")
    assert "plugins" in str(caught.value.details["validation_errors"])


def test_the_dataclass_refuses_an_empty_name() -> None:
    with pytest.raises(ValidationError):
        SkyeConfig(plugins=["ok", ""])


def test_an_override_wins_over_the_file(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, '{"plugins": ["a"]}'), overrides={"plugins": ["b"]})
    assert config.plugins == ["b"]


# -- configured_plugins: the allowlist alone, with no side effect -------------------------------------------------


def test_no_file_is_no_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SKYE_CONFIG", raising=False)
    assert configured_plugins() is None


def test_a_file_without_the_key_is_no_allowlist(tmp_path: Path) -> None:
    assert configured_plugins(write(tmp_path, '{"log_level": "INFO"}')) is None


def test_it_reads_the_file_that_skye_config_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SKYE_CONFIG", str(write(tmp_path, '{"plugins": ["a"]}')))
    assert configured_plugins() == ["a"]


def test_it_applies_no_log_level(tmp_path: Path) -> None:
    logger = logging.getLogger("skye")
    before = logger.level
    logger.setLevel(logging.DEBUG)
    try:
        configured_plugins(write(tmp_path, '{"log_level": "ERROR", "plugins": ["a"]}'))
        assert logger.level == logging.DEBUG
        load_config(tmp_path / "skye.json")  # load_config does apply it
        assert logger.level == logging.ERROR
    finally:
        logger.setLevel(before)


def test_a_missing_file_is_a_configuration_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="not found"):
        configured_plugins(tmp_path / "nope.json")


def test_a_bad_key_in_the_file_is_still_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="enable_fallbacks"):
        configured_plugins(write(tmp_path, '{"enable_fallbacks": true}'))
