"""Integration tests for ModelRouter.from_config_dict().

File loading (.skye and JSON) is tested in test_router_file.py; the library reads no YAML (decision D62).
"""

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import pytest

from skye.base.completion import CompleteRequest, CompleteResponse, StreamChunk, TokenUsage
from skye.base.exceptions import ConfigurationError
from skye.base.interfaces.router import RoutingStrategy
from skye.models.base import BaseModelProvider
from skye.models.registry import ProviderRegistry
from tests.unit.plugins.registrar_state import restored_default_registrar
from skye.router.model_router import ModelRouter


class MockProvider(BaseModelProvider):
    """Mock provider for testing."""
    
    def _initialize_client(self) -> Any:
        return {"mock": "client"}
    
    def _transform_request(self, request: CompleteRequest) -> dict[str, Any]:
        return {"model": request.model, "messages": []}
    
    def _transform_response(self, response: Any) -> CompleteResponse:
        return CompleteResponse(
            id="test_id",
            model="test_model",
            provider="mock",
            content="Mock response",
            finish_reason="stop",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
            created_at=datetime.now(timezone.utc)
        )
    
    def _transform_stream_chunk(self, chunk: Any) -> StreamChunk:
        return StreamChunk(id="test", delta="", index=0)
    
    def _call_provider(self, request: dict[str, Any]) -> Any:
        return {"content": "Mock response"}
    
    def _call_provider_stream(self, request: dict[str, Any]) -> Iterator[Any]:
        yield {"delta": "Mock response"}
    
    def _transform_messages(self, messages: list[Any]) -> list[dict[str, Any]]:
        return [{"role": "user", "content": "test"}]
    
    def _transform_capabilities(self, capabilities: list[Any]) -> list[dict[str, Any]]:
        return []
    
    def _extract_capability_calls(self, response: Any) -> list[Any] | None:
        return None
    
    def format_capability_results(self, results: list[Any]) -> list[dict[str, Any]]:
        """Format capability results for mock provider."""
        return [{"mock_result": "formatted"} for _ in results]
    
    def get_model_info(self) -> dict[str, Any]:
        """Get model information."""
        return {"provider": "mock", "model": "test-model"}


