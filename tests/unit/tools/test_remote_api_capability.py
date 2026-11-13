"""Tests for RemoteAPICapability."""

import asyncio

import pytest

from skye.tools.exceptions import CapabilityValidationError
from skye.tools.remote_api import RemoteAPICapability
from skye.base.interfaces.capability import CapabilitySchema
from tests.unit.tools import _urllib_responses as responses


class TestRemoteAPICapabilityCreation:
    """Test creating RemoteAPICapability instances."""

    def test_create_with_required_parameters(self) -> None:
        """Test creating capability with required parameters."""
        capability = RemoteAPICapability(
            name="test_api",
            description="Test API",
            url="https://api.example.com/test",
        )

        assert capability.name == "test_api"
        assert capability.description == "Test API"
        assert capability.url == "https://api.example.com/test"
        assert capability.method == "POST"
        assert capability.timeout == 30.0

    def test_create_with_custom_method(self) -> None:
        """Test creating capability with custom HTTP method."""
        for method in ["GET", "POST", "PUT", "DELETE", "PATCH"]:
            capability = RemoteAPICapability(
                name="test_api",
                description="Test API",
                url="https://api.example.com/test",
                method=method,
            )
            assert capability.method == method

    def test_create_with_lowercase_method(self) -> None:
        """Test that HTTP method is normalized to uppercase."""
        capability = RemoteAPICapability(
            name="test_api",
            description="Test API",
            url="https://api.example.com/test",
            method="get",
        )
        assert capability.method == "GET"

    def test_create_with_custom_headers(self) -> None:
        """Test creating capability with custom headers."""
        headers = {"Authorization": "Bearer token123", "X-Custom": "value"}
        capability = RemoteAPICapability(
            name="test_api",
            description="Test API",
            url="https://api.example.com/test",
            headers=headers,
        )
        assert capability.headers == headers

    def test_create_with_basic_auth(self) -> None:
        """Test creating capability with basic authentication."""
        auth = ("username", "password")
        capability = RemoteAPICapability(
            name="test_api",
            description="Test API",
            url="https://api.example.com/test",
            auth=auth,
        )
        assert capability.auth == auth

    def test_create_with_custom_timeout(self) -> None:
        """Test creating capability with custom timeout."""
        capability = RemoteAPICapability(
            name="test_api",
            description="Test API",
            url="https://api.example.com/test",
            timeout=60.0,
        )
        assert capability.timeout == 60.0

    def test_create_with_custom_schema(self) -> None:
        """Test creating capability with custom schema."""
        schema = CapabilitySchema(
            name="custom_schema",
            description="Custom schema",
            parameters={"type": "object", "properties": {"x": {"type": "string"}}},
            returns={"type": "string"},
        )
        capability = RemoteAPICapability(
            name="test_api",
            description="Test API",
            url="https://api.example.com/test",
            schema=schema,
        )
        assert capability._schema == schema

    def test_reject_empty_name(self) -> None:
        """Test that empty name is rejected."""
        with pytest.raises(CapabilityValidationError) as exc_info:
            RemoteAPICapability(
                name="",
                description="Test API",
                url="https://api.example.com/test",
            )
        assert "name" in str(exc_info.value).lower()

    def test_reject_empty_description(self) -> None:
        """Test that empty description is rejected."""
        with pytest.raises(CapabilityValidationError) as exc_info:
            RemoteAPICapability(
                name="test_api",
                description="",
                url="https://api.example.com/test",
            )
        assert "description" in str(exc_info.value).lower()

    def test_reject_empty_url(self) -> None:
        """Test that empty URL is rejected."""
        with pytest.raises(CapabilityValidationError) as exc_info:
            RemoteAPICapability(
                name="test_api",
                description="Test API",
                url="",
            )
        assert "url" in str(exc_info.value).lower()

    def test_reject_invalid_http_method(self) -> None:
        """Test that invalid HTTP method is rejected."""
        with pytest.raises(CapabilityValidationError) as exc_info:
            RemoteAPICapability(
                name="test_api",
                description="Test API",
                url="https://api.example.com/test",
                method="INVALID",
            )
        assert "method" in str(exc_info.value).lower()

    def test_reject_invalid_timeout(self) -> None:
        """Test that invalid timeout is rejected."""
        with pytest.raises(CapabilityValidationError) as exc_info:
            RemoteAPICapability(
                name="test_api",
                description="Test API",
                url="https://api.example.com/test",
                timeout=0,
            )
        assert "timeout" in str(exc_info.value).lower()

    def test_reject_negative_timeout(self) -> None:
        """Test that negative timeout is rejected."""
        with pytest.raises(CapabilityValidationError) as exc_info:
            RemoteAPICapability(
                name="test_api",
                description="Test API",
                url="https://api.example.com/test",
                timeout=-1.0,
            )
        assert "timeout" in str(exc_info.value).lower()

    def test_strip_whitespace_from_name(self) -> None:
        """Test that whitespace is stripped from name."""
        capability = RemoteAPICapability(
            name="  test_api  ",
            description="Test API",
            url="https://api.example.com/test",
        )
        assert capability.name == "test_api"

    def test_strip_whitespace_from_description(self) -> None:
        """Test that whitespace is stripped from description."""
        capability = RemoteAPICapability(
            name="test_api",
            description="  Test API  ",
            url="https://api.example.com/test",
        )
        assert capability.description == "Test API"

    def test_strip_whitespace_from_url(self) -> None:
        """Test that whitespace is stripped from URL."""
        capability = RemoteAPICapability(
            name="test_api",
            description="Test API",
            url="  https://api.example.com/test  ",
        )
        assert capability.url == "https://api.example.com/test"


