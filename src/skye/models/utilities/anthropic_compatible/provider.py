# D110
"""``AnthropicCompatibleProvider``: the class of the Anthropic Messages format.

The constructor, the URL and headers, the two calls (``POST /v1/messages``, plain and streamed), the async wrapper and the model info are here.
How a request is built is in ``request.py``, how a response and a stream event are read in ``response.py``, and the capabilities (tool definitions
out, tool calls back, results formatted) in ``capabilities.py``. The methods of the class keep their names and signatures and call those functions,
so a subclass can still override any of them.

Raises: ``ConfigurationError`` when no ``api_base`` or no key is available.
Missing: ``api_base`` has no default here; a vendor subclass sets ``default_api_base``.
Concurrency: a provider holds no mutable state after construction; one instance serves many threads.
"""

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

from skye.base.completion import CompleteRequest, CompleteResponse, StreamChunk
from skye.base.exceptions import ConfigurationError
from skye.models.utilities.anthropic_compatible.capabilities import (
    extract_capability_calls,
    format_capability_results,
    plain,
    transform_capabilities,
)
from skye.models.utilities.anthropic_compatible import request as wire_request
from skye.models.utilities.anthropic_compatible import response as wire_response
from skye.models.base import BaseModelProvider
from skye.models.utilities import rest
from skye.models.utilities.blocking import aiterate_blocking
from skye.base.api_keys import api_key_variables
from skye.models.utilities.credentials import resolve_api_key

ANTHROPIC_VERSION = "2023-06-01"

class AnthropicCompatibleProvider(BaseModelProvider):
    """Provider for any endpoint that speaks the Anthropic Messages format.

    Args:
        api_key: Key sent in the ``x-api-key`` header
        api_base: Base URL of the endpoint (default: ``default_api_base``)
        timeout: Seconds before a call fails (default 60)
        **kwargs: Additional configuration parameters

    Example:
        >>> provider = AnthropicCompatibleProvider(api_key="none", api_base="http://localhost:8000")
        >>> response = provider.complete(request)
    """

    #: Base URL used when ``api_base`` is not given; a vendor subclass sets it.
    default_api_base: str | None = None
    #: Provider label reported in errors and model info.
    provider_name = "anthropic_compatible"

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        """Initialize the provider.

        Args:
            api_key: The key; the first variable of ``api_key_variables`` of the profile of ``provider_name`` when omitted
            **kwargs: Additional configuration parameters

        Raises:
            ConfigurationError: No key is given and the standard variable is not set (the error names it).
        """
        api_key = resolve_api_key(api_key, api_key_variables(self.provider_name))
        base = kwargs.pop("api_base", None) or self.default_api_base
        if not base:
            raise ConfigurationError("api_base is required for an Anthropic-compatible endpoint")
        self.api_base = str(base).rstrip("/")
        self.timeout = float(kwargs.pop("timeout", 60.0))
        super().__init__(api_key=api_key, **kwargs)
        self.api_key = api_key

    @property
    def _url(self) -> str:
        return f"{self.api_base}/v1/messages"

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self.api_key, "anthropic-version": ANTHROPIC_VERSION}

    def _initialize_client(self) -> Any:
        """No SDK client: requests go through the stdlib REST transport."""
        return None

    def _transform_messages(self, messages: list[Any]) -> tuple[str | None, list[dict[str, Any]]]:
        """Skye messages to ``(system, anthropic_messages)`` (see ``request.transform_messages``)."""
        return wire_request.transform_messages(messages)

    def _transform_capabilities(self, capabilities: list[Any]) -> list[dict[str, Any]]:
        """Skye capabilities to Anthropic tool definitions (see ``capabilities.transform_capabilities``)."""
        return transform_capabilities(capabilities)

    @staticmethod
    def _plain(value: Any) -> Any:
        """Unwrap a JsonObject (tool ``input``) back to a plain dict."""
        return plain(value)

    def _extract_capability_calls(self, response: Any) -> list[Any] | None:
        """The capability calls of an Anthropic response, or ``None`` (see ``capabilities.extract_capability_calls``)."""
        return extract_capability_calls(response, self._plain)

    def _transform_request(self, request: CompleteRequest) -> dict[str, Any]:
        """A ``CompleteRequest`` in Anthropic format (see ``request.transform_request``)."""
        return wire_request.transform_request(
            request, self._transform_messages, self._transform_capabilities
        )

    def _transform_response(self, response: Any) -> CompleteResponse:
        """An Anthropic response as a ``CompleteResponse`` (see ``response.transform_response``)."""
        return wire_response.transform_response(
            response, self.provider_name, self._plain, self._extract_capability_calls
        )

    def _transform_stream_chunk(self, chunk: Any) -> StreamChunk:
        """An Anthropic stream event as a ``StreamChunk`` (see ``response.transform_stream_chunk``)."""
        return wire_response.transform_stream_chunk(chunk)

    async def _acall_provider(self, request: dict[str, Any]) -> Any:
        """POST the request to ``/v1/messages``; return the JSON as a JsonObject (the blocking call runs in a worker thread)."""
        return await asyncio.to_thread(
            rest.post_json,
            self._url,
            request,
            headers=self._headers(),
            timeout=self.timeout,
            provider=self.provider_name,
        )

    def _acall_provider_stream(self, request: dict[str, Any]) -> AsyncGenerator[Any, None]:
        """Stream SSE events from ``/v1/messages`` (``stream: true``)."""
        return aiterate_blocking(
            lambda: rest.stream_sse_json(
                self._url,
                {**request, "stream": True},
                headers=self._headers(),
                timeout=self.timeout,
                provider=self.provider_name,
            )
        )

    def format_capability_results(self, results: list[Any]) -> list[dict[str, Any]]:
        """Format capability results as Anthropic ``tool_result`` blocks (see ``capabilities.format_capability_results``)."""
        return format_capability_results(results)

    # D109
    def refuses_forced_choice(self, model: str) -> bool:
        """Whether ``model`` refuses a forced ``tool_choice``: its profile says ``supports_forced_capability_choice`` is false."""
        return self.get_model_info(model).get("supports_forced_capability_choice") is False

    def get_model_info(self, model: str | None = None) -> dict[str, Any]:
        """Return model metadata and capabilities, with the ``info`` of the model's entry in the provider profile merged in.

        Args:
            model: The model to describe; the default model of the client when omitted.

        Returns:
            Dictionary with provider information and capabilities
        """
        return {
            "provider": self.provider_name,
            "supports_streaming": True,
            "supports_function_calling": True,  # Via tool use
            "supports_structured_output": True,  # Native: output_config.format (json_schema)
            "supports_multimodal": True,  # Claude 3 supports images
            "supports_thinking": True,  # Claude 3 Opus supports extended thinking
            **self._profile_info(self.provider_name, model),
        }


__all__ = [
    "ANTHROPIC_VERSION",
    "AnthropicCompatibleProvider",
]
