"""Configuration models and loading system for Skye.

This module provides dataclass models for configuring Skye components including
rate limiting, retries, cooldowns, model configurations, and global settings.
It also includes the ConfigLoader for loading configuration from multiple sources.

Example:
    >>> from skye.base.config import ModelConfig, RateLimitConfig
    >>>
    >>> # Create a model configuration with rate limits
    >>> config = ModelConfig(
    ...     model_id="gpt-4",
    ...     provider="openai",
    ...     rate_limits=RateLimitConfig(
    ...         requests_per_minute=60,
    ...         tokens_per_minute=90000
    ...     )
    ... )
    >>> config.model_id
    'gpt-4'
"""

import dataclasses
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from skye.base.exceptions import ConfigurationError, ValidationError
from skye.base.validated import Validated, field, validated

# Set up module logger
logger = logging.getLogger(__name__)


# decision D62
def reject_yaml(path: str | Path) -> None:
    """Raise ``ConfigurationError`` when ``path`` is a YAML file: the library reads no YAML.

    Args:
        path: The configuration file about to be read.

    Raises:
        ConfigurationError: If the suffix is ``.yaml`` or ``.yml``; the message names the supported formats.
    """
    suffix = Path(path).suffix.lower()
    if suffix in (".yaml", ".yml"):
        raise ConfigurationError(
            f"YAML is not read: {Path(path).name}. Rewrite the file as .skye or JSON.",
            details={"path": str(path), "supported": [".skye", ".json"]},
        )


# decision D66
def substitute_env_vars(config: dict[str, Any] | list[Any] | str | Any) -> Any:
    """Recursively substitute environment variables in configuration.

    Substitutes ${VAR_NAME} patterns with environment variable values throughout
    the configuration structure. Supports nested dictionaries, lists, and strings.
    Each reference reads the environment when it is substituted, so a variable
    changed between two loads is seen by the second.

    Args:
        config: Configuration data (dict, list, str, or other type).

    Returns:
        Configuration data with environment variables substituted.

    Raises:
        ConfigurationError: If a referenced environment variable is not found.

    Example:
        >>> os.environ["API_KEY"] = "secret-key-123"
        >>> config = {"api_key": "${API_KEY}", "timeout": 30}
        >>> result = substitute_env_vars(config)
        >>> result["api_key"]
        'secret-key-123'
        >>> result["timeout"]
        30
    """
    if isinstance(config, dict):
        # Recursively substitute in dictionary values
        return {key: substitute_env_vars(value) for key, value in config.items()}
    elif isinstance(config, list):
        # Recursively substitute in list items
        return [substitute_env_vars(item) for item in config]
    elif isinstance(config, str):
        # Pattern to match ${VAR_NAME}
        pattern = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

        def replace_var(match: re.Match[str]) -> str:
            var_name = match.group(1)

            # Get from environment
            value = os.getenv(var_name)
            if value is None:
                raise ConfigurationError(
                    f"Environment variable '${{{var_name}}}' not found",
                    details={"variable_name": var_name},
                )

            logger.debug(f"Substituted environment variable: {var_name}")
            return value

        return pattern.sub(replace_var, config)
    else:
        # Return non-string, non-dict, non-list values as-is
        return config


@validated
class RateLimitConfig(Validated):
    """Rate limit configuration for a model.

    Defines rate limiting constraints for API requests to prevent exceeding
    provider quotas. Supports both request-based and token-based limits
    at minute and day granularity.

    Attributes:
        requests_per_minute: Maximum number of requests allowed per minute.
        tokens_per_minute: Maximum number of tokens allowed per minute.
        requests_per_day: Maximum number of requests allowed per day.
        tokens_per_day: Maximum number of tokens allowed per day.

    Example:
        >>> rate_limits = RateLimitConfig(
        ...     requests_per_minute=60,
        ...     tokens_per_minute=90000,
        ...     requests_per_day=10000,
        ...     tokens_per_day=2000000
        ... )
        >>> rate_limits.requests_per_minute
        60
    """

    requests_per_minute: int | None = None
    tokens_per_minute: int | None = None
    requests_per_day: int | None = None
    tokens_per_day: int | None = None


