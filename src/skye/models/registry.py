# Requirement 56.7
"""Provider registry for model and embedding providers.

This module provides a central registry for discovering and instantiating
model and embedding providers. Providers can be registered by name and
retrieved with configuration. It keeps no table of its own: it is a view of the
default registrar (``skye.base.plugins``), where the built-in
providers are registered by ``skye.models.plugins`` and a third-party plugin
registers its own with ``registrar.provider`` (``function="model"`` or ``"embedding"``).

Example:
    >>> from skye.models.registry import ProviderRegistry
    >>> from skye.models.plugins.openai.provider import OpenAIProvider
    >>>
    >>> # Register a provider
    >>> ProviderRegistry.register_model_provider("openai", OpenAIProvider)
    >>>
    >>> # Get a provider instance
    >>> provider = ProviderRegistry.get_model_provider("openai", api_key="sk-...")
    >>>
    >>> # List available providers
    >>> providers = ProviderRegistry.list_model_providers()
"""

import inspect
from typing import Any, Literal, Type, overload

from skye.base.api_keys import api_key_from_environment, api_key_variables
from skye.base.exceptions import ConfigurationError
from skye.base.interfaces.decision import DecisionModel
from skye.base.interfaces.model import ModelInterface
from skye.base.interfaces.registry import ProviderRegistryInterface, set_provider_registry
from skye.base.interfaces.vector_encoder import VectorEncoderInterface
from skye.base.plugins import ProviderFunction, Registrar, get_registrar

_KIND = "provider"
_MODEL: ProviderFunction = "model"
_EMBEDDING: ProviderFunction = "embedding"
_DECISION: ProviderFunction = "decision"


# Requirement 56.7
def _registrar() -> Registrar:
    """The default registrar, with the built-in providers in it: this module keeps no table of its own."""
    return get_registrar()


#: The ``provider_name`` of the two wire-format classes: a plugin registered on one of them is named by its registered name.
_GENERIC_NAMES = frozenset({"openai_compatible", "anthropic_compatible"})


# task 6.3
def _with_profile_key(name: str, provider_class: Any, config: dict[str, Any]) -> dict[str, Any]:
    """The key of a provider of the OpenAI or Anthropic format that is registered under its own name.

    A plugin registers ``OpenAICompatibleProvider`` or ``AnthropicCompatibleProvider`` under ``name`` with a profile that names the variables
    of its key. The class does not know that name, so the registry reads the first variable that is set and gives the key to the class. A class
    that has a profile of its own (``openai``, ``anthropic``) reads it itself, and a key that is passed is never replaced.

    Raises:
        ConfigurationError: The profile of ``name`` names variables and none is set (the message names them).
    """
    if config.get("api_key"):
        return config
    from skye.models.utilities.anthropic_compatible.provider import AnthropicCompatibleProvider
    from skye.models.utilities.openai_compatible.provider import OpenAICompatibleProvider

    if not (
        isinstance(provider_class, type)
        and issubclass(provider_class, (OpenAICompatibleProvider, AnthropicCompatibleProvider))
    ):
        return config
    if api_key_variables(provider_class.provider_name):
        return config
    variables = api_key_variables(name)
    if not variables:
        return config
    key = api_key_from_environment(name)
    if key is None:
        raise ConfigurationError(
            f"No API key: pass api_key or set {' or '.join(variables)}", details={"variable": variables[0]}
        )
    return {**config, "api_key": key}


def _with_profile_endpoint(name: str, provider_class: Any, config: dict[str, Any]) -> dict[str, Any]:
    """The ``default_api_base`` of the profile of ``name`` for a class of the OpenAI or Anthropic format that has no endpoint of its own.

    An endpoint that is passed, or one the class sets itself (``openai``, ``anthropic``), is never replaced.
    """
    from skye.models.utilities.anthropic_compatible.provider import AnthropicCompatibleProvider
    from skye.models.utilities.openai_compatible.provider import OpenAICompatibleProvider

    if config.get("api_base") or not (
        isinstance(provider_class, type)
        and issubclass(provider_class, (OpenAICompatibleProvider, AnthropicCompatibleProvider))
        and not provider_class.default_api_base
    ):
        return config
    profile = _registrar().get_profile(name)
    base = getattr(profile, "default_api_base", None)
    return {**config, "api_base": base} if base else config


