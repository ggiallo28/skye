"""Unit tests for Anthropic provider implementation.

Tests cover:
- Client initialization
- Request transformation with system message separation
- Response transformation
- Tool use format
- Streaming
- Error handling
"""

from typing import Any
from unittest.mock import Mock, patch

import pytest

from skye.base.completion import CompleteRequest, CompleteResponse, StreamChunk
from skye.base.exceptions import ProviderError
from skye.base.messages import SystemMessage, UserMessage
from skye.models.plugins.anthropic.provider import AnthropicProvider
from skye.models.utilities.rest import JsonObject


class TestAnthropicProviderInitialization:
    """Test Anthropic provider initialization."""
    
    def test_init_with_api_key(self) -> None:
        """Test initialization with API key."""
        provider = AnthropicProvider(model="claude-3-opus-20240229", api_key="sk-ant-test")
        assert provider.api_key == "sk-ant-test"
    
    def test_no_sdk_client(self) -> None:
        """No vendor SDK client is created; the REST transport is used."""
        provider = AnthropicProvider(model="claude-3-opus-20240229", api_key="sk-ant-test")
        assert provider.client is None

    def test_api_base_override(self) -> None:
        provider = AnthropicProvider(model="m", api_key="k", api_base="http://localhost:9/")
        assert provider._url == "http://localhost:9/v1/messages"

    def test_modules_import_no_anthropic(self) -> None:
        import ast
        import inspect

        import importlib
        import pkgutil

        from skye.models.utilities import anthropic_compatible as pkg

        # The shared base is a package split by responsibility (D110): check every module of it, not only the __init__.
        modules = [importlib.import_module(m.name) for m in pkgutil.iter_modules(pkg.__path__, pkg.__name__ + ".")]
        assert {m.__name__.rsplit(".", 1)[-1] for m in modules} == {"capabilities", "provider", "request", "response"}
        sources = [inspect.getsource(pkg), *(inspect.getsource(m) for m in modules)]
        for node in (n for source in sources for n in ast.walk(ast.parse(source))):
            if isinstance(node, ast.Import):
                assert all(a.name.split(".")[0] != "anthropic" for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] != "anthropic"
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                pass


