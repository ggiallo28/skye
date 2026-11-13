# task 4.3, D110
"""The OpenAI wire format, for any endpoint that speaks it: the provider class (structure).

One parametrized adapter, ``OpenAICompatibleProvider``, serves every OpenAI wire-compatible
endpoint (vLLM, Ollama, LM Studio, Together, ...), keyed by ``api_base`` + ``api_key``. What belongs to
one vendor lives in its own folder: ``plugins/openai`` (``OpenAIProvider``) and ``plugins/azure`` (``AzureOpenAIProvider``).

The class holds the constructor, the endpoint, the calls and the model info. The rest is in the files of this package, with the same
names as in every provider folder: ``request.py`` (building the request), ``response.py`` (reading a response and a stream chunk) and
``capabilities.py`` (capabilities out and back). The methods of the class with the same names call them, so a subclass can still override
one of them.

Features:
- Standard-library REST transport (no vendor SDK)
- Structured outputs via response_format
- Function calling
- Streaming support
- Async support (sync call run in an executor)
- Multimodal inputs (images)

Example:
    >>> from skye.models.utilities.openai_compatible import OpenAICompatibleProvider
    >>> from skye.base.completion import CompleteRequest
    >>> from skye.base.messages import UserMessage
    >>>
    >>> provider = OpenAICompatibleProvider(api_key="sk-...", api_base="http://localhost:8000/v1")
    >>> request = CompleteRequest(
    ...     messages=[UserMessage(content="Hello")],
    ...     model="gpt-4"
    ... )
    >>> response = provider.complete(request)
    >>> print(response.content)
"""

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

from skye.base.completion import CompleteRequest, CompleteResponse, StreamChunk
from skye.base.exceptions import ConfigurationError
from skye.base.interfaces.authentication import AuthenticationInterface
from skye.models.base import BaseModelProvider
from skye.models.utilities.openai_compatible import capabilities as _capabilities
from skye.models.utilities.openai_compatible import request as _request
from skye.models.utilities.openai_compatible import response as _response
from skye.models.utilities import rest
from skye.models.utilities.blocking import aiterate_blocking
from skye.base.api_keys import api_key_variables
from skye.models.utilities.credentials import resolve_api_key


