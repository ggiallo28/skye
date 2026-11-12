"""Read the configuration file of the library: the one place that opens it.

``skye.base.config.ConfigLoader`` takes text and opens no file, because ``base`` does no file I/O
(Requirement 3.2, decision D91). This module opens the file, the same way ``skye_files`` opens the
``.skye`` files for ``skye.base.dsl``, and is public as ``skye.load_config``. The file is JSON in
version 1 (decision D92); YAML is refused (decision D62).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from skye.base.config import ConfigLoader, SkyeConfig, reject_yaml
from skye.base.exceptions import ConfigurationError
from skye.utils.skye_files import read_text


def _read_config(path: str | Path | None, overrides: dict[str, Any] | None) -> SkyeConfig:
    """Read and validate the configuration, touching no logger: the one reader that ``load_config`` and ``configured_plugins`` share."""
    if path is None:
        path = ConfigLoader.config_path_from_env()
        if path is None:
            return ConfigLoader.from_dict({}, overrides)
    target = Path(path)
    reject_yaml(target)  # say it plainly: the library reads no YAML (D62)
    if target.suffix.lower() != ".json":
        raise ConfigurationError(
            f"Unsupported configuration file format: {target.suffix or '(none)'};"
            " the configuration file is JSON.",
            details={"path": str(target), "suffix": target.suffix, "supported": [".json"]},
        )
    if not target.exists():
        raise ConfigurationError(
            f"Configuration file not found: {target}", details={"path": str(target)}
        )
    return ConfigLoader.from_text(read_text(target), source=str(target), overrides=overrides)


def configured_plugins(path: str | Path | None = None) -> list[str] | None:
    """The ``plugins`` allowlist of the configuration, or ``None`` when there is no file or no such key (every entry point may load).

    The file is the one ``load_config`` reads (``path``, else the file ``SKYE_CONFIG`` names). Unlike ``load_config`` this applies no log level:
    the plugin scan runs at the first lookup that misses, and it must not change a logger the application has set.

    Raises:
        ConfigurationError: The file is missing, is not JSON, holds an unknown key, or a ``plugins`` that is not a list of non-empty strings.
    """
    return _read_config(path, None).plugins


def load_config(
    path: str | Path | None = None, *, overrides: dict[str, Any] | None = None
) -> SkyeConfig:
    """Load the configuration: the JSON file, then the ``SKYE_`` environment, then ``overrides``.

    The log levels read are applied (``SkyeConfig.apply_log_levels``): the ``skye`` logger takes
    ``log_level`` and each ``skye.<component>`` logger its entry of ``component_log_levels``
    (decision D106).

    Args:
        path: The JSON configuration file. When ``None``, the file that ``SKYE_CONFIG`` names is
            read, and with neither only the environment and ``overrides`` count.
        overrides: Values that win over the file and the environment.

    Returns:
        SkyeConfig: The validated configuration.

    Raises:
        ConfigurationError: If the file is YAML, is not ``.json``, is missing or unreadable, is not
            a JSON object, holds a key that is not a configuration key (the message names it), or
            the merged values do not validate.

    Example:
        >>> import skye
        >>> config = skye.load_config(overrides={"log_level": "DEBUG"})  # no file: environment, code
        >>> config.log_level
        'DEBUG'
    """
    config = _read_config(path, overrides)
    config.apply_log_levels()
    return config


__all__ = ["configured_plugins", "load_config"]