class TestModelRouterFromConfigDict:
    """Tests for ModelRouter.from_config_dict() class method."""

    def setup_method(self):
        """Set up test fixtures."""
        self._restore = restored_default_registrar()
        self._restore.__enter__()
        ProviderRegistry.register_model_provider("mock", MockProvider)

    def teardown_method(self):
        """Restore the provider registry, so later tests still find the real providers."""
        self._restore.__exit__(None, None, None)

    def test_from_config_dict_minimal(self):
        """Test creating router from minimal config dict."""
        config = {"routes": []}

        router = ModelRouter.from_config_dict(config)

        assert router is not None
        assert router.strategy == RoutingStrategy.ROUND_ROBIN
        assert router.cooldown_seconds == 60.0
        assert router.pre_call_checks_enabled is True

    def test_from_config_dict_with_strategy(self):
        """Test creating router with custom strategy."""
        config = {"routes": [], "strategy": "least_busy"}

        router = ModelRouter.from_config_dict(config)

        assert router.strategy == RoutingStrategy.LEAST_BUSY

    def test_from_config_dict_with_settings(self):
        """Test creating router with custom settings."""
        config = {
            "routes": [],
            "strategy": "rate_limit_aware",
            "cooldown_seconds": 120.0,
            "enable_pre_call_checks": False,
        }

        router = ModelRouter.from_config_dict(config)

        assert router.strategy == RoutingStrategy.RATE_LIMIT_AWARE
        assert router.cooldown_seconds == 120.0
        assert router.pre_call_checks_enabled is False

    def test_from_config_dict_invalid_strategy(self):
        """Test that invalid strategy raises ConfigurationError."""
        config = {"routes": [], "strategy": "invalid_strategy"}

        with pytest.raises(ConfigurationError) as exc_info:
            ModelRouter.from_config_dict(config)

        assert "invalid_strategy" in str(exc_info.value).lower()

    def test_from_config_dict_with_routes(self):
        """Test creating router with route configurations."""
        config = {
            "routes": [
                {
                    "alias": "test-model",
                    "targets": [
                        {
                            "model": "gpt-3.5-turbo",
                            "provider": "mock",
                            "api_key": "sk-test",
                            "tpm": 200000,
                            "rpm": 2000,
                        }
                    ],
                    "strategy": "round_robin",
                }
            ]
        }

        router = ModelRouter.from_config_dict(config)

        assert router.is_alias("test-model")
        assert "test-model" in router.list_aliases()

    def test_from_config_dict_with_fallbacks(self):
        """Test creating router with fallback configurations."""
        config = {
            "routes": [
                {
                    "alias": "gpt-4",
                    "targets": [
                        {"model": "gpt-4", "provider": "mock", "api_key": "sk-test"}
                    ],
                },
                {
                    "alias": "gpt-3.5-turbo",
                    "targets": [
                        {"model": "gpt-3.5-turbo", "provider": "mock", "api_key": "sk-test"}
                    ],
                },
            ],
            "fallbacks": [{"primary": "gpt-4", "fallbacks": ["gpt-3.5-turbo"]}],
        }

        router = ModelRouter.from_config_dict(config)

        assert "gpt-4" in router.fallbacks
        assert router.fallbacks["gpt-4"] == ["gpt-3.5-turbo"]

    def test_from_config_dict_with_retry_policies(self):
        """Test creating router with retry policies."""
        config = {
            "routes": [],
            "retry_policies": [
                {"error_type": "RateLimitError", "max_retries": 5},
                {"error_type": "TimeoutError", "max_retries": 3},
            ],
        }

        router = ModelRouter.from_config_dict(config)

        assert router.retry_policy["RateLimitError"] == 5
        assert router.retry_policy["TimeoutError"] == 3

    def test_from_config_dict_with_allowed_fails_policies(self):
        """Test creating router with allowed fails policies."""
        config = {
            "routes": [],
            "allowed_fails_policies": [
                {"error_type": "RateLimitError", "allowed_fails_per_minute": 50}
            ],
        }

        router = ModelRouter.from_config_dict(config)

        assert router.allowed_fails_policy["RateLimitError"] == 50

    def test_from_config_dict_missing_required_route_field(self):
        """Test that missing required route field raises ConfigurationError."""
        config = {
            "routes": [
                {
                    # Missing 'alias' field
                    "targets": [
                        {"model": "gpt-3.5-turbo", "provider": "mock", "api_key": "sk-test"}
                    ]
                }
            ]
        }

        with pytest.raises(ConfigurationError) as exc_info:
            ModelRouter.from_config_dict(config)

        assert "missing" in str(exc_info.value).lower()

    def test_from_config_dict_kwargs_override(self):
        """Test that kwargs override config dict values."""
        config = {"routes": [], "strategy": "round_robin", "cooldown_seconds": 60.0}

        router = ModelRouter.from_config_dict(
            config, strategy="least_busy", cooldown_seconds=120.0
        )

        assert router.strategy == RoutingStrategy.LEAST_BUSY
        assert router.cooldown_seconds == 120.0


class TestModelTargetEnvVarSubstitution:
    """Tests for ModelTarget environment variable substitution."""

    def test_model_target_env_var_substitution(self):
        """Test that ModelTarget substitutes environment variables."""
        from skye.router.model_router import ModelTarget


        # Set test environment variables
        os.environ["TEST_API_KEY_UNIQUE"] = "sk-real-key-456"
        os.environ["TEST_API_BASE_UNIQUE"] = "https://test.example.com"

        try:
            target = ModelTarget(
                model="gpt-4",
                provider="mock",
                api_key="${TEST_API_KEY_UNIQUE}",
                api_base="${TEST_API_BASE_UNIQUE}",
            )

            # Environment variables should be substituted
            assert target.api_key == "sk-real-key-456"
            assert target.api_base == "https://test.example.com"
        finally:
            del os.environ["TEST_API_KEY_UNIQUE"]
            del os.environ["TEST_API_BASE_UNIQUE"]

    def test_model_target_missing_env_var(self):
        """Test that missing environment variable raises ConfigurationError."""
        from skye.router.model_router import ModelTarget

        with pytest.raises(ConfigurationError) as exc_info:
            ModelTarget(
                model="gpt-4", provider="mock", api_key="${NONEXISTENT_VAR}"
            )

        assert "NONEXISTENT_VAR" in str(exc_info.value)

    def test_model_target_no_env_var(self):
        """Test that ModelTarget works without environment variables."""
        from skye.router.model_router import ModelTarget

        target = ModelTarget(
            model="gpt-4", provider="mock", api_key="sk-plain-key"
        )

        assert target.api_key == "sk-plain-key"

    def test_model_target_partial_env_var(self):
        """Test that partial environment variable patterns are not substituted."""
        from skye.router.model_router import ModelTarget

        # This should not trigger substitution (missing closing brace)
        target = ModelTarget(
            model="gpt-4", provider="mock", api_key="sk-${PARTIAL"
        )

        # Should remain unchanged
        assert target.api_key == "sk-${PARTIAL"
