"""Google (Gemini Enterprise Agent Platform, formerly Vertex AI) provider implementation.

Renamed from `vertex` (Google renamed Vertex AI to Gemini Enterprise Agent Platform in April 2026); the extra is now `google`.

This module provides the Google Cloud implementation of the ModelInterface,
supporting Gemini and other Google models.

Features:
- Built-in stdlib REST adapter (no vendor SDK): ``generateContent`` / ``streamGenerateContent``
- Support for Gemini models
- Safety settings configuration
- Grounding features
- Streaming support
- Async support
- Multimodal inputs (images, video)

Example:
    >>> from skye.models.plugins.google.provider import GoogleProvider
    >>> from skye.base.completion import CompleteRequest
    >>> from skye.base.messages import UserMessage
    >>>
    >>> provider = GoogleProvider(
    ...     project_id="my-project",
    ...     location="us-central1"
    ... )
    >>> request = CompleteRequest(
    ...     messages=[UserMessage(content="Hello")],
    ...     model="gemini-1.5-pro"
    ... )
    >>> response = provider.complete(request)
    >>> print(response.content)
"""

import asyncio
from collections.abc import Iterator
from typing import Any

from skye.auth.plugins.google import resolve_google_auth
from skye.base.completion import CompleteRequest, CompleteResponse, StreamChunk
from skye.base.interfaces.authentication import AuthenticationInterface
from skye.base.prompt_parts import PromptParts
from skye.models.base import BaseModelProvider
from skye.models.plugins.google import capabilities, request, response
from skye.models.plugins.google.capabilities import as_args as _as_args  # noqa: F401  (kept importable from here)
from skye.models.utilities import rest
from skye.models.utilities.rest import JsonObject


def _model_url(location: str, project_id: str, model: str, method: str) -> str:
    """Vertex AI publisher-model URL (the ``global`` location uses the bare host)."""
    host = (
        "aiplatform.googleapis.com"
        if location == "global"
        else f"{location}-aiplatform.googleapis.com"
    )
    return (
        f"https://{host}/v1/projects/{project_id}/locations/{location}"
        f"/publishers/google/models/{model}:{method}"
    )