class ProviderRegistry(ProviderRegistryInterface):
    """Registry for model and embedding providers.

    This class provides a central registry for discovering and instantiating
    model and embedding providers. Providers are registered by name and can
    be retrieved with configuration parameters.

    The registry is a view of the default registrar: the kind ``provider``, with the function ``model`` (LLMs)
    or ``embedding`` (vector encoders).

    Example:
        >>> # Register providers
        >>> ProviderRegistry.register_model_provider("openai", OpenAIProvider)
        >>> ProviderRegistry.register_embedding_provider("openai", OpenAIEmbeddingProvider)
        >>>
        >>> # Get provider instances
        >>> model = ProviderRegistry.get_model_provider("openai", api_key="sk-...")
        >>> embedder = ProviderRegistry.get_embedding_provider("openai", model="text-embedding-3-small")
        >>>
        >>> # List available providers
        >>> print(ProviderRegistry.list_model_providers())
        ['anthropic', 'azure', 'bedrock', 'google', 'openai']
    """

    @classmethod
    def register_model_provider(
        cls, name: str, provider_class: Type[ModelInterface]
    ) -> None:
        """Register a model provider.

        Args:
            name: The name to register the provider under (e.g., "openai", "bedrock").
            provider_class: The provider class that implements ModelInterface.

        Example:
            >>> from skye.models.plugins.openai.provider import OpenAIProvider
            >>> ProviderRegistry.register_model_provider("openai", OpenAIProvider)
        """
        _registrar().provider(name, provider_class, function=_MODEL, replace=True)

    @classmethod
    def register_embedding_provider(
        cls, name: str, provider_class: Type[VectorEncoderInterface]
    ) -> None:
        """Register an embedding provider.

        Args:
            name: The name to register the provider under (e.g., "openai", "cohere").
            provider_class: The provider class that implements VectorEncoderInterface.

        Example:
            >>> from skye.models.plugins.openai.embeddings import OpenAIEmbeddingProvider
            >>> ProviderRegistry.register_embedding_provider("openai", OpenAIEmbeddingProvider)
        """
        _registrar().provider(name, provider_class, function=_EMBEDDING, replace=True)

    @classmethod
    def get_model_provider(cls, name: str, **config: Any) -> ModelInterface:
        """Instantiate a model provider by name.

        Args:
            name: The name of the provider to instantiate.
            **config: Configuration parameters to pass to the provider constructor.

        Returns:
            An instance of the requested model provider.

        Raises:
            ConfigurationError: If the provider is not found or not installed.

        Example:
            >>> provider = ProviderRegistry.get_model_provider(
            ...     "openai",
            ...     api_key="sk-...",
            ...     api_base="https://api.openai.com/v1"
            ... )
            >>> response = provider.complete(request)
        """
        registrar = _registrar()
        if not registrar.has(_KIND, name, _MODEL):
            available = ", ".join(registrar.names(_KIND, _MODEL)) or "none"
            hint = ""
            if registrar.has(_KIND, name, _EMBEDDING):
                hint = f" '{name}' is an embedding provider: pass provider_type=\"embedding\"."
            elif registrar.has(_KIND, name, _DECISION):
                hint = f" '{name}' is a decision provider: pass provider_type=\"decision\"."
            raise ConfigurationError(
                f"Model provider '{name}' not found. Available model providers: {available}.{hint}"
            )

        provider_class: Type[ModelInterface] = registrar.get(_KIND, name, _MODEL)
        config = _with_profile_endpoint(name, provider_class, _with_profile_key(name, provider_class, config))
        try:
            provider = provider_class(**config)
            if getattr(provider, "provider_name", None) in _GENERIC_NAMES and _registrar().get_profile(name) is not None:
                setattr(provider, "provider_name", name)  # so its profile (``info``, prices, tokenizer) is found by name
            return provider
        except ConfigurationError:
            raise  # it already says what is missing (a key, a region) and names the variable
        except Exception as e:
            raise ConfigurationError(
                f"Failed to instantiate provider '{name}': {str(e)}"
            ) from e

    @classmethod
    def get_embedding_provider(
        cls, name: str, **config: Any
    ) -> VectorEncoderInterface:
        """Instantiate an embedding provider by name.

        Args:
            name: The name of the provider to instantiate.
            **config: Configuration parameters to pass to the provider constructor.

        Returns:
            An instance of the requested embedding provider.

        Raises:
            ConfigurationError: If the provider is not found or not installed.

        Example:
            >>> embedder = ProviderRegistry.get_embedding_provider(
            ...     "openai",
            ...     model="text-embedding-3-small",
            ...     api_key="sk-..."
            ... )
            >>> vectors = embedder.encode_batch(["text1", "text2"])
        """
        registrar = _registrar()
        if not registrar.has(_KIND, name, _EMBEDDING):
            available = ", ".join(registrar.names(_KIND, _EMBEDDING)) or "none"
            raise ConfigurationError(
                f"Embedding provider '{name}' not found. Available embedding providers: {available}."
            )

        provider_class: Type[VectorEncoderInterface] = registrar.get(_KIND, name, _EMBEDDING)
        try:
            return provider_class(**config)
        except ConfigurationError:
            raise  # it already says what is missing (a key, a region) and names the variable
        except Exception as e:
            raise ConfigurationError(
                f"Failed to instantiate embedding provider '{name}': {str(e)}"
            ) from e

    @classmethod
    def list_model_providers(cls) -> list[str]:
        """List all registered model providers.

        Returns:
            The registered model provider names, sorted (built-in ones and those a plugin registered).

        Example:
            >>> providers = ProviderRegistry.list_model_providers()
            >>> print(providers)
            ['anthropic', 'azure', 'bedrock', 'google', 'openai']
        """
        return _registrar().names(_KIND, _MODEL)

    @classmethod
    def list_embedding_providers(cls) -> list[str]:
        """List all registered embedding providers.

        Returns:
            The registered embedding provider names, sorted.

        Example:
            >>> providers = ProviderRegistry.list_embedding_providers()
            >>> print(providers)
            ['bedrock', 'cohere', 'google', 'google-multimodal', 'openai']
        """
        return _registrar().names(_KIND, _EMBEDDING)


