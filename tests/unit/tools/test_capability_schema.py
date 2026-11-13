"""Tests for CapabilitySchema model."""

import dataclasses

import pytest

from skye.base.exceptions import ValidationError

from skye.base.interfaces.capability import CapabilitySchema


class TestCapabilitySchemaCreation:
    """Test creating valid CapabilitySchema instances."""

    def test_create_valid_schema(self) -> None:
        """Test creating a valid capability schema."""
        schema = CapabilitySchema(
            name="weather_get_current",
            description="Get current weather for a location",
            parameters={
                "type": "object",
                "properties": {"location": {"type": "string"}},
                "required": ["location"],
            },
            returns={"type": "string"},
        )

        assert schema.name == "weather_get_current"
        assert schema.description == "Get current weather for a location"
        assert schema.parameters["type"] == "object"
        assert schema.returns["type"] == "string"

    def test_create_schema_with_minimal_fields(self) -> None:
        """Test creating schema with only required fields."""
        schema = CapabilitySchema(
            name="simple_tool",
            description="A simple tool",
        )

        assert schema.name == "simple_tool"
        assert schema.description == "A simple tool"
        assert schema.parameters == {}
        assert schema.returns == {}

    def test_create_schema_with_complex_parameters(self) -> None:
        """Test creating schema with complex parameter definitions."""
        schema = CapabilitySchema(
            name="complex_tool",
            description="Tool with complex parameters",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "age": {"type": "integer", "minimum": 0},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "metadata": {"type": "object"},
                },
                "required": ["name"],
            },
        )

        assert schema.parameters["properties"]["age"]["minimum"] == 0
        assert schema.parameters["properties"]["tags"]["items"]["type"] == "string"
        assert schema.parameters["required"] == ["name"]

    def test_schema_is_frozen(self) -> None:
        """Test that schema is immutable (frozen)."""
        schema = CapabilitySchema(
            name="test",
            description="Test schema",
        )

        with pytest.raises(dataclasses.FrozenInstanceError):
            schema.name = "modified"  # type: ignore


class TestCapabilitySchemaValidation:
    """Test validation of CapabilitySchema."""

    def test_reject_empty_name(self) -> None:
        """Test that empty name is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            CapabilitySchema(
                name="",
                description="Test",
            )
        assert "name" in str(exc_info.value).lower()

    def test_reject_whitespace_only_name(self) -> None:
        """Test that whitespace-only name is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            CapabilitySchema(
                name="   ",
                description="Test",
            )
        assert "name" in str(exc_info.value).lower()

    def test_reject_empty_description(self) -> None:
        """Test that empty description is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            CapabilitySchema(
                name="test",
                description="",
            )
        assert "description" in str(exc_info.value).lower()

    def test_reject_whitespace_only_description(self) -> None:
        """Test that whitespace-only description is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            CapabilitySchema(
                name="test",
                description="   ",
            )
        assert "description" in str(exc_info.value).lower()

    def test_trim_whitespace_from_name(self) -> None:
        """Test that whitespace is trimmed from name."""
        schema = CapabilitySchema(
            name="  test_name  ",
            description="Test",
        )
        assert schema.name == "test_name"

    def test_trim_whitespace_from_description(self) -> None:
        """Test that whitespace is trimmed from description."""
        schema = CapabilitySchema(
            name="test",
            description="  Test description  ",
        )
        assert schema.description == "Test description"


class TestCapabilitySchemaJSONSchema:
    """Test JSON Schema validation and compatibility."""

    def test_valid_json_schema_parameters(self) -> None:
        """Test that valid JSON Schema parameters are accepted."""
        schema = CapabilitySchema(
            name="test",
            description="Test",
            parameters={
                "type": "object",
                "properties": {
                    "param1": {"type": "string", "description": "First param"},
                    "param2": {"type": "integer", "minimum": 0, "maximum": 100},
                },
                "required": ["param1"],
                "additionalProperties": False,
            },
        )

        assert schema.parameters["type"] == "object"
        assert "param1" in schema.parameters["properties"]
        assert schema.parameters["additionalProperties"] is False

    def test_valid_json_schema_returns(self) -> None:
        """Test that valid JSON Schema returns are accepted."""
        schema = CapabilitySchema(
            name="test",
            description="Test",
            returns={
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                    "data": {"type": "array", "items": {"type": "string"}},
                },
            },
        )

        assert schema.returns["type"] == "object"
        assert "status" in schema.returns["properties"]

    def test_schema_with_nested_objects(self) -> None:
        """Test schema with nested object definitions."""
        schema = CapabilitySchema(
            name="test",
            description="Test",
            parameters={
                "type": "object",
                "properties": {
                    "user": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "email": {"type": "string"},
                        },
                        "required": ["name"],
                    }
                },
            },
        )

        user_schema = schema.parameters["properties"]["user"]
        assert user_schema["type"] == "object"
        assert "name" in user_schema["properties"]

    def test_schema_with_array_items(self) -> None:
        """Test schema with array item definitions."""
        schema = CapabilitySchema(
            name="test",
            description="Test",
            parameters={
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"id": {"type": "integer"}},
                        },
                    }
                },
            },
        )

        items_schema = schema.parameters["properties"]["items"]
        assert items_schema["type"] == "array"
        assert items_schema["items"]["type"] == "object"


class TestCapabilitySchemaEquality:
    """Test schema equality and comparison."""

    def test_schemas_with_same_values_are_equal(self) -> None:
        """Test that schemas with identical values are equal."""
        schema1 = CapabilitySchema(
            name="test",
            description="Test schema",
            parameters={"type": "object"},
        )
        schema2 = CapabilitySchema(
            name="test",
            description="Test schema",
            parameters={"type": "object"},
        )

        assert schema1 == schema2

    def test_schemas_with_different_names_are_not_equal(self) -> None:
        """Test that schemas with different names are not equal."""
        schema1 = CapabilitySchema(
            name="test1",
            description="Test",
        )
        schema2 = CapabilitySchema(
            name="test2",
            description="Test",
        )

        assert schema1 != schema2
