"""AWS Bedrock provider implementation.

This module provides the AWS Bedrock implementation of the ModelInterface,
supporting Claude, Titan, Llama, and other models available through Bedrock.

Features:
- Built-in stdlib REST transport with SigV4 / Bedrock API key auth (no vendor SDK)
- Bedrock Converse API for unified multi-model access
- Tool/function calling support
- Streaming support
- Multimodal inputs (images)

Example:
    >>> from skye.models.plugins.bedrock.provider import BedrockProvider
    >>> from skye.base.completion import CompleteRequest
    >>> from skye.base.messages import UserMessage
    >>>
    >>> provider = BedrockProvider(region_name="us-east-1")  # or set AWS_REGION and pass nothing
    >>> request = CompleteRequest(
    ...     messages=[UserMessage(content="Hello")],
    ...     model="anthropic.claude-3-sonnet-20240229-v1:0"
    ... )
    >>> response = provider.complete(request)
    >>> print(response.content)
"""

import asyncio
import urllib.parse
from collections.abc import Iterator
from typing import Any

from skye.base.prompt_parts import PromptParts
from skye.base.completion import CompleteRequest, CompleteResponse, StreamChunk
from skye.base.interfaces.authentication import AuthenticationInterface
from skye.models.base import BaseModelProvider
from skye.models.plugins.bedrock import capabilities as _capabilities
from skye.models.plugins.bedrock import request as _request
from skye.models.plugins.bedrock import response as _response
from skye.models.utilities.credentials import resolve_aws_region
from skye.models.utilities import rest
from skye.models.utilities.eventstream import post_eventstream_json


def _base_model_id(model: str | None) -> str:
    """A Bedrock model id without the geography of a cross-Region inference profile.

    ``us.anthropic.claude-sonnet-5-5-v1:0`` and ``eu.anthropic...`` are the same model as ``anthropic.claude-sonnet-5-5-v1:0``: the first segment
    names a geography when a vendor segment (a token with no hyphen, such as ``anthropic``) follows it and then the model.
    """
    name = model or ""
    parts = name.split(".", 2)
    if len(parts) == 3 and "-" not in parts[1] and parts[1]:
        return ".".join(parts[1:])
    return name


