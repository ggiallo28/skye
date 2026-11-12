"""Configuration: a file, environment variables and code overrides, in that order of precedence (code > environment > file).

The library reads two prefixed environment variables: ``SKYE_LOG_LEVEL`` and ``SKYE_CONFIG`` (the path of the configuration
file, JSON; the library reads no YAML). Provider credentials are never read from a prefixed variable: they come from each provider's
standard variable (``OPENAI_API_KEY``, ``AWS_*``, ...). Inside a file, ``${VAR}`` is replaced by the environment variable.
The file holds only the keys the library reads (``log_level``, ``component_log_levels``, ``correlation_id_header``, ``plugins``); any other
key is a ``ConfigurationError`` that names it. ``skye.load_config`` applies the log levels it reads to the ``skye`` loggers.
"""

import logging
import os
import tempfile
from pathlib import Path

import skye
from skye.config import substitute_env_vars

CONFIG = '{"log_level": "INFO", "component_log_levels": {"router": "DEBUG"}}'


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "skye.json"
        path.write_text(CONFIG, encoding="utf-8")

        config = skye.load_config(path)
        print("from the file:       ", config.log_level, config.level_for("router"))
        print("applied to logging:  ", logging.getLevelName(logging.getLogger("skye.router").level))

        path.write_text('{"log_level": "INFO", "enable_telemetry": false}', encoding="utf-8")
        try:
            skye.load_config(path)
        except skye.ConfigurationError as exc:
            print("unknown key:         ", exc.details["unknown_keys"])
        path.write_text(CONFIG, encoding="utf-8")

        os.environ["SKYE_LOG_LEVEL"] = "WARNING"
        config = skye.load_config(path)
        print("environment wins:    ", config.log_level)

        config = skye.load_config(path, overrides={"log_level": "ERROR"})
        print("code wins:           ", config.log_level)
        del os.environ["SKYE_LOG_LEVEL"]

    os.environ.setdefault("OPENAI_API_KEY", "sk-example")
    print("substitution:        ", substitute_env_vars({"api_key": "${OPENAI_API_KEY}"}))


if __name__ == "__main__":
    main()