@validated
class RetryConfig(Validated):
    """Retry configuration for a model.

    Defines retry behavior for failed API requests including maximum retry
    attempts, delay between retries, exponential backoff, and which error
    types should trigger retries.

    Attributes:
        max_retries: Maximum number of retry attempts.
        retry_after_seconds: Base delay in seconds between retry attempts.
        exponential_backoff: Whether to use exponential backoff for retries.
        retry_on_errors: List of error types that should trigger retries.

    Example:
        >>> retry_config = RetryConfig(
        ...     max_retries=3,
        ...     retry_after_seconds=5,
        ...     exponential_backoff=True,
        ...     retry_on_errors=["rate_limit", "timeout", "server_error"]
        ... )
        >>> retry_config.max_retries
        3
    """

    max_retries: int = 3
    retry_after_seconds: int = 5
    exponential_backoff: bool = True
    retry_on_errors: list[str] = field(
        default_factory=lambda: ["rate_limit", "timeout", "server_error"]
    )


@validated
class CooldownConfig(Validated):
    """Cooldown configuration for failed models.

    Defines cooldown behavior to temporarily disable models that experience
    repeated failures, preventing cascading failures and allowing time for
    recovery.

    Attributes:
        enabled: Whether cooldown is enabled.
        allowed_fails_per_minute: Number of failures allowed per minute before cooldown.
        cooldown_duration_seconds: Duration in seconds to keep model in cooldown.

    Example:
        >>> cooldown_config = CooldownConfig(
        ...     enabled=True,
        ...     allowed_fails_per_minute=3,
        ...     cooldown_duration_seconds=60
        ... )
        >>> cooldown_config.enabled
        True
    """

    enabled: bool = True
    allowed_fails_per_minute: int = 3
    cooldown_duration_seconds: int = 60


@validated
class ModelConfig(Validated):
    """Configuration for a model.

    Comprehensive configuration for an LLM model including provider details,
    API credentials, generation parameters, routing configuration, and cost tracking.

    Attributes:
        model_id: Unique identifier for the model (e.g., 'gpt-4', 'claude-3-sonnet').
        provider: Provider name (e.g., 'openai', 'anthropic', 'bedrock').
        api_key: API key for authentication (optional, can use environment variable).
        api_base: Base URL for API endpoint (optional, uses provider default).
        temperature: Default sampling temperature (0.0-2.0).
        max_tokens: Default maximum tokens to generate.
        timeout: Request timeout in seconds.
        rate_limits: Rate limiting configuration.
        retry_config: Retry configuration for failed requests.
        cooldown_config: Cooldown configuration for repeated failures.
        fallback_models: List of fallback model IDs to try if this model fails.
        weight: Weight for weighted routing strategies (higher = more traffic).
        priority: Priority for priority-based routing (higher = preferred).
        tags: Tags for tag-based routing and filtering.
        cost_per_1k_prompt_tokens: Cost per 1000 prompt tokens in USD.
        cost_per_1k_completion_tokens: Cost per 1000 completion tokens in USD.

    Example:
        >>> config = ModelConfig(
        ...     model_id="gpt-4",
        ...     provider="openai",
        ...     temperature=0.7,
        ...     max_tokens=2000,
        ...     rate_limits=RateLimitConfig(requests_per_minute=60),
        ...     fallback_models=["gpt-3.5-turbo"],
        ...     cost_per_1k_prompt_tokens=0.03,
        ...     cost_per_1k_completion_tokens=0.06
        ... )
        >>> config.model_id
        'gpt-4'
    """

    model_id: str
    provider: str
    api_key: str | None = None
    api_base: str | None = None
    temperature: float = 0.7
    max_tokens: int | None = None
    timeout: int = 60

    # Advanced routing features
    rate_limits: RateLimitConfig | None = None
    retry_config: RetryConfig = field(default_factory=RetryConfig)
    cooldown_config: CooldownConfig = field(default_factory=CooldownConfig)
    fallback_models: list[str] = field(default_factory=list)

    # Load balancing
    weight: float = 1.0
    priority: int = 0
    tags: list[str] = field(default_factory=list)

    # Cost tracking
    cost_per_1k_prompt_tokens: float | None = None
    cost_per_1k_completion_tokens: float | None = None


