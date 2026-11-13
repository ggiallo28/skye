"""Tests for CapabilityCall and CapabilityResult models."""

import pytest
from skye.base.exceptions import ValidationError as ValidationError

from skye.base.exceptions import ValidationError
from skye.tools.capability_models import CapabilityCall, CapabilityResult


class TestCapabilityCallCreation:
    """Test creating valid CapabilityCall instances."""

    def test_create_valid_tool_call(self) -> None:
        """Test creating a valid tool call."""
        tool_call = CapabilityCall(
            id="call_123",
            name="weather_get_current",
            arguments={"location": "San Francisco"},
        )

        assert tool_call.id == "call_123"
        assert tool_call.name == "weather_get_current"
        assert tool_call.arguments == {"location": "San Francisco"}

    def test_create_tool_call_with_empty_arguments(self) -> None:
        """Test creating a tool call with no arguments."""
        tool_call = CapabilityCall(
            id="call_456",
            name="simple_tool",
        )

        assert tool_call.id == "call_456"
        assert tool_call.name == "simple_tool"
        assert tool_call.arguments == {}

    def test_create_tool_call_with_complex_arguments(self) -> None:
        """Test creating a tool call with complex nested arguments."""
        tool_call = CapabilityCall(
            id="call_789",
            name="database_query",
            arguments={
                "query": "SELECT * FROM users",
                "filters": {
                    "age": {"min": 18, "max": 65},
                    "status": "active",
                },
                "limit": 100,
            },
        )

        assert tool_call.arguments["query"] == "SELECT * FROM users"
        assert tool_call.arguments["filters"]["age"]["min"] == 18
        assert tool_call.arguments["limit"] == 100

    def test_create_tool_call_with_various_argument_types(self) -> None:
        """Test creating a tool call with various argument types."""
        tool_call = CapabilityCall(
            id="call_mixed",
            name="mixed_types",
            arguments={
                "string_arg": "hello",
                "int_arg": 42,
                "float_arg": 3.14,
                "bool_arg": True,
                "list_arg": [1, 2, 3],
                "dict_arg": {"key": "value"},
                "none_arg": None,
            },
        )

        assert tool_call.arguments["string_arg"] == "hello"
        assert tool_call.arguments["int_arg"] == 42
        assert tool_call.arguments["float_arg"] == 3.14
        assert tool_call.arguments["bool_arg"] is True
        assert tool_call.arguments["list_arg"] == [1, 2, 3]
        assert tool_call.arguments["dict_arg"] == {"key": "value"}
        assert tool_call.arguments["none_arg"] is None


class TestCapabilityCallValidation:
    """Test validation of CapabilityCall."""

    def test_reject_missing_id(self) -> None:
        """Test that missing id is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            CapabilityCall(
                name="test_tool",
                arguments={},
            )
        assert "id" in str(exc_info.value).lower()

    def test_reject_missing_name(self) -> None:
        """Test that missing name is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            CapabilityCall(
                id="call_123",
                arguments={},
            )
        assert "name" in str(exc_info.value).lower()

    def test_accept_empty_id_string(self) -> None:
        """Test that empty id string is accepted (validation at provider level)."""
        # Empty strings are technically valid at the type level
        # Provider-specific validation would happen elsewhere
        tool_call = CapabilityCall(
            id="",
            name="test_tool",
        )
        assert tool_call.id == ""

    def test_accept_empty_name_string(self) -> None:
        """Test that empty name string is accepted (validation at provider level)."""
        # Empty strings are technically valid at the type level
        # Provider-specific validation would happen elsewhere
        tool_call = CapabilityCall(
            id="call_123",
            name="",
        )
        assert tool_call.name == ""