set_provider_registry(ProviderRegistry)


@overload
def provider(name: str, *, provider_type: Literal["embedding"], **config: Any) -> VectorEncoderInterface: ...


@overload
def provider(name: str, *, provider_type: Literal["decision"], **config: Any) -> DecisionModel: ...


@overload
def provider(name: str, *, provider_type: Literal["model"] = ..., **config: Any) -> ModelInterface: ...


def provider(name: str, **config: Any) -> ModelInterface | VectorEncoderInterface | DecisionModel:
    """Create a provider client (boto3-style API).

    This is the main entry point for the simplified boto3-style API.
    Returns a provider instance that supports direct method calls.

    Args:
        name: Provider name (e.g., "openai", "bedrock", "anthropic", "cohere", "jev").
        **config: Provider-specific configuration. Use provider_type="embedding"
            to get an embedding provider instead of a model provider, or provider_type="decision"
            for a decision model (built as ``create_decision_model(name, **config)`` does); a name
            that has only an embedding provider (``cohere``) or only a decision provider (``jev``)
            gives it without ``provider_type``. ``region`` is an
            alias of the AWS ``region_name`` and of the Google ``location``; ``location`` stays
            ``location`` for Google. ``max_retries`` (0 turns retries off) goes to the client.

    Returns:
        ModelInterface or VectorEncoderInterface instance that supports boto3-style calls.

    Example:
        >>> from skye.base.messages import UserMessage
        >>>
        >>> # OpenAI LLM
        >>> client = provider("openai", api_key="sk-...")
        >>> response = client.complete(
        ...     messages=[UserMessage(content="Hello")],
        ...     model="gpt-4"
        ... )
        >>>
        >>> # OpenAI Embeddings
        >>> embedder = provider(
        ...     "openai",
        ...     api_key="sk-...",
        ...     model="text-embedding-3-small",
        ...     provider_type="embedding"
        ... )
        >>> vectors = embedder.encode_batch(["text1", "text2"])
        >>>
        >>> # Bedrock LLM
        >>> client = provider("bedrock", region="us-east-1")
        >>> response = client.complete(
        ...     messages=[UserMessage(content="Hello")],
        ...     model="anthropic.claude-3-sonnet-20240229-v1:0"
        ... )
        >>>
        >>> # Bedrock Embeddings
        >>> embedder = provider(
        ...     "bedrock",
        ...     region="us-east-1",
        ...     model="amazon.titan-embed-text-v1",
        ...     provider_type="embedding"
        ... )
        >>> vectors = embedder.encode_batch(["text1", "text2"])
        >>>
        >>> # Google Embeddings
        >>> embedder = provider(
        ...     "google",
        ...     project_id="my-project",
        ...     location="us-central1",
        ...     model="textembedding-gecko@003",
        ...     provider_type="embedding"
        ... )
        >>> vectors = embedder.encode_batch(["text1", "text2"])
    """
    registrar = _registrar()
    provider_type = config.pop("provider_type", None)
    if provider_type is None:
        # A name registered for one function only gives that one: ``cohere`` its embedding client, ``jev`` its decision model.
        provider_type = "model"
        if not registrar.has(_KIND, name, _MODEL):
            for other in (_EMBEDDING, _DECISION):
                if registrar.has(_KIND, name, other):
                    provider_type = other
                    break

    if provider_type == "decision":
        from skye.models.decision import create_decision_model

        return create_decision_model(name, **config)

    kind: ProviderFunction = _EMBEDDING if provider_type == "embedding" else _MODEL
    if registrar.has(_KIND, name, kind):
        _normalize_location(registrar.get(_KIND, name, kind), config)

    if provider_type == "embedding":
        return ProviderRegistry.get_embedding_provider(name, **config)
    return ProviderRegistry.get_model_provider(name, **config)


def _parameters(cls: type) -> set[str]:
    try:
        return set(inspect.signature(cls).parameters)
    except (TypeError, ValueError):
        return set()


def _normalize_location(cls: type, config: dict[str, Any]) -> None:
    """Let ``region`` and ``location`` name the parameter the class takes.

    An AWS client takes ``region_name`` (``region`` and ``location`` are aliases of it); a Google
    client takes ``location`` (``region`` is an alias of it), which is never renamed.
    """
    accepted = _parameters(cls)
    if "location" in accepted:
        if "region" in config and "location" not in config:
            config["location"] = config.pop("region")
        if "region_name" in config and "location" not in config:
            config["location"] = config.pop("region_name")
    elif "region_name" in accepted:
        for alias in ("region", "location"):
            if alias in config and "region_name" not in config:
                config["region_name"] = config.pop(alias)
