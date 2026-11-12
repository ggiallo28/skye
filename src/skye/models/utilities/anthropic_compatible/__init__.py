"""The Anthropic Messages wire format, for any endpoint that speaks it (a shared base of ``models``, D110).

``AnthropicCompatibleProvider`` serves every endpoint that implements ``POST /v1/messages``,
keyed by ``api_base`` + ``api_key``. What belongs to Anthropic itself lives in ``plugins/anthropic``.

The package is split by responsibility, with the same file names as a provider folder: ``provider.py`` (the class), ``request.py`` (building the
request), ``response.py`` (reading a response and a stream event) and ``capabilities.py`` (tools out, tool calls back, results formatted).

Features:
- Standard-library REST adapter (no vendor SDK), POST /v1/messages
- Separate system message handling
- Tool use (Anthropic's function calling)
- Thinking/reasoning features
- Streaming support
- Async support via run_in_executor

Example:
    >>> from skye.models.utilities.anthropic_compatible import AnthropicCompatibleProvider
    >>> from skye.base.completion import CompleteRequest
    >>> from skye.base.messages import UserMessage
    >>>
    >>> provider = AnthropicCompatibleProvider(api_key="...", api_base="http://localhost:8000")
    >>> request = CompleteRequest(
    ...     messages=[UserMessage(content="Hello")],
    ...     model="claude-3-opus-20240229"
    ... )
    >>> response = provider.complete(request)
    >>> print(response.content)
"""

from skye.models.utilities.anthropic_compatible.provider import (
    ANTHROPIC_VERSION,
    AnthropicCompatibleProvider,
)

__all__ = [
    "ANTHROPIC_VERSION",
    "AnthropicCompatibleProvider",
]