class GoogleProvider(BaseModelProvider):
    """Google provider implementation.

    Implements the ModelInterface for Google Cloud's Google API, supporting
    Gemini models and other Google generative models.

    Args:
        project_id: Google Cloud project ID
        location: Google Cloud region (e.g., 'us-central1')
        credentials: Optional AuthenticationInterface or access token string. If not
                    provided, resolved from the environment (access token, API key,
                    metadata server).
        **kwargs: Additional configuration parameters

    Example:
        >>> provider = GoogleProvider(
        ...     project_id="my-project",
        ...     location="us-central1"
        ... )
        >>> response = provider.complete(request)
    """

    def __init__(
        self,
        project_id: str,
        location: str = "us-central1",
        credentials: Any = None,
        model: str | None = None,
        router: Any | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize Google provider.

        Args:
            project_id: Google Cloud project ID
            location: Google Cloud region (default: us-central1)
            credentials: Optional credentials object
            model: Optional default model identifier (can be overridden in request)
            router: Optional model router for load balancing
            **kwargs: Additional configuration parameters
        """
        # For Google, model is typically specified in the request, not at init
        # If neither model nor router is provided, use a placeholder
        if model is None and router is None:
            model = "gemini-1.5-pro"  # Default model as placeholder

        super().__init__(
            model=model,
            router=router,
            project_id=project_id,
            location=location,
            credentials=credentials,
            **kwargs,
        )
        self.project_id = project_id
        self.location = location
        self.credentials = credentials

    def _initialize_client(self) -> Any:
        """No vendor SDK: requests go through the stdlib REST transport."""
        return None

    @property
    def authenticator(self) -> AuthenticationInterface:
        """The request authenticator (resolved lazily on first use)."""
        auth = getattr(self, "_authenticator", None)
        if auth is None:
            auth = resolve_google_auth(self.credentials)
            self._authenticator = auth
        return auth

    def _transform_messages(self, messages: list[Any]) -> list[dict[str, Any]]:
        """Transform Skye messages to Google (Gemini) format (see :func:`skye.models.plugins.google.request.transform_messages`)."""
        return request.transform_messages(messages)

    def _transform_capabilities(self, capabilities_: list[Any]) -> list[dict[str, Any]]:
        """Transform Skye capabilities to Google Gemini format (see :func:`skye.models.plugins.google.capabilities.transform_capabilities`)."""
        return capabilities.transform_capabilities(capabilities_)

    def _extract_capability_calls(self, response_: Any) -> list[Any] | None:
        """Extract ``functionCall`` parts from a ``generateContent`` response; ``None`` when there are none."""
        return capabilities.extract_capability_calls(response_)

    def _transform_request(self, request_: CompleteRequest) -> dict[str, Any]:
        """Transform CompleteRequest to the Vertex AI REST body (see :func:`skye.models.plugins.google.request.transform_request`).

        The returned dict carries ``model`` (consumed by ``_call_provider``, not sent). ``_transform_messages`` and ``_transform_capabilities`` of this
        instance are the ones used, so a subclass that overrides one keeps working.
        """
        return request.transform_request(
            request_, self._transform_messages, self._transform_capabilities
        )

    @staticmethod
    def _first_candidate(response_: JsonObject) -> JsonObject | None:
        return response.first_candidate(response_)

    @staticmethod
    def _finish_reason(candidate: JsonObject) -> str | None:
        return response.finish_reason(candidate)

    def _transform_response(self, response_: Any) -> CompleteResponse:
        """Transform a ``generateContent`` JSON response to CompleteResponse (see :func:`skye.models.plugins.google.response.transform_response`)."""
        return response.transform_response(response_, self._extract_capability_calls)

    def _transform_stream_chunk(self, chunk: Any) -> StreamChunk:
        """Transform one SSE event of ``streamGenerateContent`` to StreamChunk."""
        return response.transform_stream_chunk(chunk)

    def _prepare_call(self, request: dict[str, Any], method: str) -> tuple[str, dict[str, Any]]:
        body = dict(request)
        model_name = body.pop("model")
        return _model_url(self.location, self.project_id, model_name, method), body

    def _call_provider(self, request: dict[str, Any]) -> JsonObject:
        """POST ``:generateContent`` and return the JSON response."""
        url, body = self._prepare_call(request, "generateContent")
        return rest.post_json(url, body, authenticator=self.authenticator, provider="google")

    def _call_provider_stream(self, request: dict[str, Any]) -> Iterator[JsonObject]:
        """POST ``:streamGenerateContent?alt=sse`` and yield decoded SSE events."""
        url, body = self._prepare_call(request, "streamGenerateContent")
        return rest.stream_sse_json(
            url + "?alt=sse", body, authenticator=self.authenticator, provider="google"
        )

    async def acomplete(
        self,
        messages: list[Any] | str | CompleteRequest | PromptParts | None = None,
        model: str | None = None,
        router: Any | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> CompleteResponse:
        """Asynchronous completion: runs the blocking REST call in the default executor."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: self.complete(messages, model, router, temperature, max_tokens, **kwargs)
        )

    def format_capability_results(self, results: list[Any]) -> list[dict[str, Any]]:
        """Format capability results as Google ``functionResponse`` entries (see :func:`skye.models.plugins.google.capabilities.format_capability_results`)."""
        return capabilities.format_capability_results(results)

    def get_model_info(self) -> dict[str, Any]:
        """Return model metadata and capabilities.

        Returns:
            Dictionary with provider information and capabilities
        """
        return {
            "provider": "google",
            "supports_streaming": True,
            "supports_function_calling": True,
            "supports_structured_output": True,  # responseSchema (D101)
            "supports_multimodal": True,
        }
