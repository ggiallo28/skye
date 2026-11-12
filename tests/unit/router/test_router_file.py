"""ModelRouter.from_file(): a router read from a ``.skye`` or JSON file; YAML is not read (decisions
D59, D62).
"""

from __future__ import annotations

import json

import pytest

from skye.base.exceptions import ConfigurationError
from skye.base.interfaces.router import RoutingStrategy
from skye.models.registry import ProviderRegistry
from tests.unit.plugins.registrar_state import restored_default_registrar
from skye.router import ModelRouter, load_router_config
from tests.unit.router.test_router_from_config import MockProvider

FULL = """
router "main" {
  strategy = "round_robin"
  cooldown = "90s"
  enable_pre_call_checks = false

  route "smart" {
    strategy = "rate_limit_aware"
    fallback = ["cheap"]
    target {
      model = "gpt-4", provider = "mock", api_key = env.SKYE_TEST_KEY
      rpm = 60, tpm = 90000, timeout = "30s", tags = ["premium"]
    }
  }
  route "cheap" {
    target { model = "gpt-4o-mini", provider = "mock" }
  }

  retry_policy "RateLimitError" { max_retries = 3, retry_after = "5s" }
  allowed_fails_policy "RateLimitError" { allowed_fails_per_minute = 100 }
}
"""


@pytest.fixture(autouse=True)
def mock_provider():
    """Register the mock provider and restore the registry afterwards.

    Later tests then still find the real providers.
    """
    with restored_default_registrar():
        ProviderRegistry.register_model_provider("mock", MockProvider)
        yield


@pytest.fixture
def skye_file(tmp_path, monkeypatch):
    monkeypatch.setenv("SKYE_TEST_KEY", "sk-from-env")
    path = tmp_path / "router.skye"
    path.write_text(FULL, encoding="utf-8")
    return path


def test_the_full_form_builds_the_same_objects_as_the_dictionary_form(skye_file):
    router = ModelRouter.from_file(skye_file)
    assert sorted(router.aliases) == ["cheap", "smart"]
    assert router.strategy == RoutingStrategy.ROUND_ROBIN
    assert router.cooldown_seconds == 90.0
    assert router.pre_call_checks_enabled is False
    target = router.aliases["smart"].targets[0]
    assert (target.rpm, target.tpm, target.timeout, target.tags) == (60, 90000, 30.0, ["premium"])
    assert router.aliases["smart"].strategy == RoutingStrategy.RATE_LIMIT_AWARE


def test_the_config_dictionary_has_the_names_of_the_old_file(skye_file):
    config = load_router_config(skye_file)
    assert (
        config["cooldown_seconds"] == 90.0
    )  # "90s": the suffix is gone from the file, not from the dictionary
    assert config["routes"][0]["targets"][0]["api_key"] == "sk-from-env"  # env.NAME was replaced
    assert config["fallbacks"] == [{"primary": "smart", "fallbacks": ["cheap"]}]
    assert config["retry_policies"] == [
        {"error_type": "RateLimitError", "max_retries": 3, "retry_after_seconds": 5.0}
    ]  # retry_after = "5s" is applied since 2026-11-11 (router task 6.1)
    assert config["allowed_fails_policies"] == [
        {"error_type": "RateLimitError", "allowed_fails_per_minute": 100}
    ]


def test_the_shorthand_makes_one_route_and_a_chain_of_fallbacks(tmp_path):
    path = tmp_path / "r.skye"
    path.write_text('router { route "fast" = ["mock/a", "mock/b", "mock/c"] }', encoding="utf-8")
    router = ModelRouter.from_file(path)
    assert sorted(router.aliases) == ["fast", "fast/fallback1", "fast/fallback2"]
    assert load_router_config(path)["fallbacks"] == [
        {"primary": "fast", "fallbacks": ["fast/fallback1", "fast/fallback2"]}
    ]


def test_a_missing_variable_is_a_configuration_error(skye_file, monkeypatch):
    monkeypatch.delenv("SKYE_TEST_KEY")
    with pytest.raises(ConfigurationError, match="SKYE_TEST_KEY"):
        ModelRouter.from_file(skye_file)


def test_the_name_picks_one_router_of_several(tmp_path):
    path = tmp_path / "two.skye"
    path.write_text(
        'router "a" { route "x" = ["mock/m"] }\nrouter "b" { route "y" = ["mock/m"] }',
        encoding="utf-8",
    )
    assert sorted(ModelRouter.from_file(path, name="b").aliases) == ["y"]
    with pytest.raises(ConfigurationError, match="give the name"):
        ModelRouter.from_file(path)
    with pytest.raises(ConfigurationError, match='no router "c"'):
        ModelRouter.from_file(path, name="c")


def test_a_syntax_error_names_the_file_the_line_and_the_fix(tmp_path):
    path = tmp_path / "bad.skye"
    path.write_text(
        'router {\n  route "x" {\n    targt { model = "m", provider = "mock" }\n  }\n}\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError) as caught:
        ModelRouter.from_file(path)
    text = str(caught.value)
    assert (
        "bad.skye" in text and ":3:" in text and "target" in text
    )  # file, line, and the nearest name


def test_a_keyword_argument_overrides_the_file(skye_file):
    assert ModelRouter.from_file(skye_file, cooldown_seconds=5.0).cooldown_seconds == 5.0


def test_a_json_file_is_read_with_dollar_variables(tmp_path, monkeypatch):
    monkeypatch.setenv("SKYE_TEST_KEY", "sk-json")
    path = tmp_path / "router.json"
    path.write_text(
        json.dumps(
            {
                "routes": [
                    {
                        "alias": "j",
                        "targets": [
                            {"model": "m", "provider": "mock", "api_key": "${SKYE_TEST_KEY}"}
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    router = ModelRouter.from_file(path)
    assert router.aliases["j"].targets[0].api_key == "sk-json"


def test_a_missing_file_is_a_configuration_error(tmp_path):
    with pytest.raises(ConfigurationError, match="not found"):
        ModelRouter.from_file(tmp_path / "nope.skye")


@pytest.mark.parametrize("name", ["router.yaml", "router.yml", "ROUTER.YAML"])
def test_yaml_is_rejected_and_the_message_names_the_supported_formats(tmp_path, name):
    path = tmp_path / name
    path.write_text("routes: []\n", encoding="utf-8")
    with pytest.raises(ConfigurationError) as caught:
        ModelRouter.from_file(path)
    assert ".skye" in str(caught.value) and "JSON" in str(caught.value)


def test_another_suffix_is_rejected_with_the_supported_formats(tmp_path):
    path = tmp_path / "router.toml"
    path.write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match=r"\.skye or a \.json"):
        ModelRouter.from_file(path)
