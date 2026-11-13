# D104
"""Model and embedding providers for Skye.

This module provides concrete implementations of ModelInterface and VectorEncoderInterface
for various LLM and embedding providers. Providers are loaded lazily and only require
their dependencies when instantiated.

Supported LLM Providers:
- OpenAI (GPT-4, GPT-3.5, o1, o3)
- Anthropic (Claude 3.x)
- AWS Bedrock (Claude, Titan, Llama, etc.)
- Azure OpenAI
- Google (Gemini, PaLM)

Supported Embedding Providers:
- OpenAI (text-embedding-3-small/large, ada-002)
- AWS Bedrock Titan Embeddings
- Cohere Embeddings
- Google Text Embeddings
- Google Multimodal Embeddings

Example:
    >>> from skye.models import ProviderRegistry
    >>>
    >>> # Get a model provider
    >>> provider = ProviderRegistry.get_model_provider("openai", api_key="sk-...")
    >>> response = provider.complete(request)
    >>>
    >>> # Get an embedding provider
    >>> embedder = ProviderRegistry.get_embedding_provider("openai", model="text-embedding-3-small")
    >>> vectors = embedder.encode_batch(["text1", "text2"])

A custom provider that calls an HTTP service uses the same standard-library transport as the
built-in ones: ``post_json(url, payload, headers=..., authenticator=..., provider=...)`` returns
the decoded JSON as a ``JsonObject`` (attribute access), ``stream_sse_json`` yields one per
server-sent event. Both raise the ``ProviderError`` subclass of the response, which is
what the client's retries read.

Codename: zephyr.
"""

from skye.base.lazy_import import lazy_names as _lazy_names
from skye.models.base import BaseEmbeddingProvider, BaseModelProvider
from skye.models.decision import create_decision_model
from skye.models.lazy_import import LazyImporter
from skye.models.utilities.openai_compatible import OpenAICompatibleProvider
from skye.models.plugins.anthropic import AnthropicProvider
from skye.models.plugins.azure import AzureOpenAIProvider
from skye.models.plugins.bedrock import BedrockEmbeddingProvider, BedrockProvider
from skye.models.plugins.cohere import CohereEmbeddingProvider
from skye.models.plugins.google import (
    GoogleEmbeddingProvider,
    GoogleMultimodalEmbeddingProvider,
    GoogleProvider,
)
from skye.models.plugins.openai import OpenAIEmbeddingProvider, OpenAIProvider
from skye.models.plugins.typesafe import JevDecisionModel
from skye.models.registry import ProviderRegistry
from skye.models.cost import CostCalculator
from skye.models.utilities.multimodal import ImageHandler
from skye.models.token_counter import TokenCounter
from skye.models.utilities import rest as _rest

# The HTTP transport of the built-in adapters, public for custom providers
JsonObject = _rest.JsonObject
post_json = _rest.post_json
stream_sse_json = _rest.stream_sse_json

# The built-in providers are not registered here: ``skye.models.plugins`` registers them with the default registrar at its first lookup, and
# ``ProviderRegistry`` is a view of that registrar (Requirement 56.7).

# The offline check is read at first use, so importing the package does not import it.
_LAZY = {"check_provider": "conformance", "check_tokenizer": "conformance"}
__getattr__ = _lazy_names(__name__, _LAZY)

__all__ = [
    *_LAZY,
    "BaseModelProvider",
    "BaseEmbeddingProvider",
    "LazyImporter",
    "ProviderRegistry",
    "ImageHandler",
    "TokenCounter",
    "CostCalculator",
    "OpenAIProvider",
    "OpenAICompatibleProvider",
    "AnthropicProvider",
    "BedrockProvider",
    "AzureOpenAIProvider",
    "GoogleProvider",
    "JevDecisionModel",
    "create_decision_model",
    "OpenAIEmbeddingProvider",
    "BedrockEmbeddingProvider",
    "CohereEmbeddingProvider",
    "GoogleEmbeddingProvider",
    "GoogleMultimodalEmbeddingProvider",
    "JsonObject",
    "post_json",
    "stream_sse_json",
]