class OpenAICompatibleProvider(BaseModelProvider):
    """Provider for any endpoint that speaks the OpenAI chat-completions format.

    Args:
        api_key: Key sent as a bearer token
        api_base: Base URL of the endpoint, up to and including ``/v1``
        **kwargs: Additional configuration parameters

    Example:
        >>> provider = OpenAICompatibleProvider(api_key="none", api_base="http://localhost:8000/v1")
        >>> response = provider.complete(request)
    """

    #: Base URL used when ``api_base`` is not given; a vendor subclass sets it.
    default_api_base: str | None = None
    #: Provider label reported in responses / model info.
    provider_name = "openai_compatible"
    #: Metadata keys with this prefix are forwarded to the API as extra params.
    metadata_prefix = "openai_"
    #: Whether response metadata carries ``system_fingerprint``.
    reports_fingerprint = False
    #: Ask the endpoint for the token usage of a stream (``stream_options.include_usage``). Off here because an
    #: OpenAI-compatible endpoint may reject the field; ``OpenAIProvider`` turns it on.
    streams_usage = False

    def __init__(
        self, api_key: str | None = None, api_base: str | None = None, **kwargs: Any
    ) -> None:
        """Initialize the provider.

        Args:
            api_key: Key sent as a bearer token; the first variable of ``api_key_variables`` of the profile of ``provider_name`` when omitted
            api_base: Base URL of the endpoint (default: ``default_api_base``)
            **kwargs: Additional configuration parameters

        Raises:
            ConfigurationError: No key is given and the standard variable is not set (the error names it).
        """
        api_key = resolve_api_key(api_key, api_key_variables(self.provider_name))
        super().__init__(api_key=api_key, api_base=api_base, **kwargs)
        self.api_key: str | None = api_key
        self.api_base = api_base

    def _initialize_client(self) -> Any:
        """No vendor client: requests go through the standard-library REST transport."""
        return None

    def _endpoint_url(self) -> str:
        """Chat-completions URL."""
        base = self.api_base or self.default_api_base
        if not base:
            raise ConfigurationError("api_base is required for an OpenAI-compatible endpoint")
        return f"{base.rstrip('/')}/chat/completions"

    def _auth_headers(self) -> dict[str, str]:
        """Authentication headers for the endpoint."""
        return {"Authorization": f"Bearer {self.api_key}"}

    def _authenticator(self) -> AuthenticationInterface | None:
        """An authenticator that signs each request (Azure Entra ID); ``None`` when the headers are enough."""
        return None

    def _model_name(self, request: CompleteRequest) -> str:
        """Model identifier sent to the endpoint."""
        return request.model

    def _transform_messages(self, messages: list[Any]) -> list[dict[str, Any]]:
        """Transform Skye messages to OpenAI format (see ``request.transform_messages``)."""
        return _request.transform_messages(messages)

    def _transform_capabilities(self, capabilities: list[Any]) -> list[dict[str, Any]]:
        """Transform Skye capabilities to OpenAI function calling format (see ``capabilities.transform_capabilities``)."""
        return _capabilities.transform_capabilities(capabilities)

    def _extract_capability_calls(self, response: Any) -> list[Any] | None:
        """Extract capability calls from OpenAI response (see ``capabilities.extract_capability_calls``)."""
        return _capabilities.extract_capability_calls(response)

    def _transform_request(self, request: CompleteRequest) -> dict[str, Any]:
        """Transform CompleteRequest to OpenAI format (see ``request.transform_request``)."""
        return _request.transform_request(self, request)

    def _transform_response(self, response: Any) -> CompleteResponse:
        """Transform OpenAI response to CompleteResponse (see ``response.transform_response``)."""
        return _response.transform_response(self, response)

    def _response_metadata(self, response: Any, tool_calls: Any) -> dict[str, Any]:
        """Response metadata; ``system_fingerprint`` only where the endpoint reports it (see ``response.response_metadata``)."""
        return _response.response_metadata(self, response, tool_calls)

    def _transform_stream_chunk(self, chunk: Any) -> StreamChunk:
        """Transform OpenAI stream chunk to StreamChunk (see ``response.transform_stream_chunk``)."""
        return _response.transform_stream_chunk(chunk)

    async def _acall_provider(self, request: dict[str, Any]) -> Any:
        """POST to the chat-completions endpoint and return the decoded JSON view (the blocking call runs in a worker thread)."""
        return await asyncio.to_thread(
            rest.post_json,
            self._endpoint_url(),
            request,
            headers=self._auth_headers(),
            authenticator=self._authenticator(),
            provider=self.provider_name,
        )

    def _acall_provider_stream(self, request: dict[str, Any]) -> AsyncGenerator[Any, None]:
        """Stream the chat-completions endpoint (SSE), yielding decoded chunks."""
        payload = {**request, "stream": True}
        if self.streams_usage:
            payload.setdefault("stream_options", {"include_usage": True})
        return aiterate_blocking(
            lambda: rest.stream_sse_json(
                self._endpoint_url(),
                payload,
                headers=self._auth_headers(),
                authenticator=self._authenticator(),
                provider=self.provider_name,
            )
        )

    def format_capability_results(self, results: list[Any]) -> list[dict[str, Any]]:
        """Format capability results for OpenAI (see ``capabilities.format_capability_results``)."""
        return _capabilities.format_capability_results(results)

    def get_model_info(self) -> dict[str, Any]:
        """Return model metadata and capabilities.

        Returns:
            Dictionary with provider information and capabilities
        """
        return {
            "provider": self.provider_name,
            "supports_streaming": True,
            "supports_function_calling": True,
            "supports_structured_output": True,
            "supports_multimodal": True,
            **self._profile_info(self.provider_name),
        }


__all__ = ["OpenAICompatibleProvider"]
