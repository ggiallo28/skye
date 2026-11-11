"""Skye - a serverless-first Python library for GenAI applications.

The core is the standard library: every model provider is a built-in REST adapter, and an optional
extra adds only a third-party library that one feature needs (exact token counts, a store driver,
the MCP SDK). The top level re-exports only the commonest names (messages, completion, errors) and
``provider``; the modules ``skye.messages``, ``skye.completion``, ``skye.exceptions``,
``skye.config``, ``skye.data``, ``skye.interfaces`` and ``skye.dsl`` are the public paths of
``base``; import everything else from its component path (``skye.models``, ``skye.router``,
``skye.tools``, ...).

Installation:
    pip install skyeai                    # every provider (built-in REST adapters)
    pip install skyeai[tokens]            # + exact token counts
    pip install skyeai[redis]             # + Redis store backend
    pip install skyeai[all]               # every optional library but boto3 (in Lambda already)

Example:
    >>> import skye
    >>> from skye import UserMessage
    >>>
    >>> client = skye.provider("bedrock", region="us-east-1")
    >>> response = client.complete(  # doctest: +SKIP
    ...     messages=[UserMessage(content="Hello")],
    ...     model="anthropic.claude-3-sonnet-20240229-v1:0"
    ... )
    >>> print(response.content)  # doctest: +SKIP
"""

__version__ = "0.2.0"

from typing import TYPE_CHECKING, Any, Literal, overload

if TYPE_CHECKING:
    from skye.base.completion import CompleteRequest, CompleteResponse, StreamChunk, TokenUsage
    from skye.base.exceptions import (
        AuthenticationError,
        BadRequestError,
        ConfigurationError,
        ContentPolicyError,
        MissingExtraError,
        ProviderError,
        ProviderTimeoutError,
        RateLimitError,
        ServerError,
        SkyeError,
        ValidationError,
    )
    from skye.base.interfaces.model import ModelInterface
    from skye.base.interfaces.vector_encoder import VectorEncoderInterface
    from skye.base.messages import AssistantMessage, CapabilityMessage, SystemMessage, UserMessage
    from skye.flows import Flow
    from skye.utils.config_files import load_config
    from skye.utils.skye_files import load

# The commonest names, importable as ``from skye import UserMessage``; each is loaded on first use, so ``import skye`` stays light.
_LAZY = {
    "UserMessage": "skye.base.messages",
    "SystemMessage": "skye.base.messages",
    "AssistantMessage": "skye.base.messages",
    "CapabilityMessage": "skye.base.messages",
    "CompleteRequest": "skye.base.completion",
    "CompleteResponse": "skye.base.completion",
    "StreamChunk": "skye.base.completion",
    "TokenUsage": "skye.base.completion",
    "SkyeError": "skye.base.exceptions",
    "ProviderError": "skye.base.exceptions",
    "RateLimitError": "skye.base.exceptions",
    "ServerError": "skye.base.exceptions",
    "ProviderTimeoutError": "skye.base.exceptions",
    "AuthenticationError": "skye.base.exceptions",
    "BadRequestError": "skye.base.exceptions",
    "ContentPolicyError": "skye.base.exceptions",
    "ConfigurationError": "skye.base.exceptions",
    "ValidationError": "skye.base.exceptions",
    "MissingExtraError": "skye.base.exceptions",
    "load": "skye.utils.skye_files",
    "load_config": "skye.utils.config_files",
    "Flow": "skye.flows",
}

__all__ = ["__version__", "messages", "completion", "exceptions", "config", "provider", *_LAZY]


def __getattr__(name: str) -> Any:
    """Load a commonly used name (``UserMessage``, ``SkyeError``, ...) on first access."""
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module 'skye' has no attribute {name!r}")
    import importlib

    value = getattr(importlib.import_module(module), name)
    globals()[name] = value
    return value


@overload
def provider(
    name: str, *, provider_type: Literal["embedding"], **config: Any
) -> "VectorEncoderInterface": ...


@overload
def provider(
    name: str, *, provider_type: Literal["model"] = ..., **config: Any
) -> "ModelInterface": ...


def provider(name: str, **config: Any) -> "ModelInterface | VectorEncoderInterface":
    """Create the client of a model provider with one call, in the style of ``boto3.client``.

    ``name`` is the provider (``"openai"``, ``"anthropic"``, ``"bedrock"``, ``"azure"``, ``"google"``, ``"cohere"``); the rest is its
    configuration. Pass ``provider_type="embedding"`` to get an embedding client instead of a language model client. The registry is
    imported only when this function is called, so ``import skye`` stays light.

    Example:
        >>> import skye
        >>> client = skye.provider("openai", api_key="sk-...")
        >>> embedder = skye.provider("openai", model="text-embedding-3-small", provider_type="embedding")
    """
    from skye.models.registry import provider as _provider

    client: ModelInterface | VectorEncoderInterface = _provider(name, **config)
    return client


# The public module paths of ``base`` (``skye.messages`` and the others); imported last so that they are attributes of ``skye``.
from skye import completion, config, exceptions, messages  # noqa: E402