class TestCapabilityResultCreation:
    """Test creating valid CapabilityResult instances."""

    def test_create_successful_tool_result(self) -> None:
        """Test creating a successful tool result."""
        result = CapabilityResult(
            capability_call_id="call_123",
            name="weather_get_current",
            result={"temperature": 72, "condition": "sunny"},
        )

        assert result.capability_call_id == "call_123"
        assert result.name == "weather_get_current"
        assert result.result == {"temperature": 72, "condition": "sunny"}
        assert result.error is None

    def test_create_failed_tool_result(self) -> None:
        """Test creating a failed tool result with error."""
        result = CapabilityResult(
            capability_call_id="call_456",
            name="weather_get_current",
            result=None,
            error="Location not found",
        )

        assert result.capability_call_id == "call_456"
        assert result.name == "weather_get_current"
        assert result.result is None
        assert result.error == "Location not found"

    def test_create_tool_result_with_string_result(self) -> None:
        """Test creating a tool result with string return value."""
        result = CapabilityResult(
            capability_call_id="call_789",
            name="text_processor",
            result="Processed text output",
        )

        assert result.result == "Processed text output"
        assert result.error is None

    def test_create_tool_result_with_list_result(self) -> None:
        """Test creating a tool result with list return value."""
        result = CapabilityResult(
            capability_call_id="call_list",
            name="search",
            result=["item1", "item2", "item3"],
        )

        assert result.result == ["item1", "item2", "item3"]
        assert result.error is None

    def test_create_tool_result_with_numeric_result(self) -> None:
        """Test creating a tool result with numeric return value."""
        result = CapabilityResult(
            capability_call_id="call_calc",
            name="calculator",
            result=42,
        )

        assert result.result == 42
        assert result.error is None

    def test_create_tool_result_with_complex_result(self) -> None:
        """Test creating a tool result with complex nested result."""
        result = CapabilityResult(
            capability_call_id="call_complex",
            name="database_query",
            result={
                "rows": [
                    {"id": 1, "name": "Alice"},
                    {"id": 2, "name": "Bob"},
                ],
                "count": 2,
                "metadata": {"query_time_ms": 45},
            },
        )

        assert result.result["rows"][0]["name"] == "Alice"
        assert result.result["count"] == 2
        assert result.result["metadata"]["query_time_ms"] == 45

    def test_create_tool_result_with_both_result_and_error(self) -> None:
        """Test creating a tool result with both result and error (edge case)."""
        result = CapabilityResult(
            capability_call_id="call_edge",
            name="partial_tool",
            result={"partial": "data"},
            error="Partial failure occurred",
        )

        assert result.result == {"partial": "data"}
        assert result.error == "Partial failure occurred"


class TestCapabilityResultValidation:
    """Test validation of CapabilityResult."""

    def test_reject_missing_capability_call_id(self) -> None:
        """Test that missing capability_call_id is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            CapabilityResult(
                name="test_tool",
                result="success",
            )
        assert "capability_call_id" in str(exc_info.value).lower()

    def test_reject_missing_name(self) -> None:
        """Test that missing name is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            CapabilityResult(
                capability_call_id="call_123",
                result="success",
            )
        assert "name" in str(exc_info.value).lower()

    def test_accept_missing_result(self) -> None:
        """Test that missing result defaults to None."""
        result = CapabilityResult(
            capability_call_id="call_123",
            name="test_tool",
        )

        assert result.result is None
        assert result.error is None

    def test_accept_missing_error(self) -> None:
        """Test that missing error defaults to None."""
        result = CapabilityResult(
            capability_call_id="call_123",
            name="test_tool",
            result="success",
        )

        assert result.error is None


class TestCapabilityCallSerialization:
    """Test serialization and deserialization of CapabilityCall."""

    def test_tool_call_to_dict(self) -> None:
        """Test converting CapabilityCall to dictionary."""
        tool_call = CapabilityCall(
            id="call_123",
            name="weather_get_current",
            arguments={"location": "San Francisco"},
        )

        data = tool_call.to_dict()

        assert data["id"] == "call_123"
        assert data["name"] == "weather_get_current"
        assert data["arguments"] == {"location": "San Francisco"}

    def test_tool_call_to_json(self) -> None:
        """Test converting CapabilityCall to JSON string."""
        tool_call = CapabilityCall(
            id="call_123",
            name="weather_get_current",
            arguments={"location": "San Francisco"},
        )

        json_str = tool_call.to_json()

        assert "call_123" in json_str
        assert "weather_get_current" in json_str
        assert "San Francisco" in json_str

    def test_tool_call_from_dict(self) -> None:
        """Test creating CapabilityCall from dictionary."""
        data = {
            "id": "call_456",
            "name": "database_query",
            "arguments": {"query": "SELECT * FROM users"},
        }

        tool_call = CapabilityCall(**data)

        assert tool_call.id == "call_456"
        assert tool_call.name == "database_query"
        assert tool_call.arguments["query"] == "SELECT * FROM users"

    def test_tool_call_from_json(self) -> None:
        """Test creating CapabilityCall from JSON string."""
        json_str = '{"id": "call_789", "name": "test_tool", "arguments": {"key": "value"}}'

        tool_call = CapabilityCall.from_json(json_str)

        assert tool_call.id == "call_789"
        assert tool_call.name == "test_tool"
        assert tool_call.arguments["key"] == "value"