class TestAnthropicRequestTransformation:
    """Test request transformation to Anthropic format."""
    
    def test_transform_basic_request(self) -> None:
        """Test transformation of basic completion request."""
        provider = AnthropicProvider(model="claude-3-opus-20240229", api_key="sk-ant-test")
        request = CompleteRequest(
            messages=[UserMessage(content="Hello")],
            model="claude-3-opus-20240229",
            temperature=0.7
        )
        
        result = provider._transform_request(request)
        
        assert result["model"] == "claude-3-opus-20240229"
        assert result["temperature"] == 0.7
        assert result["stream"] is False
        assert result["max_tokens"] == 4096  # Default
        assert len(result["messages"]) == 1
        assert result["messages"][0]["role"] == "user"
        assert result["messages"][0]["content"] == "Hello"
        assert "system" not in result
    
    def test_transform_with_system_message_separation(self) -> None:
        """Test transformation with system message separated."""
        provider = AnthropicProvider(model="claude-3-opus-20240229", api_key="sk-ant-test")
        request = CompleteRequest(
            messages=[
                SystemMessage(content="You are a helpful assistant"),
                UserMessage(content="Hello")
            ],
            model="claude-3-opus-20240229"
        )
        
        result = provider._transform_request(request)
        
        # System message should be separate
        assert result["system"] == "You are a helpful assistant"
        # Only user message in messages array
        assert len(result["messages"]) == 1
        assert result["messages"][0]["role"] == "user"
        assert result["messages"][0]["content"] == "Hello"
    
    def test_transform_with_max_tokens(self) -> None:
        """Test transformation with max_tokens parameter."""
        provider = AnthropicProvider(model="claude-3-opus-20240229", api_key="sk-ant-test")
        request = CompleteRequest(
            messages=[UserMessage(content="Hello")],
            model="claude-3-opus-20240229",
            max_tokens=1000
        )
        
        result = provider._transform_request(request)
        
        assert result["max_tokens"] == 1000
    
    def test_transform_with_stop_sequences(self) -> None:
        """Test transformation with stop sequences."""
        provider = AnthropicProvider(model="claude-3-opus-20240229", api_key="sk-ant-test")
        request = CompleteRequest(
            messages=[UserMessage(content="Hello")],
            model="claude-3-opus-20240229",
            stop=["END", "STOP"]
        )
        
        result = provider._transform_request(request)
        
        assert result["stop_sequences"] == ["END", "STOP"]
    
    def test_transform_with_tool_use(self) -> None:
        """Test transformation with tool use (Anthropic's function calling)."""
        provider = AnthropicProvider(model="claude-3-opus-20240229", api_key="sk-ant-test")
        capabilities = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather information",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location": {"type": "string"}
                        }
                    }
                }
            }
        ]
        request = CompleteRequest(
            messages=[UserMessage(content="What's the weather?")],
            model="claude-3-opus-20240229",
            capabilities=capabilities,
            capability_choice="auto"
        )
        
        result = provider._transform_request(request)
        
        assert "tools" in result
        assert len(result["tools"]) == 1
        assert result["tools"][0]["name"] == "get_weather"
        assert result["tools"][0]["description"] == "Get weather information"
        assert result["tools"][0]["input_schema"]["type"] == "object"
        assert result["tool_choice"] == {"type": "auto"}
    
    def test_transform_with_tool_choice_required(self) -> None:
        """Test transformation with required tool choice."""
        provider = AnthropicProvider(model="claude-3-opus-20240229", api_key="sk-ant-test")
        capabilities = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather",
                    "parameters": {"type": "object", "properties": {}}
                }
            }
        ]
        request = CompleteRequest(
            messages=[UserMessage(content="What's the weather?")],
            model="claude-3-opus-20240229",
            capabilities=capabilities,
            capability_choice="required"
        )
        
        result = provider._transform_request(request)
        
        assert result["tool_choice"] == {"type": "any"}
    
    def test_transform_with_provider_metadata(self) -> None:
        """Test transformation with provider-specific metadata."""
        provider = AnthropicProvider(model="claude-3-opus-20240229", api_key="sk-ant-test")
        request = CompleteRequest(
            messages=[UserMessage(content="Hello")],
            model="claude-3-opus-20240229",
            metadata={
                "anthropic_metadata": {"user_id": "user123"},
                "other_key": "ignored"
            }
        )
        
        result = provider._transform_request(request)
        
        assert result["metadata"] == {"user_id": "user123"}
        assert "other_key" not in result


