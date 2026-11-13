"""Remote API capability implementation.

This module provides the RemoteAPICapability class for wrapping HTTP APIs
as capabilities that can be invoked by LLMs.
"""

import asyncio
import json
import logging
from typing import Any

from skye.base.http import HttpResponse
from skye.base.http import request as http_request
from skye.base.interfaces.capability import CapabilityInterface, CapabilitySchema
from skye.tools.exceptions import CapabilityValidationError

logger = logging.getLogger(__name__)

# Supported HTTP methods
SUPPORTED_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH"}


class RemoteAPICapability(CapabilityInterface):
    """Capability wrapping a remote HTTP API.

    Allows invoking external HTTP APIs as capabilities. Supports various
    HTTP methods, authentication, custom headers, and timeout configuration.

    Attributes:
        name: The capability name
        description: The capability description
        url: The API endpoint URL
        method: HTTP method (GET, POST, PUT, DELETE, PATCH)
        schema: The capability schema
        headers: Custom HTTP headers
        auth: Basic authentication tuple (username, password)
        timeout: Request timeout in seconds

    Example:
        >>> capability = RemoteAPICapability(
        ...     name="weather_get_current",
        ...     description="Get current weather",
        ...     url="https://api.weather.com/current",
        ...     method="GET",
        ...     schema=CapabilitySchema(
        ...         name="weather_get_current",
        ...         description="Get current weather",
        ...         parameters={
        ...             "type": "object",
        ...             "properties": {
        ...                 "location": {"type": "string"}
        ...             },
        ...             "required": ["location"]
        ...         },
        ...         returns={"type": "object"}
        ...     )
        ... )
        >>> result = capability.execute(location="New York")
        >>> # For async:
        >>> result = await capability.aexecute(location="New York")
    """

    def __init__(
        self,
        name: str,
        description: str,
        url: str,
        method: str = "POST",
        schema: CapabilitySchema | None = None,
        headers: dict[str, str] | None = None,
        auth: tuple[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        """Initialize RemoteAPICapability.

        Args:
            name: The capability name
            description: The capability description
            url: The API endpoint URL
            method: HTTP method (GET, POST, PUT, DELETE, PATCH). Defaults to POST.
            schema: The capability schema. If not provided, a basic schema is created.
            headers: Optional custom HTTP headers
            auth: Optional basic authentication tuple (username, password)
            timeout: Request timeout in seconds. Defaults to 30.0.

        Raises:
            CapabilityValidationError: If parameters are invalid
        """
        if not name or not name.strip():
            raise CapabilityValidationError(
                "name cannot be empty",
                capability_name="<unknown>",
            )

        if not description or not description.strip():
            raise CapabilityValidationError(
                "description cannot be empty",
                capability_name=name,
            )

        if not url or not url.strip():
            raise CapabilityValidationError(
                "url cannot be empty",
                capability_name=name,
            )

        method_upper = method.upper()
        if method_upper not in SUPPORTED_METHODS:
            raise CapabilityValidationError(
                f"Unsupported HTTP method '{method}'. "
                f"Supported methods: {', '.join(SUPPORTED_METHODS)}",
                capability_name=name,
            )

        if timeout <= 0:
            raise CapabilityValidationError(
                f"timeout must be positive, got {timeout}",
                capability_name=name,
            )

        self.name = name.strip()
        self.description = description.strip()
        self.url = url.strip()
        self.method = method_upper
        self.headers = headers or {}
        self.auth = auth
        self.timeout = timeout

        # Create default schema if not provided
        if schema is None:
            self._schema = CapabilitySchema(
                name=self.name,
                description=self.description,
                parameters={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
                returns={"type": "object"},
            )
        else:
            self._schema = schema

    def get_schema(self) -> CapabilitySchema:
        """Get the schema for this capability.

        Returns:
            CapabilitySchema: The schema definition for this capability
        """
        return self._schema

    def execute(self, **kwargs: Any) -> Any:
        """Execute the API call synchronously.

        Args:
            **kwargs: Arguments to pass to the API. These are typically
                used as query parameters (GET) or request body (POST/PUT).

        Returns:
            The parsed JSON response from the API

        Raises:
            CapabilityValidationError: If arguments don't match schema
            Exception: If the HTTP request fails
        """
        try:
            response = self._make_request(kwargs)
            result = self._parse_response(response)

            logger.debug(
                "Remote API call executed successfully",
                extra={
                    "capability_name": self.name,
                    "url": self.url,
                    "method": self.method,
                    "status_code": response.status_code,
                },
            )
            return result
        except Exception as e:
            logger.error(
                "Remote API call failed",
                extra={
                    "capability_name": self.name,
                    "url": self.url,
                    "method": self.method,
                    "error": str(e),
                },
            )
            raise

    async def aexecute(self, **kwargs: Any) -> Any:
        """Execute the API call asynchronously.

        Args:
            **kwargs: Arguments to pass to the API. These are typically
                used as query parameters (GET) or request body (POST/PUT).

        Returns:
            The parsed JSON response from the API

        Raises:
            CapabilityValidationError: If arguments don't match schema
            Exception: If the HTTP request fails
        """
        try:
            response = await self._make_request_async(kwargs)
            result = self._parse_response(response)

            logger.debug(
                "Remote API call executed successfully (async)",
                extra={
                    "capability_name": self.name,
                    "url": self.url,
                    "method": self.method,
                    "status_code": response.status_code,
                },
            )
            return result
        except Exception as e:
            logger.error(
                "Remote API call failed (async)",
                extra={
                    "capability_name": self.name,
                    "url": self.url,
                    "method": self.method,
                    "error": str(e),
                },
            )
            raise

    def _make_request(self, params: dict[str, Any]) -> HttpResponse:
        """Make a synchronous HTTP request (stdlib ``urllib`` transport).

        Args:
            params: Request parameters (query string for GET, JSON body otherwise)

        Returns:
            The HTTP response

        Raises:
            ProviderError: If the request fails or the status is an HTTP error
        """
        is_get = self.method == "GET"
        return http_request(
            self.url,
            self.method,
            params=params if is_get else None,
            json_body=None if is_get else params,
            headers=self.headers,
            auth=self.auth,
            timeout=self.timeout,
            provider=self.name,
        )

    async def _make_request_async(self, params: dict[str, Any]) -> HttpResponse:
        """Make an HTTP request without blocking the event loop (sync transport in a thread)."""
        return await asyncio.to_thread(self._make_request, params)

    @staticmethod
    def _parse_response(response: HttpResponse) -> Any:
        """Parse the HTTP response.

        Attempts to parse as JSON. If that fails, returns the text content.

        Args:
            response: The HTTP response

        Returns:
            Parsed response (JSON or text)
        """
        try:
            return response.json()
        except (json.JSONDecodeError, ValueError):
            # If not JSON, return text
            return response.text
