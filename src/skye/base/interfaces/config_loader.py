"""Configuration loader interface for loading Skye configuration.

This module defines the abstract interface for loading configuration from
multiple sources with precedence handling.

Raises: ConfigurationError when the text is malformed or the merged values do not validate.
Missing: an absent environment variable falls back to the next source and to the default; no text means no file.
Concurrency: loading is read-only and safe to repeat; ``skye.config.ConfigLoader`` satisfies this Port structurally, with a static ``load``.
"""

from abc import ABC, abstractmethod
from typing import Any

from skye.base.config import SkyeConfig


class ConfigLoaderInterface(ABC):
    """Abstract interface for configuration loading.

    This interface defines the contract for loading configuration from
    multiple sources (files, environment variables, code overrides) with
    proper precedence handling.

    Example:
        >>> class MyConfigLoader(ConfigLoaderInterface):
        ...     def load(self, text=None, overrides=None):
        ...         # Implementation
        ...         return SkyeConfig()
    """

    # Requirement 3.2, decision D91
    @abstractmethod
    def load(self, text: str | None = None, overrides: dict[str, Any] | None = None) -> SkyeConfig:
        """Build the configuration from the text of a file, the environment and code overrides.

        Precedence: code > environment > file. The loader takes the text of the file and opens
        nothing; ``skye.load_config(path)`` reads a file.

        Args:
            text: The text of a JSON configuration file, or ``None`` for no file.
            overrides: Optional dictionary of configuration values to override.

        Returns:
            SkyeConfig: Validated configuration object.

        Raises:
            ConfigurationError: If configuration cannot be loaded or validated.

        Example:
            >>> config = loader.load('{"log_level": "INFO"}', overrides={"log_level": "DEBUG"})
        """
        pass