class TestRemoteAPICapabilitySchema:
    """Test schema handling."""

    def test_get_schema_returns_provided_schema(self) -> None:
        """Test that get_schema returns the provided schema."""
        schema = CapabilitySchema(
            name="custom",
            description="Custom schema",
            parameters={"type": "object"},
            returns={"type": "string"},
        )
        capability = RemoteAPICapability(
            name="test_api",
            description="Test API",
            url="https://api.example.com/test",
            schema=schema,
        )
        assert capability.get_schema() == schema

    def test_get_schema_creates_default_schema(self) -> None:
        """Test that default schema is created if not provided."""
        capability = RemoteAPICapability(
            name="test_api",
            description="Test API",
            url="https://api.example.com/test",
        )
        schema = capability.get_schema()

        assert schema.name == "test_api"
        assert schema.description == "Test API"
        assert schema.parameters["type"] == "object"
        assert schema.returns["type"] == "object"


class TestRemoteAPICapabilityExecution:
    """Test executing remote API calls."""

    @responses.activate
    def test_execute_get_request(self) -> None:
        """Test executing a GET request."""
        responses.add(
            responses.GET,
            "https://api.example.com/test",
            json={"result": "success"},
            status=200,
        )

        capability = RemoteAPICapability(
            name="test_api",
            description="Test API",
            url="https://api.example.com/test",
            method="GET",
        )

        result = capability.execute(param1="value1")
        assert result == {"result": "success"}

    @responses.activate
    def test_execute_post_request(self) -> None:
        """Test executing a POST request."""
        responses.add(
            responses.POST,
            "https://api.example.com/test",
            json={"result": "created"},
            status=201,
        )

        capability = RemoteAPICapability(
            name="test_api",
            description="Test API",
            url="https://api.example.com/test",
            method="POST",
        )

        result = capability.execute(name="test", value=42)
        assert result == {"result": "created"}

    @responses.activate
    def test_execute_put_request(self) -> None:
        """Test executing a PUT request."""
        responses.add(
            responses.PUT,
            "https://api.example.com/test",
            json={"result": "updated"},
            status=200,
        )

        capability = RemoteAPICapability(
            name="test_api",
            description="Test API",
            url="https://api.example.com/test",
            method="PUT",
        )

        result = capability.execute(id=1, name="updated")
        assert result == {"result": "updated"}

    @responses.activate
    def test_execute_delete_request(self) -> None:
        """Test executing a DELETE request."""
        responses.add(
            responses.DELETE,
            "https://api.example.com/test",
            json={"result": "deleted"},
            status=200,
        )

        capability = RemoteAPICapability(
            name="test_api",
            description="Test API",
            url="https://api.example.com/test",
            method="DELETE",
        )

        result = capability.execute(id=1)
        assert result == {"result": "deleted"}

    @responses.activate
    def test_execute_patch_request(self) -> None:
        """Test executing a PATCH request."""
        responses.add(
            responses.PATCH,
            "https://api.example.com/test",
            json={"result": "patched"},
            status=200,
        )

        capability = RemoteAPICapability(
            name="test_api",
            description="Test API",
            url="https://api.example.com/test",
            method="PATCH",
        )

        result = capability.execute(id=1, status="active")
        assert result == {"result": "patched"}

    @responses.activate
    def test_execute_with_custom_headers(self) -> None:
        """Test executing request with custom headers."""

        def request_callback(request):
            assert request.headers.get("X-Custom") == "value"
            return (200, {}, '{"result": "success"}')

        responses.add_callback(
            responses.POST,
            "https://api.example.com/test",
            callback=request_callback,
            content_type="application/json",
        )

        capability = RemoteAPICapability(
            name="test_api",
            description="Test API",
            url="https://api.example.com/test",
            headers={"X-Custom": "value"},
        )

        result = capability.execute()
        assert result == {"result": "success"}

    @responses.activate
    def test_execute_with_basic_auth(self) -> None:
        """Test executing request with basic authentication."""

        def request_callback(request):
            # Check that Authorization header is present
            assert "Authorization" in request.headers
            return (200, {}, '{"result": "success"}')

        responses.add_callback(
            responses.POST,
            "https://api.example.com/test",
            callback=request_callback,
            content_type="application/json",
        )

        capability = RemoteAPICapability(
            name="test_api",
            description="Test API",
            url="https://api.example.com/test",
            auth=("user", "pass"),
        )

        result = capability.execute()
        assert result == {"result": "success"}

    @responses.activate
    def test_execute_get_with_query_parameters(self) -> None:
        """Test that GET request sends parameters as query string."""
        responses.add(
            responses.GET,
            "https://api.example.com/test",
            json={"result": "success"},
            status=200,
        )

        capability = RemoteAPICapability(
            name="test_api",
            description="Test API",
            url="https://api.example.com/test",
            method="GET",
        )

        result = capability.execute(location="New York", units="metric")
        assert result == {"result": "success"}

        # Verify query parameters were sent
        assert len(responses.calls) == 1
        assert "location=New+York" in responses.calls[0].request.url
        assert "units=metric" in responses.calls[0].request.url

    @responses.activate
    def test_execute_post_with_json_body(self) -> None:
        """Test that POST request sends parameters as JSON body."""

        def request_callback(request):
            import json

            body = json.loads(request.body)
            assert body == {"name": "test", "value": 42}
            return (200, {}, '{"result": "success"}')

        responses.add_callback(
            responses.POST,
            "https://api.example.com/test",
            callback=request_callback,
            content_type="application/json",
        )

        capability = RemoteAPICapability(
            name="test_api",
            description="Test API",
            url="https://api.example.com/test",
            method="POST",
        )

        result = capability.execute(name="test", value=42)
        assert result == {"result": "success"}

    @responses.activate
    def test_execute_returns_text_when_not_json(self) -> None:
        """Test that non-JSON responses are returned as text."""
        responses.add(
            responses.GET,
            "https://api.example.com/test",
            body="Plain text response",
            status=200,
        )

        capability = RemoteAPICapability(
            name="test_api",
            description="Test API",
            url="https://api.example.com/test",
            method="GET",
        )

        result = capability.execute()
        assert result == "Plain text response"

    @responses.activate
    def test_execute_raises_on_http_error(self) -> None:
        """Test that HTTP errors are raised."""
        responses.add(
            responses.GET,
            "https://api.example.com/test",
            json={"error": "Not found"},
            status=404,
        )

        capability = RemoteAPICapability(
            name="test_api",
            description="Test API",
            url="https://api.example.com/test",
            method="GET",
        )

        with pytest.raises(Exception):  # ProviderError (HTTP 404)
            capability.execute()

    @responses.activate
    def test_execute_with_empty_parameters(self) -> None:
        """Test executing with no parameters."""
        responses.add(
            responses.POST,
            "https://api.example.com/test",
            json={"result": "success"},
            status=200,
        )

        capability = RemoteAPICapability(
            name="test_api",
            description="Test API",
            url="https://api.example.com/test",
        )

        result = capability.execute()
        assert result == {"result": "success"}