class BedrockProvider(BaseModelProvider):
    """AWS Bedrock provider implementation.

    Implements the ModelInterface for AWS Bedrock's Converse API, supporting
    multiple model families including Claude, Titan, Llama, and others.

    Uses the built-in stdlib REST adapter; no AWS SDK is imported.

    Args:
        region_name: AWS region name; when omitted, the region of ``authenticator``, then
            ``AWS_REGION``, then ``AWS_DEFAULT_REGION`` (there is no silent default)
        profile_name: Optional AWS profile name
        authenticator: An authenticator already built (``skye.auth.plugins.aws.bedrock_authenticator``);
            its ``region`` is used when ``region_name`` is not given
        **kwargs: Additional configuration parameters (``api_key``, ``aws_access_key_id``,
            ``aws_secret_access_key``, ``aws_session_token``, ``endpoint_url``, ``timeout``)

    Raises:
        ConfigurationError: No region is given or found; the message names ``AWS_REGION``.

    Example:
        >>> provider = BedrockProvider(region_name="us-west-2")
        >>> response = provider.complete(request)
    """

    provider_name = "bedrock"  # the name of its profile; a plugin sets its own

    def __init__(
        self,
        region_name: str | None = None,
        profile_name: str | None = None,
        authenticator: AuthenticationInterface | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize Bedrock provider.

        Args:
            region_name: AWS region name (see the class docstring for the fallbacks)
            profile_name: Optional AWS profile name
            authenticator: Optional authenticator already built
            **kwargs: Additional configuration parameters
        """
        region = resolve_aws_region(region_name, authenticator)
        super().__init__(region_name=region, profile_name=profile_name, **kwargs)
        self.region_name = region
        self.profile_name = profile_name
        self._auth: Any = authenticator

    def _initialize_client(self) -> Any:
        """No vendor client: requests go through the stdlib REST transport."""
        return None

    def _authenticator(self) -> Any:
        if self._auth is None:
            from skye.auth.plugins.aws import bedrock_authenticator

            self._auth = bedrock_authenticator(
                self.region_name,
                api_key=self.config.get("api_key"),
                profile_name=self.profile_name,
                access_key=self.config.get("aws_access_key_id"),
                secret_key=self.config.get("aws_secret_access_key"),
                session_token=self.config.get("aws_session_token"),
            )
        return self._auth

    def _url(self, request: dict[str, Any], operation: str) -> tuple[str, dict[str, Any]]:
        body = {k: v for k, v in request.items() if k != "modelId"}
        model = urllib.parse.quote(str(request["modelId"]), safe="")
        host = (
            self.config.get("endpoint_url")
            or f"https://bedrock-runtime.{self.region_name}.amazonaws.com"
        )
        return f"{host}/model/{model}/{operation}", body

    async def acomplete(
        self,
        messages: list[Any] | str | CompleteRequest | PromptParts | None = None,
        model: str | None = None,
        router: Any | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> CompleteResponse:
        """Run :meth:`complete` in an executor so the event loop is not blocked."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: self.complete(messages, model, router, temperature, max_tokens, **kwargs)
        )

    def _transform_messages(self, messages: list[Any]) -> list[dict[str, Any]]:
        """Skye messages to Converse messages (see ``request.transform_messages``)."""
        return _request.transform_messages(messages)

    def _transform_capabilities(self, capabilities: list[Any]) -> list[dict[str, Any]]:
        """Skye capabilities to Converse ``toolSpec`` entries (see ``capabilities.transform_capabilities``)."""
        return _capabilities.transform_capabilities(capabilities)

    def _extract_capability_calls(self, response: Any) -> list[Any] | None:
        """The capability calls of a Converse response (see ``capabilities.extract_capability_calls``)."""
        return _capabilities.extract_capability_calls(response)

    def _transform_request(self, request: CompleteRequest) -> dict[str, Any]:
        """A ``CompleteRequest`` as a Converse API request (see ``request.transform_request``)."""
        native = bool(request.response_schema) and bool(
            self.get_model_info(request.model).get("supports_structured_output")
        )
        return _request.transform_request(
            request,
            native=native,
            messages_fn=self._transform_messages,
            capabilities_fn=self._transform_capabilities,
        )

    def _transform_response(self, response: Any) -> CompleteResponse:
        """A Converse response as a ``CompleteResponse`` (see ``response.transform_response``)."""
        return _response.transform_response(response, extract_calls=self._extract_capability_calls)

    def _transform_stream_chunk(self, chunk: Any) -> StreamChunk:
        """A Converse stream event as a ``StreamChunk`` (see ``response.transform_stream_chunk``)."""
        return _response.transform_stream_chunk(chunk)

    def _call_provider(self, request: dict[str, Any]) -> Any:
        """POST the Converse API; returns a JsonObject."""
        url, body = self._url(request, "converse")
        return rest.post_json(
            url,
            body,
            authenticator=self._authenticator(),
            provider="bedrock",
            timeout=float(self.config.get("timeout", 60.0)),
        )

    def _call_provider_stream(self, request: dict[str, Any]) -> Iterator[Any]:
        """POST ConverseStream and yield decoded eventstream events."""
        url, body = self._url(request, "converse-stream")
        yield from post_eventstream_json(
            url,
            body,
            authenticator=self._authenticator(),
            provider="bedrock",
            timeout=float(self.config.get("timeout", 60.0)),
        )

    def format_capability_results(self, results: list[Any]) -> list[dict[str, Any]]:
        """Capability results in the Converse ``toolResult`` format (see ``capabilities.format_capability_results``)."""
        return _capabilities.format_capability_results(results)

    def refuses_forced_choice(self, model: str) -> bool:
        """The Claude models that refuse a forced ``tool_choice`` refuse ``toolChoice`` ``any`` and ``tool`` on Bedrock as well (D109):
        their profile entry says ``supports_forced_capability_choice`` is false."""
        return self.get_model_info(model).get("supports_forced_capability_choice") is False

    def get_model_info(self, model: str | None = None) -> dict[str, Any]:
        """Return model metadata and capabilities, with the ``info`` of the model's entry in the Bedrock profile merged in.

        Args:
            model: The model to describe; the default model of the client when omitted. A cross-Region prefix (``us.``) is ignored.

        Returns:
            Dictionary with provider information and capabilities
        """
        return {
            "provider": self.provider_name,
            "supports_streaming": True,
            "supports_function_calling": True,
            "supports_structured_output": False,  # False: a forced answer tool; a model that takes a native schema says True in its profile
            "supports_multimodal": True,
            **self._profile_info(
                self.provider_name, _base_model_id(model if model is not None else self.model)
            ),
        }
