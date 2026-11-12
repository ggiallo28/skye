# Unit Tests

This directory contains fast, isolated unit tests for individual Skye components.

## Purpose

Unit tests verify that individual components work correctly in isolation. They should:
- Run quickly (< 1 second per test)
- Mock external dependencies (APIs, databases, file systems)
- Focus on business logic and edge cases
- Test one component at a time
- Be deterministic and repeatable

## Directory Structure

```
unit/
├── capabilities/       # Capability system tests
│   ├── test_capability_call_handler.py
│   ├── test_capability_models.py
│   ├── test_capability_registry.py
│   └── test_capability_transformer.py
├── providers/          # Provider implementation tests
│   ├── test_bedrock_provider.py
│   ├── test_openai_provider.py
│   ├── test_anthropic_provider.py
│   └── test_provider_registry.py
├── routes/             # Router and routing logic tests
│   ├── test_model_router.py
│   ├── test_routing_strategies.py
│   └── test_rate_limiting.py
├── config/             # Configuration loading tests
│   ├── test_config_loader.py
│   ├── test_env_var_substitution.py
│   └── test_router_config_model.py
└── utils/              # Utility function tests
    ├── test_token_counter.py
    ├── test_cost_calculator.py
    └── test_image_handler.py
```

## Running Unit Tests

```bash
# Run all unit tests
pytest tests/unit/

# Run specific module tests
pytest tests/unit/tools/
pytest tests/unit/models/
pytest tests/unit/router/

# Run with coverage
pytest tests/unit/ --cov=src/skye --cov-report=html

# Run in parallel
pytest tests/unit/ -n auto
```

## Writing Unit Tests

### Basic Structure

```python
import pytest
from skye.tools import CapabilityCall, CapabilityResult

def test_capability_call_creation():
    """Test creating a capability call with valid data."""
    call = CapabilityCall(
        id="test-1",
        name="get_weather",
        arguments={"location": "San Francisco"}
    )
    
    assert call.id == "test-1"
    assert call.name == "get_weather"
    assert call.arguments["location"] == "San Francisco"

def test_capability_call_validation():
    """Test capability call validation with invalid data."""
    with pytest.raises(ValidationError):
        CapabilityCall(id="", name="get_weather")  # Empty ID should fail
```

### Using Fixtures

```python
import pytest
from skye.router import ModelRouter, ModelTarget

@pytest.fixture
def sample_router():
    """Create a sample router for testing."""
    return ModelRouter(routes=[
        RouteConfig(
            alias="test-model",
            targets=[
                ModelTarget(
                    model="gpt-3.5-turbo",
                    provider="openai",
                    api_key="test-key"
                )
            ]
        )
    ])

def test_router_selection(sample_router):
    """Test router model selection."""
    target = sample_router.select_target("test-model")
    assert target is not None
    assert target.model == "gpt-3.5-turbo"
```

### Mocking External Dependencies

```python
from unittest.mock import Mock, patch
import pytest

@patch('skye.models.plugins.openai.provider.OpenAI')
def test_openai_provider_completion(mock_openai):
    """Test OpenAI provider with mocked API."""
    # Setup mock
    mock_client = Mock()
    mock_openai.return_value = mock_client
    mock_client.chat.completions.create.return_value = Mock(
        choices=[Mock(message=Mock(content="Hello!"))]
    )
    
    # Test provider
    provider = OpenAIProvider(api_key="test-key")
    response = provider.complete(request)
    
    assert response.content == "Hello!"
    mock_client.chat.completions.create.assert_called_once()
```

### Parametrized Tests

```python
@pytest.mark.parametrize("temperature,expected_valid", [
    (0.0, True),
    (0.7, True),
    (1.0, True),
    (2.0, True),
    (-0.1, False),
    (2.1, False),
])
def test_temperature_validation(temperature, expected_valid):
    """Test temperature parameter validation."""
    try:
        config = ModelConfig(
            model_id="test",
            provider="test",
            temperature=temperature
        )
        assert expected_valid is True
    except ValidationError:
        assert expected_valid is False
```

## Test Coverage Goals

Unit tests should achieve:
- **80%+ coverage** on core functionality
- **90%+ coverage** on configuration loading
- **85%+ coverage** on capability models
- **90%+ coverage** on router selection logic

## Best Practices

1. **One assertion per test** (when possible) - Makes failures easier to diagnose
2. **Descriptive test names** - Name should describe what is being tested
3. **Arrange-Act-Assert pattern** - Clear separation of setup, execution, and verification
4. **Mock external dependencies** - Don't make real API calls in unit tests
5. **Test edge cases** - Empty inputs, boundary values, invalid data
6. **Use fixtures** - Share common setup across tests
7. **Keep tests fast** - Unit tests should run in milliseconds

## Common Patterns

### Testing Pydantic Models

```python
from pydantic import ValidationError
import pytest

def test_model_validation():
    """Test Pydantic model validation."""
    # Valid data
    model = MyModel(field1="value", field2=42)
    assert model.field1 == "value"
    
    # Invalid data
    with pytest.raises(ValidationError) as exc_info:
        MyModel(field1="", field2=-1)
    
    errors = exc_info.value.errors()
    assert len(errors) == 2
```

### Testing Async Functions

```python
import pytest

@pytest.mark.asyncio
async def test_async_completion():
    """Test async completion method."""
    provider = OpenAIProvider(api_key="test-key")
    response = await provider.acomplete(request)
    assert response is not None
```

### Testing Error Handling

```python
def test_error_handling():
    """Test proper error handling."""
    with pytest.raises(ConfigurationError) as exc_info:
        load_config("invalid.json")
    
    assert "Invalid configuration" in str(exc_info.value)
    assert exc_info.value.details["config_path"] == "invalid.json"
```

## Troubleshooting

### Tests Running Slowly
- Check for unintentional API calls
- Ensure external dependencies are mocked
- Use `pytest --durations=10` to find slow tests

### Flaky Tests
- Check for race conditions in async tests
- Ensure tests don't depend on external state
- Use deterministic test data

### Import Errors
- Ensure `__init__.py` files exist in all directories
- Check that the package is installed in development mode: `pip install -e .`

## Related Documentation

- [Main Test README](../README.md)
- [Integration Tests](../integration/README.md)
- [Stress Tests](../stress/README.md)
- [Python Standards](../../.kiro/steering/00-rules.md)
