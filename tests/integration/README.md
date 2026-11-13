# Integration Tests

This directory contains integration tests that verify interactions between multiple Skye components.

## Purpose

Integration tests verify that different components work correctly together. They should:
- Test component interactions and workflows
- Use real implementations where possible
- Verify end-to-end functionality
- Test configuration loading from multiple sources
- May make real API calls (when configured)

## Directory Structure

```
integration/
├── capabilities/       # End-to-end capability tests
│   ├── test_capability_execution.py
│   ├── test_mcp_integration.py
│   └── test_capability_with_providers.py
├── providers/          # Provider integration tests
│   ├── test_openai_integration.py
│   ├── test_bedrock_integration.py
│   ├── test_anthropic_integration.py
│   └── test_multi_provider.py
└── routes/             # Router integration tests
    ├── test_skye_routing.py
    ├── test_fallback_chains.py
    └── test_rate_limit_integration.py
```

## Running Integration Tests

```bash
# Run all integration tests
pytest tests/integration/

# Run specific module tests
pytest tests/integration/capabilities/
pytest tests/integration/providers/
pytest tests/integration/routes/

# Skip tests that require API keys
pytest tests/integration/ -m "not requires_api_key"

# Run only tests that require API keys (when configured)
pytest tests/integration/ -m "requires_api_key"
```

## Environment Setup

Integration tests may require environment variables for API access:

```bash
# OpenAI
export OPENAI_API_KEY="your-openai-key"

# Azure OpenAI
export AZURE_API_KEY="your-azure-key"
export AZURE_API_BASE="https://your-resource.openai.azure.com"

# Anthropic
export ANTHROPIC_API_KEY="your-anthropic-key"

# AWS Bedrock
export AWS_ACCESS_KEY_ID="your-aws-key"
export AWS_SECRET_ACCESS_KEY="your-aws-secret"
export AWS_REGION="us-east-1"
```

## Writing Integration Tests

### Basic Structure

```python
import pytest
from skye.router import ModelRouter
from skye.base.completion import CompleteRequest
from skye.base.messages import UserMessage

@pytest.mark.integration
def test_router_with_skye_config():
    """Test router loading and execution from a .skye file."""
    # Load router from a .skye file
    router = ModelRouter.from_file("tests/fixtures/skye/routers.skye", name="r1")
    
    # Create request
    request = CompleteRequest(
        messages=[UserMessage(content="Hello, world!")],
        model="gpt-3.5-turbo"
    )
    
    # Execute request
    response = router.complete(
        messages=[UserMessage("Hello!")],
        model="gpt-4"
    )
    
    # Verify response
    assert response is not None
    assert response.content
    assert len(response.content) > 0
```

### Testing with Real APIs

```python
import pytest
import os

@pytest.mark.integration
@pytest.mark.requires_api_key
@pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set"
)
def test_openai_provider_real_api():
    """Test OpenAI provider with real API call."""
    from skye.models.plugins.openai.provider import OpenAIProvider
    
    provider = OpenAIProvider(api_key=os.getenv("OPENAI_API_KEY"))
    
    request = CompleteRequest(
        messages=[UserMessage(content="Say 'test' and nothing else")],
        model="gpt-3.5-turbo",
        max_tokens=10
    )
    
    response = provider.complete(request)
    
    assert response is not None
    assert "test" in response.content.lower()
```

### Testing Multi-Component Workflows

```python
import pytest
from skye.router import ModelRouter
from skye.tools import CapabilityRegistry, capability

@pytest.mark.integration
def test_router_with_capabilities():
    """Test router with capability execution."""
    # Register capability
    @capability(name="get_weather")
    def get_weather(location: str) -> dict:
        return {"location": location, "temperature": 72}
    
    registry = CapabilityRegistry()
    registry.register(get_weather)
    
    # Create router
    router = ModelRouter.from_file("tests/fixtures/skye/routers.skye", name="r1")
    
    # Create request with capabilities
    request = CompleteRequest(
        messages=[UserMessage(content="What's the weather in SF?")],
        model="gpt-3.5-turbo",
        capabilities=registry.get_all()
    )
    
    # Execute
    response = router.complete(
        messages=[UserMessage("Hello!")],
        model="gpt-4"
    )
    
    assert response is not None
```