# decision D106, Requirement 57.5
@validated
class SkyeConfig(Validated):
    """Global Skye configuration.

    The settings of the library itself: the log levels and the correlation header. A key that
    nothing reads is not a field, and an unknown key in a configuration file is a
    ``ConfigurationError``; a key comes back only with the code that reads it.

    Attributes:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        correlation_id_header: HTTP header name for correlation IDs.
        component_log_levels: Log level per component, keyed by the component name (for example
            ``{"router": "DEBUG", "models": "WARNING"}``); a component not listed uses
            ``log_level``.
        plugins: The names of the installed plugins (entry points of the group ``skye.plugins``)
            that may load; ``None`` (no key) lets all of them load, ``[]`` lets none. Read by the
            scan of ``skye.utils.plugins``; an entry point not listed is never
            imported.

    Example:
        >>> config = SkyeConfig(log_level="INFO", component_log_levels={"router": "DEBUG"})
        >>> config.level_for("router")
        'DEBUG'
    """

    log_level: str = "INFO"
    correlation_id_header: str = "X-Correlation-ID"
    component_log_levels: dict[str, str] = field(default_factory=dict)
    plugins: list[str] | None = field(default=None, description="The entry points that may load")

    def __post_init__(self) -> None:
        """Validate the fields, then that every component log level is a standard level name and every plugin name a non-empty string."""
        super().__post_init__()
        if self.plugins is not None:
            for name in self.plugins:
                if not name.strip():
                    raise ValidationError(
                        "A plugin name in `plugins` must be a non-empty string",
                        field="plugins",
                        value=self.plugins,
                    )
        for component, level in self.component_log_levels.items():
            if not isinstance(logging.getLevelName(level.upper()), int):
                raise ValidationError(
                    f"Unknown log level {level!r} for component {component!r}",
                    field="component_log_levels",
                    value={component: level},
                )

    def level_for(self, component: str) -> str:
        """The log level of a component: its own if set, else the global ``log_level``.

        Args:
            component: The component name (``models``, ``router``, ``tools``, ...).
        """
        return self.component_log_levels.get(component, self.log_level).upper()

    def apply_log_levels(self) -> None:
        """Set the level of the ``skye`` logger and of each listed component logger (``skye.<component>``)."""
        logging.getLogger("skye").setLevel(self.log_level.upper())
        for component in self.component_log_levels:
            logging.getLogger(f"skye.{component}").setLevel(self.level_for(component))


@validated
class RouterConfig(Validated):
    """Complete router configuration.

    This model represents a complete router configuration that can be loaded
    from a file. It includes routes, fallbacks, retry policies, and other
    router settings.

    Attributes:
        routes: List of route configurations with aliases and targets.
        fallbacks: List of fallback configurations defining fallback chains.
        retry_policies: List of retry policy configurations per error type.
        allowed_fails_policies: List of allowed fails policies before cooldown.
        strategy: Default routing strategy for the router.
        cooldown_seconds: Default cooldown duration for failed models.
        enable_pre_call_checks: Whether to enable pre-call rate limit checks.

    Example:
        >>> config = RouterConfig(
        ...     routes=[
        ...         {
        ...             "alias": "gpt-3.5-turbo",
        ...             "targets": [
        ...                 {
        ...                     "model": "gpt-3.5-turbo",
        ...                     "provider": "openai",
        ...                     "api_key": "${OPENAI_API_KEY}",
        ...                     "tpm": 200000,
        ...                     "rpm": 2000
        ...                 }
        ...             ],
        ...             "strategy": "rate_limit_aware"
        ...         }
        ...     ],
        ...     fallbacks=[
        ...         {
        ...             "primary": "gpt-4",
        ...             "fallbacks": ["gpt-3.5-turbo"]
        ...         }
        ...     ]
        ... )
    """

    routes: list[dict[str, Any]] = field(default_factory=list, description="Route configurations")
    fallbacks: list[dict[str, Any]] = field(
        default_factory=list, description="Fallback configurations"
    )
    retry_policies: list[dict[str, Any]] = field(
        default_factory=list, description="Retry policy configurations"
    )
    allowed_fails_policies: list[dict[str, Any]] = field(
        default_factory=list, description="Allowed fails policy configurations"
    )
    strategy: str = field("round_robin", description="Default routing strategy")
    cooldown_seconds: float = field(60.0, ge=0.0, description="Cooldown duration in seconds")
    enable_pre_call_checks: bool = field(True, description="Enable pre-call rate limit checks")