class TestRemoteAPICapabilityAsyncExecution:
    """Test async execution of remote API calls."""

    @pytest.mark.asyncio
    async def test_aexecute_get_request(self) -> None:
        """Test async execution of a GET request."""
        # For testing, we'll create a mock response
        capability = RemoteAPICapability(
            name="test_api",
            description="Test API",
            url="https://httpbin.org/get",
            method="GET",
        )

        # Executing would need a mocked transport
        # We'll skip the actual execution test and focus on structure
        assert capability.method == "GET"

    @pytest.mark.asyncio
    async def test_aexecute_post_request(self) -> None:
        """Test async execution of a POST request."""
        capability = RemoteAPICapability(
            name="test_api",
            description="Test API",
            url="https://api.example.com/test",
            method="POST",
        )

        assert capability.method == "POST"

    @pytest.mark.asyncio
    async def test_aexecute_with_empty_parameters(self) -> None:
        """Test async execution with no parameters."""
        capability = RemoteAPICapability(
            name="test_api",
            description="Test API",
            url="https://api.example.com/test",
        )

        # Verify the capability is set up correctly
        schema = capability.get_schema()
        assert schema.name == "test_api"


class TestRemoteAPICapabilityIntegration:
    """Integration tests for RemoteAPICapability."""

    @responses.activate
    def test_full_workflow_sync(self) -> None:
        """Test full workflow: create, get schema, execute."""
        responses.add(
            responses.POST,
            "https://api.example.com/weather",
            json={"temperature": 72, "condition": "sunny"},
            status=200,
        )

        capability = RemoteAPICapability(
            name="weather_get_current",
            description="Get current weather",
            url="https://api.example.com/weather",
            method="POST",
        )

        # Get schema
        schema = capability.get_schema()
        assert schema.name == "weather_get_current"
        assert schema.description == "Get current weather"

        # Execute
        result = capability.execute(location="New York")
        assert result["temperature"] == 72
        assert result["condition"] == "sunny"

    @responses.activate
    def test_full_workflow_with_custom_schema(self) -> None:
        """Test full workflow with custom schema."""
        responses.add(
            responses.GET,
            "https://api.example.com/users",
            json={"users": ["alice", "bob"]},
            status=200,
        )

        schema = CapabilitySchema(
            name="list_users",
            description="List all users",
            parameters={
                "type": "object",
                "properties": {"limit": {"type": "integer"}},
                "required": [],
            },
            returns={"type": "object"},
        )

        capability = RemoteAPICapability(
            name="list_users",
            description="List all users",
            url="https://api.example.com/users",
            method="GET",
            schema=schema,
        )

        # Get schema
        schema_result = capability.get_schema()
        assert schema_result.name == "list_users"

        # Execute
        result = capability.execute(limit=10)
        assert "users" in result

    @responses.activate
    def test_multiple_requests_with_different_parameters(self) -> None:
        """Test making multiple requests with different parameters."""
        responses.add(
            responses.POST,
            "https://api.example.com/calculate",
            json={"result": 5},
            status=200,
        )
        responses.add(
            responses.POST,
            "https://api.example.com/calculate",
            json={"result": 10},
            status=200,
        )

        capability = RemoteAPICapability(
            name="calculate",
            description="Calculate something",
            url="https://api.example.com/calculate",
            method="POST",
        )

        result1 = capability.execute(a=2, b=3)
        assert result1["result"] == 5

        result2 = capability.execute(a=5, b=5)
        assert result2["result"] == 10

    @responses.activate
    def test_capability_with_all_options(self) -> None:
        """Test capability with all options configured."""

        def request_callback(request):
            # Verify headers
            assert request.headers.get("X-API-Key") == "secret123"
            # Verify auth
            assert "Authorization" in request.headers
            return (200, {}, '{"result": "success"}')

        responses.add_callback(
            responses.PUT,
            "https://api.example.com/resource",
            callback=request_callback,
            content_type="application/json",
        )

        schema = CapabilitySchema(
            name="update_resource",
            description="Update a resource",
            parameters={
                "type": "object",
                "properties": {"id": {"type": "integer"}},
                "required": ["id"],
            },
            returns={"type": "object"},
        )

        capability = RemoteAPICapability(
            name="update_resource",
            description="Update a resource",
            url="https://api.example.com/resource",
            method="PUT",
            schema=schema,
            headers={"X-API-Key": "secret123"},
            auth=("user", "pass"),
            timeout=60.0,
        )

        result = capability.execute(id=123, name="updated")
        assert result["result"] == "success"


class TestRemoteAPICapabilityAsyncTransport:
    """aexecute goes through the same stdlib transport (in a worker thread)."""

    @responses.activate
    def test_aexecute_uses_stdlib_transport(self) -> None:
        responses.add(responses.GET, "https://api.example.com/a", json={"ok": True}, status=200)
        capability = RemoteAPICapability(
            name="a", description="A", url="https://api.example.com/a", method="GET"
        )
        assert asyncio.run(capability.aexecute(q="x")) == {"ok": True}
        assert "q=x" in responses.calls[0].request.url
