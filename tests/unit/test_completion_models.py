#!/usr/bin/env python
"""Unit tests for completion models."""

import pytest
from skye.base.validated import Validated, validated

from skye.base.completion import CompleteRequest, CompleteResponse, StreamChunk, TokenUsage
from skye.base.exceptions import ValidationError
from skye.base.messages import UserMessage


def test_token_usage():
    """Test TokenUsage model."""
    usage = TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30)
    assert usage.prompt_tokens == 10
    assert usage.completion_tokens == 20
    assert usage.total_tokens == 30


def test_completion_request():
    """Test CompleteRequest model."""
    # Basic request
    request = CompleteRequest(
        messages=[UserMessage(content="Hello")], model="gpt-4", temperature=0.7, max_tokens=100
    )
    assert request.model == "gpt-4"
    assert request.temperature == 0.7
    assert request.max_tokens == 100
    assert request.top_p == 1.0  # default
    assert request.stream is False  # default

    # Test temperature validation
    with pytest.raises(ValidationError):
        CompleteRequest(
            messages=[UserMessage(content="Hi")], model="gpt-4", temperature=3.0  # Invalid
        )

    # Test top_p validation
    with pytest.raises(ValidationError):
        CompleteRequest(messages=[UserMessage(content="Hi")], model="gpt-4", top_p=1.5)  # Invalid


def test_completion_response():
    """Test CompleteResponse model."""
    usage = TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30)

    # Text response
    response = CompleteResponse(
        model="gpt-4", provider="openai", content="Hello there!", finish_reason="stop", usage=usage
    )
    assert response.content == "Hello there!"
    assert response.get_output() == "Hello there!"
    assert response.role == "assistant"

    # Structured response
    @validated
    class Person(Validated):
        name: str
        age: int

    person = Person(name="Alice", age=30)
    response.structured_output = person
    output = response.get_output()
    assert isinstance(output, Person)
    assert output.name == "Alice"


def test_stream_chunk():
    """Test StreamChunk model."""
    chunk = StreamChunk(id="stream_123", delta="Hello", index=0)
    assert chunk.id == "stream_123"
    assert chunk.delta == "Hello"
    assert chunk.index == 0
    assert chunk.finish_reason is None

    final_chunk = StreamChunk(id="stream_123", delta="", finish_reason="stop", index=5)
    assert final_chunk.finish_reason == "stop"


def test_completion_response_capability_calls():
    """Test CompleteResponse with capability calls."""
    from skye.tools.capability_models import CapabilityCall

    usage = TokenUsage(prompt_tokens=50, completion_tokens=20, total_tokens=70)

    # Response without capability calls
    response_no_capabilities = CompleteResponse(
        model="gpt-4",
        provider="openai",
        content="Hello",
        finish_reason="stop",
        usage=usage,
    )
    assert not response_no_capabilities.has_capability_calls()
    assert response_no_capabilities.capability_calls is None

    # Response with capability calls
    capability_call = CapabilityCall(
        id="call_123",
        name="weather_get_current",
        arguments={"location": "San Francisco"},
    )
    response_with_capabilities = CompleteResponse(
        model="gpt-4",
        provider="openai",
        content="",
        finish_reason="capability_calls",
        usage=usage,
        capability_calls=[capability_call],
    )
    assert response_with_capabilities.has_capability_calls()
    assert len(response_with_capabilities.capability_calls) == 1
    assert response_with_capabilities.capability_calls[0].name == "weather_get_current"

    # Response with empty capability_calls list
    response_empty_capabilities = CompleteResponse(
        model="gpt-4",
        provider="openai",
        content="Hello",
        finish_reason="stop",
        usage=usage,
        capability_calls=[],
    )
    assert not response_empty_capabilities.has_capability_calls()