class TestCapabilityResultSerialization:
    """Test serialization and deserialization of CapabilityResult."""

    def test_tool_result_to_dict(self) -> None:
        """Test converting CapabilityResult to dictionary."""
        result = CapabilityResult(
            capability_call_id="call_123",
            name="weather_get_current",
            result={"temperature": 72},
        )

        data = result.to_dict()

        assert data["capability_call_id"] == "call_123"
        assert data["name"] == "weather_get_current"
        assert data["result"] == {"temperature": 72}
        assert data["error"] is None

    def test_tool_result_to_json(self) -> None:
        """Test converting CapabilityResult to JSON string."""
        result = CapabilityResult(
            capability_call_id="call_123",
            name="weather_get_current",
            result={"temperature": 72},
            error=None,
        )

        json_str = result.to_json()

        assert "call_123" in json_str
        assert "weather_get_current" in json_str
        assert "72" in json_str

    def test_tool_result_from_dict(self) -> None:
        """Test creating CapabilityResult from dictionary."""
        data = {
            "capability_call_id": "call_456",
            "name": "database_query",
            "result": [{"id": 1}, {"id": 2}],
            "error": None,
        }

        result = CapabilityResult(**data)

        assert result.capability_call_id == "call_456"
        assert result.name == "database_query"
        assert len(result.result) == 2

    def test_tool_result_from_json(self) -> None:
        """Test creating CapabilityResult from JSON string."""
        json_str = '{"capability_call_id": "call_789", "name": "test_tool", "result": "success", "error": null}'

        result = CapabilityResult.from_json(json_str)

        assert result.capability_call_id == "call_789"
        assert result.name == "test_tool"
        assert result.result == "success"
        assert result.error is None

    def test_tool_result_error_serialization(self) -> None:
        """Test serializing CapabilityResult with error."""
        result = CapabilityResult(
            capability_call_id="call_error",
            name="failing_tool",
            result=None,
            error="Tool execution failed",
        )

        data = result.to_dict()

        assert data["error"] == "Tool execution failed"
        assert data["result"] is None

    def test_tool_result_error_json_serialization(self) -> None:
        """Test JSON serializing CapabilityResult with error."""
        result = CapabilityResult(
            capability_call_id="call_error",
            name="failing_tool",
            result=None,
            error="Tool execution failed",
        )

        json_str = result.to_json()

        assert "Tool execution failed" in json_str
        assert "call_error" in json_str


class TestCapabilityCallAndResultIntegration:
    """Test integration between CapabilityCall and CapabilityResult."""

    def test_tool_call_and_result_correspondence(self) -> None:
        """Test that CapabilityResult correctly corresponds to CapabilityCall."""
        tool_call = CapabilityCall(
            id="call_123",
            name="weather_get_current",
            arguments={"location": "San Francisco"},
        )

        result = CapabilityResult(
            capability_call_id=tool_call.id,
            name=tool_call.name,
            result={"temperature": 72, "condition": "sunny"},
        )

        assert result.capability_call_id == tool_call.id
        assert result.name == tool_call.name

    def test_multiple_tool_calls_and_results(self) -> None:
        """Test handling multiple tool calls and results."""
        tool_calls = [
            CapabilityCall(
                id="call_1",
                name="weather_get_current",
                arguments={"location": "SF"},
            ),
            CapabilityCall(
                id="call_2",
                name="weather_get_forecast",
                arguments={"location": "SF", "days": 3},
            ),
        ]

        results = [
            CapabilityResult(
                capability_call_id="call_1",
                name="weather_get_current",
                result={"temperature": 72},
            ),
            CapabilityResult(
                capability_call_id="call_2",
                name="weather_get_forecast",
                result={"forecast": ["sunny", "cloudy", "rainy"]},
            ),
        ]

        assert len(tool_calls) == len(results)
        for tool_call, result in zip(tool_calls, results):
            assert result.capability_call_id == tool_call.id
            assert result.name == tool_call.name