class TestAnthropicResponseTransformation:
    """Test response transformation from Anthropic format."""
    
    def test_transform_basic_response(self) -> None:
        """Test transformation of basic Anthropic response."""
        provider = AnthropicProvider(model="claude-3-opus-20240229", api_key="sk-ant-test")
        
        # Mock Anthropic response
        mock_response = Mock()
        mock_response.id = "msg_123"
        mock_response.model = "claude-3-opus-20240229"
        mock_response.stop_reason = "end_turn"
        mock_response.stop_sequence = None
        
        # Mock content blocks
        mock_content = Mock()
        mock_content.type = "text"
        mock_content.text = "Hello! How can I help you today?"
        mock_response.content = [mock_content]
        
        # Mock usage
        mock_usage = Mock()
        mock_usage.input_tokens = 10
        mock_usage.output_tokens = 20
        mock_response.usage = mock_usage
        
        result = provider._transform_response(mock_response)
        
        assert isinstance(result, CompleteResponse)
        assert result.id == "msg_123"
        assert result.model == "claude-3-opus-20240229"
        assert result.provider == "anthropic"
        assert result.content == "Hello! How can I help you today?"
        assert result.role == "assistant"
        assert result.finish_reason == "end_turn"
        assert result.usage.prompt_tokens == 10
        assert result.usage.completion_tokens == 20
        assert result.usage.total_tokens == 30
        assert result.metadata["stop_sequence"] is None
        assert result.metadata["tool_calls"] is None
    
    def test_transform_response_with_tool_use(self) -> None:
        """Test transformation of response with tool use."""
        provider = AnthropicProvider(model="claude-3-opus-20240229", api_key="sk-ant-test")
        
        # Mock Anthropic response with tool use
        mock_response = Mock()
        mock_response.id = "msg_123"
        mock_response.model = "claude-3-opus-20240229"
        mock_response.stop_reason = "tool_use"
        mock_response.stop_sequence = None
        
        # Mock tool use content block
        mock_tool_use = Mock()
        mock_tool_use.type = "tool_use"
        mock_tool_use.id = "toolu_123"
        mock_tool_use.name = "get_weather"
        mock_tool_use.input = {"location": "NYC"}
        mock_response.content = [mock_tool_use]
        
        # Mock usage
        mock_usage = Mock()
        mock_usage.input_tokens = 15
        mock_usage.output_tokens = 10
        mock_response.usage = mock_usage
        
        result = provider._transform_response(mock_response)
        
        assert result.content == ""
        assert result.finish_reason == "tool_use"
        assert result.metadata["tool_calls"] is not None
        assert len(result.metadata["tool_calls"]) == 1
        assert result.metadata["tool_calls"][0]["id"] == "toolu_123"
        assert result.metadata["tool_calls"][0]["type"] == "function"
        assert result.metadata["tool_calls"][0]["function"]["name"] == "get_weather"
        assert result.metadata["tool_calls"][0]["function"]["arguments"] == {"location": "NYC"}
    
    def test_transform_response_with_mixed_content(self) -> None:
        """Test transformation of response with text and tool use."""
        provider = AnthropicProvider(model="claude-3-opus-20240229", api_key="sk-ant-test")
        
        # Mock Anthropic response with mixed content
        mock_response = Mock()
        mock_response.id = "msg_123"
        mock_response.model = "claude-3-opus-20240229"
        mock_response.stop_reason = "tool_use"
        mock_response.stop_sequence = None
        
        # Mock text content
        mock_text = Mock()
        mock_text.type = "text"
        mock_text.text = "Let me check the weather for you."
        
        # Mock tool use content
        mock_tool_use = Mock()
        mock_tool_use.type = "tool_use"
        mock_tool_use.id = "toolu_123"
        mock_tool_use.name = "get_weather"
        mock_tool_use.input = {"location": "NYC"}
        
        mock_response.content = [mock_text, mock_tool_use]
        
        # Mock usage
        mock_usage = Mock()
        mock_usage.input_tokens = 15
        mock_usage.output_tokens = 25
        mock_response.usage = mock_usage
        
        result = provider._transform_response(mock_response)
        
        assert result.content == "Let me check the weather for you."
        assert result.metadata["tool_calls"] is not None
        assert len(result.metadata["tool_calls"]) == 1


class TestAnthropicStreamTransformation:
    """Test stream chunk transformation."""
    
    def test_transform_content_block_delta(self) -> None:
        """Test transformation of content block delta event."""
        provider = AnthropicProvider(model="claude-3-opus-20240229", api_key="sk-ant-test")
        
        # Mock Anthropic stream event
        mock_chunk = Mock()
        mock_chunk.type = "content_block_delta"
        mock_chunk.message_id = "msg_123"
        mock_chunk.index = 0
        mock_chunk.delta = Mock()
        mock_chunk.delta.text = "Hello"
        
        result = provider._transform_stream_chunk(mock_chunk)
        
        assert isinstance(result, StreamChunk)
        assert result.id == "msg_123"
        assert result.delta == "Hello"
        assert result.finish_reason is None
        assert result.index == 0
    
    def test_transform_message_delta_with_stop(self) -> None:
        """Test transformation of message delta with stop reason."""
        provider = AnthropicProvider(model="claude-3-opus-20240229", api_key="sk-ant-test")
        
        # Mock final stream event
        mock_chunk = Mock()
        mock_chunk.type = "message_delta"
        mock_chunk.message_id = "msg_123"
        mock_chunk.index = 0
        mock_chunk.delta = Mock()
        mock_chunk.delta.stop_reason = "end_turn"
        
        result = provider._transform_stream_chunk(mock_chunk)
        
        assert result.delta == ""
        assert result.finish_reason == "end_turn"
    
    def test_transform_other_event_types(self) -> None:
        """Test transformation of other event types."""
        provider = AnthropicProvider(model="claude-3-opus-20240229", api_key="sk-ant-test")
        
        # Mock other event type (e.g., message_start)
        mock_chunk = Mock()
        mock_chunk.type = "message_start"
        mock_chunk.message_id = "msg_123"
        mock_chunk.index = 0
        
        result = provider._transform_stream_chunk(mock_chunk)
        
        assert result.delta == ""
        assert result.finish_reason is None