def _validation_errors(error: ValidationError) -> list[dict[str, Any]]:
    """The validation failure as a list of ``{type, loc, msg, input}`` entries (``loc`` is the field path)."""
    path = str(error.details.get("path", ""))
    loc = [part.strip("'\"") for part in re.split(r"[.\[\]]+", path) if part][1:]
    return [
        {
            "type": "value_error",
            "loc": loc or [str(error.details.get("field", ""))],
            "msg": error.message,
            "input": error.details.get("value"),
        }
    ]


#: The Skye-prefixed variables that set configuration values (SKYE_CONFIG selects the file).
ENV_CONFIG_VARS = frozenset({"SKYE_LOG_LEVEL"})
#: All Skye-prefixed environment variables: two (the telemetry variable left with its key, D106).
ALL_ENV_VARS = ENV_CONFIG_VARS | {"SKYE_CONFIG"}


# Requirement 3.2, D91
class ConfigLoader:
    """Builds the Skye configuration from the text of a file, the environment and code overrides.

    Precedence, highest first: code overrides, then the ``SKYE_`` environment variables, then the
    configuration file (JSON). This class takes the **text** of the file and opens nothing: ``base``
    does no file I/O. To read a file, call ``skye.load_config(path)``,
    which opens it (or the one ``SKYE_CONFIG`` names) and passes the text here.

    Example:
        >>> config = ConfigLoader.from_text('{"log_level": "DEBUG"}', source="skye.json")
        >>> config.log_level
        'DEBUG'
        >>> config = ConfigLoader.load(overrides={"log_level": "ERROR"})  # environment, code
        >>> config.log_level
        'ERROR'
    """

    @staticmethod
    def load(text: str | None = None, overrides: dict[str, Any] | None = None) -> SkyeConfig:
        """Build the configuration from a JSON text (optional), the environment and overrides.

        Args:
            text: The text of a JSON configuration file, or ``None`` for no file.
            overrides: Configuration values that win over the file and the environment.

        Returns:
            SkyeConfig: The validated configuration.

        Raises:
            ConfigurationError: If ``text`` is a path (read files with ``skye.load_config``), if
                ``text`` is not a JSON object, if ``SKYE_CONFIG`` names a file and no text is given,
                or if the merged values do not validate.

        Example:
            >>> ConfigLoader.load('{"log_level": "WARNING"}').log_level
            'WARNING'
        """
        if text is None:
            named = ConfigLoader.config_path_from_env()
            if named:
                raise ConfigurationError(
                    f"SKYE_CONFIG names a file ({named}); read it with skye.load_config(), "
                    "because ConfigLoader takes text and opens no file.",
                    details={"path": named},
                )
            return ConfigLoader.from_dict({}, overrides)
        return ConfigLoader.from_text(text, overrides=overrides)

    @staticmethod
    def from_text(
        text: str, *, source: str = "<text>", overrides: dict[str, Any] | None = None
    ) -> SkyeConfig:
        """Build the configuration from the text of a JSON file, then the environment and overrides.

        Args:
            text: The JSON text; empty text, or ``null``, means an empty file.
            source: Where the text came from (a file name), used in error messages.
            overrides: Configuration values that win over the file and the environment.

        Returns:
            SkyeConfig: The validated configuration.

        Raises:
            ConfigurationError: If ``text`` is a path, is not valid JSON, is not an object at the
                top level, or the merged values do not validate.
        """
        return ConfigLoader.from_dict(ConfigLoader.parse_text(text, source=source), overrides)

    @staticmethod
    def from_dict(data: dict[str, Any], overrides: dict[str, Any] | None = None) -> SkyeConfig:
        """Build the configuration from file values already read, the environment and overrides.

        Args:
            data: The values of the configuration file (``${VAR}`` is substituted here).
            overrides: Configuration values that win over the file and the environment.

        Returns:
            SkyeConfig: The validated configuration.

        Raises:
            ConfigurationError: If a key of ``data`` or ``overrides`` is not a configuration key
                (the message names it), or the merged values do not validate.
        """
        ConfigLoader._reject_unknown_keys(data, "configuration file")
        if overrides:
            ConfigLoader._reject_unknown_keys(overrides, "overrides")
        config_data: dict[str, Any] = dict(substitute_env_vars(dict(data)))
        # The environment wins over the file, and code overrides win over both.
        config_data.update(ConfigLoader._load_from_env())
        if overrides:
            config_data.update(substitute_env_vars(overrides))
        try:
            config: SkyeConfig = SkyeConfig.from_dict(config_data)
            return config
        except ValidationError as e:
            raise ConfigurationError(
                "Configuration validation failed",
                details={"validation_errors": _validation_errors(e)},
            ) from e

    # D106
    @staticmethod
    def _reject_unknown_keys(values: dict[str, Any], where: str) -> None:
        """Raise ``ConfigurationError`` naming each key of ``values`` that is not a field."""
        known = {f.name for f in dataclasses.fields(SkyeConfig)}
        unknown = sorted(key for key in values if key not in known)
        if unknown:
            raise ConfigurationError(
                f"Unknown configuration key{'s' if len(unknown) > 1 else ''} in {where}: "
                f"{', '.join(unknown)}. Known keys: {', '.join(sorted(known))}.",
                details={"unknown_keys": unknown, "known_keys": sorted(known)},
            )

    @staticmethod
    def parse_text(text: str, *, source: str = "<text>") -> dict[str, Any]:
        """The values of a JSON configuration text, as a dictionary.

        Args:
            text: The JSON text; empty text, or ``null``, gives an empty dictionary.
            source: Where the text came from, used in error messages.

        Returns:
            The values of the top-level object.

        Raises:
            ConfigurationError: If ``text`` is a path, is not valid JSON, or is not an object.
        """
        if isinstance(text, os.PathLike) or not isinstance(text, str):
            raise ConfigurationError(
                "ConfigLoader takes the text of the file, not a path;"
                " read a file with skye.load_config(path).",
                details={"given": type(text).__name__},
            )
        if not text.strip():
            return {}
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ConfigurationError(
                f"Failed to parse configuration file: {source}",
                details={"path": source, "error": str(e)},
            ) from e
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise ConfigurationError(
                "Configuration file must contain a dictionary/object at root level",
                details={"path": source, "type": type(data).__name__},
            )
        return data

    @staticmethod
    def config_path_from_env() -> str | None:
        """The file that ``SKYE_CONFIG`` names, or ``None``; nothing is opened here."""
        return os.environ.get("SKYE_CONFIG") or None

    # D106
    @staticmethod
    def _load_from_env() -> dict[str, Any]:
        """Load configuration from environment variables.

        Reads the Skye-prefixed variables that set configuration values and converts them
        to configuration keys. The prefix is removed and the key is lowercased. There are
        two Skye-prefixed variables: SKYE_LOG_LEVEL (read here) and SKYE_CONFIG (names the
        config file, which ``skye.load_config`` opens); the telemetry variable left with the
        ``enable_telemetry`` key. Provider credentials never come from a Skye-prefixed
        variable.

        For example:
            SKYE_LOG_LEVEL=DEBUG -> log_level: "DEBUG"

        Returns:
            Dictionary containing configuration data from environment variables.
        """
        config_data: dict[str, Any] = {}

        for key, value in os.environ.items():
            if key in ENV_CONFIG_VARS:
                # Remove SKYE_ prefix and convert to lowercase
                config_key = key[len("SKYE_") :].lower()

                # Try to parse boolean values
                if value.lower() in ["true", "false"]:
                    config_data[config_key] = value.lower() == "true"
                # Try to parse numeric values
                elif value.isdigit():
                    config_data[config_key] = int(value)
                elif value.replace(".", "", 1).isdigit():
                    config_data[config_key] = float(value)
                else:
                    config_data[config_key] = value

        return config_data