### Testing Fallback Chains

```python
import pytest
from skye.router import ModelRouter
from skye.base.exceptions import ProviderError

@pytest.mark.integration
def test_fallback_chain_execution():
    """Test router fallback chain when primary fails."""
    router = ModelRouter.from_file("tests/fixtures/skye/routers.skye", name="r1")
    
    # Create request
    request = CompleteRequest(
        messages=[UserMessage(content="Hello")],
        model="gpt-4"  # Primary model
    )
    
    # Mock primary failure and verify fallback
    # (Implementation depends on how you want to simulate failure)
    response = router.complete(
        messages=[UserMessage("Hello!")],
        model="gpt-4"
    )
    
    assert response is not None
```

## Test Markers

Use pytest markers to categorize integration tests:

```python
@pytest.mark.integration
def test_basic_integration():
    """Basic integration test."""
    pass

@pytest.mark.requires_api_key
def test_with_real_api():
    """Test requiring real API access."""
    pass

@pytest.mark.slow
def test_slow_integration():
    """Slow integration test."""
    pass
```

## Best Practices

1. **Use real implementations** - Don't mock unless necessary
2. **Test realistic scenarios** - Use real-world workflows
3. **Handle API failures gracefully** - Tests should be resilient
4. **Use environment variables** - Don't hardcode API keys
5. **Mark tests appropriately** - Use markers for tests requiring API access
6. **Clean up resources** - Use fixtures with teardown
7. **Test error paths** - Verify error handling works end-to-end

## Common Patterns

### Using Fixtures for Setup/Teardown

```python
import pytest
from skye.router import ModelRouter

@pytest.fixture
def configured_router():
    """Create and configure a router for testing."""
    router = ModelRouter.from_file("tests/fixtures/skye/routers.skye", name="r1")
    yield router
    # Cleanup if needed
    router.cleanup()

def test_with_router(configured_router):
    """Test using configured router fixture."""
    response = configured_router.complete(
        messages=[UserMessage("Hello!")],
        model="gpt-4"
    )
    assert response is not None
```

### Testing Async Workflows

```python
import pytest
import asyncio

@pytest.mark.integration
@pytest.mark.asyncio
async def test_async_routing():
    """Test async routing workflow."""
    router = ModelRouter.from_file("tests/fixtures/skye/routers.skye", name="r1")
    
    request = CompleteRequest(
        messages=[UserMessage(content="Hello")],
        model="gpt-3.5-turbo"
    )
    
    response = await router.aroute_request(request)
    assert response is not None
```

### Testing Configuration Loading

```python
import pytest
from skye.router import ModelRouter

@pytest.mark.integration
def test_skye_config_loading():
    """Test loading router from .skye with env vars."""
    import os
    os.environ["TEST_API_KEY"] = "test-key-123"
    
    router = ModelRouter.from_file("tests/fixtures/skye/routers.skye", name="r1")
    
    # Verify configuration was loaded correctly
    assert router is not None
    assert len(router.routes) > 0
```

## Troubleshooting

### API Rate Limits
- Use `pytest -k "not requires_api_key"` to skip API tests during development
- Implement retry logic with exponential backoff
- Use test API keys with higher rate limits if available

### Flaky Tests
- Add retries for network-related failures
- Use longer timeouts for API calls
- Check for race conditions in async tests

### Environment Issues
- Verify all required environment variables are set
- Check API key permissions and quotas
- Ensure network connectivity to API endpoints

## Test Coverage Goals

Integration tests should verify:
- **End-to-end workflows** - Complete user scenarios
- **Component interactions** - How components work together
- **Configuration loading** - `.skye`, JSON, environment variables
- **Error handling** - Graceful degradation and recovery

## Related Documentation

- [Main Test README](../README.md)
- [Unit Tests](../unit/README.md)
- [Stress Tests](../stress/README.md)
- [Skye Architecture](../../.kiro/steering/00-rules.md)