URL = "https://api.anthropic.com/v1/messages"
POST = "skye.models.utilities.rest.post_json"
STREAM = "skye.models.utilities.rest.stream_sse_json"


def _msg(blocks: list[dict[str, Any]], stop: str = "end_turn", i: int = 10, o: int = 5) -> JsonObject:
    return JsonObject({
        "id": "msg_123", "model": "claude-3-opus-20240229", "type": "message",
        "role": "assistant", "content": blocks, "stop_reason": stop,
        "stop_sequence": None, "usage": {"input_tokens": i, "output_tokens": o},
    })


def _text(t: str) -> dict[str, Any]:
    return {"type": "text", "text": t}


class TestAnthropicProviderCalls:
    """Test actual provider API calls over the stdlib REST transport."""

    def test_complete_success(self) -> None:
        with patch(POST, return_value=_msg([_text("Test response")])) as post:
            provider = AnthropicProvider(model="claude-3-opus-20240229", api_key="sk-ant-test")
            result = provider.complete(CompleteRequest(
                messages=[UserMessage(content="Hello")], model="claude-3-opus-20240229"
            ))

        assert isinstance(result, CompleteResponse)
        assert result.content == "Test response"
        assert result.provider == "anthropic"
        assert result.usage.total_tokens == 15
        post.assert_called_once()
        assert post.call_args.args[0] == URL
        headers = post.call_args.kwargs["headers"]
        assert headers["x-api-key"] == "sk-ant-test"
        assert headers["anthropic-version"] == "2023-06-01"
        payload = post.call_args.args[1]
        assert payload["model"] == "claude-3-opus-20240229"
        assert payload["messages"] == [{"role": "user", "content": "Hello"}]
        assert payload["max_tokens"] == 4096

    def test_complete_error_handling(self) -> None:
        with patch(POST, side_effect=Exception("API Error")):
            provider = AnthropicProvider(model="claude-3-opus-20240229", api_key="sk-ant-test")
            request = CompleteRequest(
                messages=[UserMessage(content="Hello")], model="claude-3-opus-20240229"
            )
            with pytest.raises(ProviderError) as exc_info:
                provider.complete(request)

        assert "Provider call failed" in str(exc_info.value)
        assert exc_info.value.details["provider"] == "anthropic"

    def test_stream_success(self) -> None:
        events = [
            JsonObject({"type": "message_start", "message": {"id": "msg_123"}}),
            *(
                JsonObject({"type": "content_block_delta", "index": i,
                            "delta": {"type": "text_delta", "text": t}})
                for i, t in enumerate(["Hello", " ", "world"])
            ),
            JsonObject({"type": "message_delta", "delta": {"stop_reason": "end_turn"}}),
        ]
        with patch(STREAM, return_value=iter(events)) as stream:
            provider = AnthropicProvider(model="claude-3-opus-20240229", api_key="sk-ant-test")
            chunks = list(provider.stream(CompleteRequest(
                messages=[UserMessage(content="Hello")],
                model="claude-3-opus-20240229", stream=True,
            )))

        assert stream.call_args.args[0] == URL
        assert stream.call_args.args[1]["stream"] is True
        assert stream.call_args.kwargs["headers"]["x-api-key"] == "sk-ant-test"
        assert [c.delta for c in chunks[1:4]] == ["Hello", " ", "world"]
        assert all(isinstance(c, StreamChunk) for c in chunks)
        assert chunks[-1].finish_reason == "end_turn"

    def test_transform_stream_chunk_missing_attrs(self) -> None:
        provider = AnthropicProvider(model="m", api_key="k")
        chunk = provider._transform_stream_chunk(JsonObject({"type": "ping"}))
        assert chunk.delta == ""
        assert chunk.finish_reason is None