@pytest.mark.asyncio
async def test_completion_response_execute_capability_calls():
    """Test executing capability calls from CompleteResponse without registry."""
    from skye.base.messages import CapabilityMessage
    from skye.tools.capability_models import CapabilityCall
    from skye.tools.local_function import LocalFunctionCapability

    # Create a test capability
    def get_weather(location: str) -> dict:
        """Get weather for a location."""
        return {"location": location, "temperature": 72, "condition": "sunny"}

    capability = LocalFunctionCapability(
        func=get_weather,
        name="weather_get_current",
        description="Get current weather for a location",
    )

    # Create response with capability calls and capabilities
    usage = TokenUsage(prompt_tokens=50, completion_tokens=20, total_tokens=70)
    capability_call = CapabilityCall(
        id="call_123",
        name="weather_get_current",
        arguments={"location": "San Francisco"},
    )
    response = CompleteResponse(
        model="gpt-4",
        provider="openai",
        content="",
        finish_reason="capability_calls",
        usage=usage,
        capability_calls=[capability_call],
    )
    # Attach capabilities (simulating what the provider does)
    response._capabilities = [capability]

    # Execute capability calls - no registry needed!
    messages = response.execute_capability_calls()

    # Verify results
    assert len(messages) == 1
    assert isinstance(messages[0], CapabilityMessage)
    assert messages[0].capability_id == "call_123"
    assert messages[0].capability_name == "weather_get_current"
    assert messages[0].role == "capability"
    # Content should be JSON string of the result
    import json
    content_data = json.loads(messages[0].content)
    assert content_data == {
        "location": "San Francisco",
        "temperature": 72,
        "condition": "sunny",
    }


@pytest.mark.asyncio
async def test_completion_response_execute_capability_calls_error():
    """Test executing capability calls with errors."""
    from skye.base.messages import CapabilityMessage
    from skye.tools.capability_models import CapabilityCall
    from skye.tools.local_function import LocalFunctionCapability
    from skye.tools.registry import CapabilityRegistry

    # Create a test capability that raises an error
    def failing_function(value: str) -> str:
        """A function that always fails."""
        raise ValueError(f"Failed to process: {value}")

    capability = LocalFunctionCapability(
        func=failing_function,
        name="failing_tool",
        description="A tool that fails",
    )

    # Register capability
    registry = CapabilityRegistry()
    registry.register(capability)

    # Create response with capability calls
    usage = TokenUsage(prompt_tokens=50, completion_tokens=20, total_tokens=70)
    capability_call = CapabilityCall(
        id="call_456",
        name="failing_tool",
        arguments={"value": "test"},
    )
    response = CompleteResponse(
        model="gpt-4",
        provider="openai",
        content="",
        finish_reason="capability_calls",
        usage=usage,
        capability_calls=[capability_call],
    )

    # Execute capability calls - now returns CapabilityMessage objects
    messages = response.execute_capability_calls(registry)

    # Verify error message
    assert len(messages) == 1
    assert isinstance(messages[0], CapabilityMessage)
    assert messages[0].capability_id == "call_456"
    assert messages[0].capability_name == "failing_tool"
    assert messages[0].role == "capability"
    assert "Error:" in messages[0].content
    assert "Failed to process: test" in messages[0].content


@pytest.mark.asyncio
async def test_completion_response_execute_capability_calls_no_capabilities():
    """Test executing capability calls when response has no capability calls."""
    from skye.tools.registry import CapabilityRegistry

    registry = CapabilityRegistry()
    usage = TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)

    response = CompleteResponse(
        model="gpt-4",
        provider="openai",
        content="Hello",
        finish_reason="stop",
        usage=usage,
    )

    # Should raise ValueError
    with pytest.raises(ValueError, match="Response has no capability calls to execute"):
        response.execute_capability_calls(registry)