class TestAnthropicAsyncSupport:
    """Test async completion support."""

    @pytest.mark.asyncio
    async def test_acomplete_success(self) -> None:
        with patch(POST, return_value=_msg([_text("Async response")])) as post:
            provider = AnthropicProvider(model="claude-3-opus-20240229", api_key="sk-ant-test")
            result = await provider.acomplete(CompleteRequest(
                messages=[UserMessage(content="Hello")], model="claude-3-opus-20240229"
            ))

        assert isinstance(result, CompleteResponse)
        assert result.content == "Async response"
        assert result.provider == "anthropic"
        assert post.call_args.args[0] == URL


class TestAnthropicModelInfo:
    """Test model info retrieval."""
    
    def test_get_model_info(self) -> None:
        """Test getting model information."""
        provider = AnthropicProvider(model="claude-3-opus-20240229", api_key="sk-ant-test")
        
        info = provider.get_model_info()
        
        assert info["provider"] == "anthropic"
        assert info["supports_streaming"] is True
        assert info["supports_function_calling"] is True
        assert info["supports_structured_output"] is True  # output_config.format
        assert info["supports_multimodal"] is True
        assert info["supports_thinking"] is True


class TestAnthropicToolCalling:
    """Test tool calling integration with capabilities."""
    
    def test_transform_request_with_capabilities(self) -> None:
        """Test transformation of request with capabilities to Anthropic format."""
        # Mock capability
        mock_capability = Mock()
        mock_schema = Mock()
        mock_schema.name = "get_weather"
        mock_schema.description = "Get weather for a location"
        mock_schema.parameters = {
            "type": "object",
            "properties": {
                "location": {"type": "string"}
            },
            "required": ["location"]
        }
        mock_capability.get_schema.return_value = mock_schema
        
        provider = AnthropicProvider(model="claude-3-opus-20240229", api_key="sk-ant-test")
        request = CompleteRequest(
            messages=[UserMessage(content="What's the weather in NYC?")],
            model="claude-3-opus-20240229",
            capabilities=[mock_capability],
            capability_choice="auto"
        )
        
        result = provider._transform_request(request)
        
        # Verify tools are converted to Anthropic format
        assert "tools" in result
        assert len(result["tools"]) == 1
        assert result["tools"][0]["name"] == "get_weather"
        assert result["tools"][0]["description"] == "Get weather for a location"
        assert result["tools"][0]["input_schema"]["type"] == "object"
        assert result["tools"][0]["input_schema"]["properties"]["location"]["type"] == "string"
        assert result["tool_choice"] == {"type": "auto"}
    
    def test_transform_request_with_specific_tool_choice(self) -> None:
        """Test transformation with specific tool name in tool_choice."""
        # Mock capability
        mock_capability = Mock()
        mock_schema = Mock()
        mock_schema.name = "get_weather"
        mock_schema.description = "Get weather"
        mock_schema.parameters = {"type": "object", "properties": {}}
        mock_capability.get_schema.return_value = mock_schema
        
        provider = AnthropicProvider(model="claude-3-opus-20240229", api_key="sk-ant-test")
        request = CompleteRequest(
            messages=[UserMessage(content="What's the weather?")],
            model="claude-3-opus-20240229",
            capabilities=[mock_capability],
            capability_choice="get_weather"
        )
        
        result = provider._transform_request(request)
        
        # Verify tool_choice is formatted correctly for specific tool
        assert "tool_choice" in result
        assert result["tool_choice"]["type"] == "tool"
        assert result["tool_choice"]["name"] == "get_weather"
    
    def test_transform_request_with_required_tool_choice(self) -> None:
        """Test transformation with 'required' tool_choice."""
        # Mock capability
        mock_capability = Mock()
        mock_schema = Mock()
        mock_schema.name = "calculator"
        mock_schema.description = "Calculate"
        mock_schema.parameters = {"type": "object", "properties": {}}
        mock_capability.get_schema.return_value = mock_schema
        
        provider = AnthropicProvider(model="claude-3-opus-20240229", api_key="sk-ant-test")
        request = CompleteRequest(
            messages=[UserMessage(content="Calculate 2+2")],
            model="claude-3-opus-20240229",
            capabilities=[mock_capability],
            capability_choice="required"
        )
        
        result = provider._transform_request(request)
        
        # Verify tool_choice is converted to Anthropic's "any" type
        assert result["tool_choice"] == {"type": "any"}
    
    def test_transform_response_with_capability_calls_creates_capability_call_objects(self) -> None:
        """Test that capability calls in response are converted to CapabilityCall objects."""
        provider = AnthropicProvider(model="claude-3-opus-20240229", api_key="sk-ant-test")
        
        # Mock Anthropic response with tool use
        mock_response = Mock()
        mock_response.id = "msg_123"
        mock_response.model = "claude-3-opus-20240229"
        mock_response.stop_reason = "tool_use"
        mock_response.stop_sequence = None
        
        mock_tool_use = Mock()
        mock_tool_use.type = "tool_use"
        mock_tool_use.id = "toolu_abc123"
        mock_tool_use.name = "get_weather"
        mock_tool_use.input = {"location": "San Francisco", "unit": "celsius"}
        
        mock_response.content = [mock_tool_use]
        
        mock_usage = Mock()
        mock_usage.input_tokens = 50
        mock_usage.output_tokens = 20
        mock_response.usage = mock_usage
        
        result = provider._transform_response(mock_response)
        
        # Verify capability_calls are present in response
        assert result.capability_calls is not None
        assert len(result.capability_calls) == 1
        
        # Verify CapabilityCall object structure
        capability_call = result.capability_calls[0]
        assert capability_call.id == "toolu_abc123"
        assert capability_call.name == "get_weather"
        assert capability_call.arguments == {"location": "San Francisco", "unit": "celsius"}
        
        # Verify metadata also contains tool calls
        assert result.metadata["tool_calls"] is not None
        assert len(result.metadata["tool_calls"]) == 1
        assert result.metadata["tool_calls"][0]["id"] == "toolu_abc123"
    
    def test_transform_response_with_parallel_capability_calls(self) -> None:
        """Test handling of parallel capability calls in response."""
        provider = AnthropicProvider(model="claude-3-opus-20240229", api_key="sk-ant-test")
        
        # Mock Anthropic response with multiple tool uses
        mock_response = Mock()
        mock_response.id = "msg_123"
        mock_response.model = "claude-3-opus-20240229"
        mock_response.stop_reason = "tool_use"
        mock_response.stop_sequence = None
        
        mock_tool_use_1 = Mock()
        mock_tool_use_1.type = "tool_use"
        mock_tool_use_1.id = "toolu_1"
        mock_tool_use_1.name = "get_weather"
        mock_tool_use_1.input = {"location": "NYC"}
        
        mock_tool_use_2 = Mock()
        mock_tool_use_2.type = "tool_use"
        mock_tool_use_2.id = "toolu_2"
        mock_tool_use_2.name = "get_time"
        mock_tool_use_2.input = {"timezone": "EST"}
        
        mock_response.content = [mock_tool_use_1, mock_tool_use_2]
        
        mock_usage = Mock()
        mock_usage.input_tokens = 60
        mock_usage.output_tokens = 30
        mock_response.usage = mock_usage
        
        result = provider._transform_response(mock_response)
        
        # Verify both capability calls are present
        assert result.capability_calls is not None
        assert len(result.capability_calls) == 2
        
        # Verify first capability call
        assert result.capability_calls[0].id == "toolu_1"
        assert result.capability_calls[0].name == "get_weather"
        assert result.capability_calls[0].arguments == {"location": "NYC"}
        
        # Verify second capability call
        assert result.capability_calls[1].id == "toolu_2"
        assert result.capability_calls[1].name == "get_time"
        assert result.capability_calls[1].arguments == {"timezone": "EST"}
    
    def test_transform_response_with_text_and_tool_use(self) -> None:
        """Test handling of response with both text and tool use."""
        provider = AnthropicProvider(model="claude-3-opus-20240229", api_key="sk-ant-test")
        
        # Mock Anthropic response with text and tool use
        mock_response = Mock()
        mock_response.id = "msg_123"
        mock_response.model = "claude-3-opus-20240229"
        mock_response.stop_reason = "tool_use"
        mock_response.stop_sequence = None
        
        mock_text = Mock()
        mock_text.type = "text"
        mock_text.text = "Let me check the weather for you."
        
        mock_tool_use = Mock()
        mock_tool_use.type = "tool_use"
        mock_tool_use.id = "toolu_123"
        mock_tool_use.name = "get_weather"
        mock_tool_use.input = {"location": "Boston"}
        
        mock_response.content = [mock_text, mock_tool_use]
        
        mock_usage = Mock()
        mock_usage.input_tokens = 40
        mock_usage.output_tokens = 25
        mock_response.usage = mock_usage
        
        result = provider._transform_response(mock_response)
        
        # Verify both text content and capability calls are present
        assert result.content == "Let me check the weather for you."
        assert result.capability_calls is not None
        assert len(result.capability_calls) == 1
        assert result.capability_calls[0].name == "get_weather"
    
    def test_transform_request_with_multiple_capabilities(self) -> None:
        """Test transformation with multiple capabilities."""
        provider = AnthropicProvider(model="claude-3-opus-20240229", api_key="sk-ant-test")
        
        # Mock multiple capabilities
        mock_capability_1 = Mock()
        mock_schema_1 = Mock()
        mock_schema_1.name = "get_weather"
        mock_schema_1.description = "Get weather"
        mock_schema_1.parameters = {"type": "object", "properties": {"location": {"type": "string"}}}
        mock_capability_1.get_schema.return_value = mock_schema_1
        
        mock_capability_2 = Mock()
        mock_schema_2 = Mock()
        mock_schema_2.name = "get_time"
        mock_schema_2.description = "Get time"
        mock_schema_2.parameters = {"type": "object", "properties": {"timezone": {"type": "string"}}}
        mock_capability_2.get_schema.return_value = mock_schema_2
        
        # Create request with multiple capabilities
        request = CompleteRequest(
            messages=[UserMessage(content="Hello")],
            model="claude-3-opus-20240229",
            capabilities=[mock_capability_1, mock_capability_2]
        )
        
        result = provider._transform_request(request)
        
        # Verify both tools are present
        assert "tools" in result
        assert len(result["tools"]) == 2
        assert result["tools"][0]["name"] == "get_weather"
        assert result["tools"][1]["name"] == "get_time"
    
    def test_complete_with_capability_calls(self) -> None:
        """Test end-to-end completion with capability calls."""
        mock_capability = Mock()
        mock_schema = Mock()
        mock_schema.name = "get_weather"
        mock_schema.description = "Get weather"
        mock_schema.parameters = {
            "type": "object",
            "properties": {"location": {"type": "string"}},
            "required": ["location"]
        }
        mock_capability.get_schema.return_value = mock_schema

        response = _msg([{"type": "tool_use", "id": "toolu_123", "name": "get_weather",
                          "input": {"location": "Boston"}}], stop="tool_use", i=40, o=15)
        with patch(POST, return_value=response) as post:
            provider = AnthropicProvider(model="claude-3-opus-20240229", api_key="sk-ant-test")
            result = provider.complete(CompleteRequest(
                messages=[UserMessage(content="What's the weather in Boston?")],
                model="claude-3-opus-20240229",
                capabilities=[mock_capability],
                capability_choice="auto"
            ))

        assert result.finish_reason == "tool_use"
        assert result.has_capability_calls()
        assert len(result.capability_calls) == 1
        assert result.capability_calls[0].name == "get_weather"
        assert result.capability_calls[0].arguments == {"location": "Boston"}

        payload = post.call_args.args[1]
        assert payload["tools"][0]["name"] == "get_weather"
        assert payload["tool_choice"] == {"type": "auto"}