@pytest.mark.asyncio
async def test_completion_response_execute_multiple_capability_calls():
    """Test executing multiple capability calls."""
    from skye.base.messages import CapabilityMessage
    from skye.tools.capability_models import CapabilityCall
    from skye.tools.local_function import LocalFunctionCapability
    from skye.tools.registry import CapabilityRegistry

    # Create test capabilities
    def get_weather(location: str) -> dict:
        """Get weather for a location."""
        return {"location": location, "temperature": 72}

    def get_time(timezone: str) -> dict:
        """Get current time for a timezone."""
        return {"timezone": timezone, "time": "12:00 PM"}

    weather_cap = LocalFunctionCapability(
        func=get_weather,
        name="weather_get_current",
        description="Get current weather",
    )
    time_cap = LocalFunctionCapability(
        func=get_time,
        name="time_get_current",
        description="Get current time",
    )

    # Register capabilities
    registry = CapabilityRegistry()
    registry.register(weather_cap)
    registry.register(time_cap)

    # Create response with multiple capability calls
    usage = TokenUsage(prompt_tokens=50, completion_tokens=30, total_tokens=80)
    capability_calls = [
        CapabilityCall(
            id="call_1",
            name="weather_get_current",
            arguments={"location": "NYC"},
        ),
        CapabilityCall(
            id="call_2",
            name="time_get_current",
            arguments={"timezone": "EST"},
        ),
    ]
    response = CompleteResponse(
        model="gpt-4",
        provider="openai",
        content="",
        finish_reason="capability_calls",
        usage=usage,
        capability_calls=capability_calls,
    )

    # Execute capability calls - now returns CapabilityMessage objects
    messages = response.execute_capability_calls(registry)

    # Verify results
    import json
    assert len(messages) == 2
    assert isinstance(messages[0], CapabilityMessage)
    assert messages[0].capability_id == "call_1"
    assert messages[0].capability_name == "weather_get_current"
    result_0 = json.loads(messages[0].content)
    assert result_0["location"] == "NYC"
    
    assert isinstance(messages[1], CapabilityMessage)
    assert messages[1].capability_id == "call_2"
    assert messages[1].capability_name == "time_get_current"
    result_1 = json.loads(messages[1].content)
    assert result_1["timezone"] == "EST"


@pytest.mark.asyncio
async def test_completion_response_execute_capability_calls_with_overrides():
    """Test executing capability calls with argument overrides."""
    from skye.base.messages import CapabilityMessage
    from skye.tools.capability_models import CapabilityCall
    from skye.tools.local_function import LocalFunctionCapability
    from skye.tools.registry import CapabilityRegistry

    # Create a test capability
    def get_weather(location: str, units: str = "fahrenheit") -> dict:
        """Get weather for a location."""
        temps = {"fahrenheit": 72, "celsius": 22}
        return {"location": location, "temperature": temps.get(units, 72), "units": units}

    capability = LocalFunctionCapability(
        func=get_weather,
        name="weather_get_current",
        description="Get current weather",
    )

    # Register capability
    registry = CapabilityRegistry()
    registry.register(capability)

    # Create response with capability call
    usage = TokenUsage(prompt_tokens=50, completion_tokens=20, total_tokens=70)
    capability_call = CapabilityCall(
        id="call_123",
        name="weather_get_current",
        arguments={"location": "San Francisco", "units": "fahrenheit"},
    )
    response = CompleteResponse(
        model="gpt-4",
        provider="openai",
        content="",
        finish_reason="capability_calls",
        usage=usage,
        capability_calls=[capability_call],
    )

    # Execute with argument overrides
    overrides = {
        "call_123": {"units": "celsius"}  # Override units but keep location
    }
    messages = response.execute_capability_calls(registry, argument_overrides=overrides)

    # Verify the override was applied
    import json
    assert len(messages) == 1
    assert isinstance(messages[0], CapabilityMessage)
    result = json.loads(messages[0].content)
    assert result["location"] == "San Francisco"  # Original LLM argument
    assert result["units"] == "celsius"  # Overridden argument
    assert result["temperature"] == 22  # Result reflects the override


def test_completion_request_has_no_mcp_servers():
    """MCP servers are not a request field (nothing read it): give their capabilities through ``capabilities``."""
    with pytest.raises(ValidationError, match="mcp_servers"):
        CompleteRequest(messages=[UserMessage(content="Test")], model="gpt-4", mcp_servers=[])
