"""Skye - a serverless-first Python library for GenAI applications.

The core is the standard library: every model provider is a built-in REST adapter, and an optional
extra adds only a third-party library that one feature needs (exact token counts, a store driver,
the MCP SDK). The top level re-exports only the commonest names (messages, completion, errors) and
the builders (``provider``, ``agent``, ``backend``, ``mcp_client``, ``credential_source``, ``routing_strategy``); the modules ``skye.messages``, ``skye.completion``, ``skye.exceptions``,
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
    from skye.base.interfaces.decision import DecisionModel
    from skye.base.interfaces.model import ModelInterface
    from skye.base.interfaces.runnable import Runnable
    from skye.base.interfaces.storage import StorageBackend
    from skye.base.interfaces.vector_encoder import VectorEncoderInterface
    from skye.base.messages import AssistantMessage, CapabilityMessage, SystemMessage, UserMessage
    from skye.base.plugins import Plugins
    from skye.flows import Flow
    from skye.tools.mcp_client import MCPClientInterface
    from skye.tools.toolkit import Toolkit
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
    # The object that adds an integration: ``plugins = skye.Plugins()`` (Requirement 56.1, decision D111).
    "Plugins": "skye.base.plugins",
    # The base class of a toolkit: ``class JiraToolkit(skye.Toolkit)`` (task 18.4, decision D111).
    "Toolkit": "skye.tools.toolkit",
}

# The builders: the word that adds a kind (``plugins.agent``) is the word that builds it (``skye.agent``), Requirement 56.11.
_BUILDERS = [
    "provider",
    "agent",
    "backend",
    "mcp_client",
    "credential_source",
    "routing_strategy",
    "toolkit",
]

__all__ = ["__version__", "messages", "completion", "exceptions", "config", *_BUILDERS, *_LAZY]


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
    name: str, *, provider_type: Literal["decision"], **config: Any
) -> "DecisionModel": ...


@overload
def provider(
    name: str, *, provider_type: Literal["model"] = ..., **config: Any
) -> "ModelInterface": ...


def provider(name: str, **config: Any) -> "ModelInterface | VectorEncoderInterface | DecisionModel":
    """Create the client of a provider with one call, in the style of ``boto3.client``.

    ``name`` is the provider (``"openai"``, ``"anthropic"``, ``"bedrock"``, ``"azure"``, ``"google"``, ``"cohere"``, ``"jev"``); the rest is
    its configuration. It builds a language model client; pass ``provider_type="embedding"`` for an embedding client or
    ``provider_type="decision"`` for a decision model. A name that has one function only (``cohere`` has embeddings, ``jev`` decides) gives
    that one. The registry is imported only when this function is called, so ``import skye`` stays light.

    Example:
        >>> import skye
        >>> client = skye.provider("openai", api_key="sk-...")
        >>> embedder = skye.provider("openai", model="text-embedding-3-small", provider_type="embedding")
        >>> decider = skye.provider("jev", endpoint="http://localhost:8080/decide", provider_type="decision")
    """
    from skye.models.registry import provider as _provider

    client: ModelInterface | VectorEncoderInterface | DecisionModel = _provider(name, **config)
    return client


def agent(name: str, **options: Any) -> "Runnable[Any, Any]":
    """Build the agent registered under ``name``, with ``options`` as keyword arguments.

    The word that adds an agent, ``plugins.agent("name")``, is the word that builds it. The built-in is ``skye.agents.REACT``. The
    name is required. This is ``skye.agents.create_agent``; ``skye.agents`` is imported only when this function is called.

    Raises:
        ConfigurationError: No agent has that name (the error lists the registered names).

    Example:
        >>> import skye
        >>> from skye.agents import REACT
        >>> agent = skye.agent(REACT, model="gpt-4o-mini")
    """
    from skye.agents.registry import create_agent

    return create_agent(name, **options)


def backend(name: str, **config: Any) -> "StorageBackend":
    """Build the storage backend registered under ``name``, with ``config`` as keyword arguments.

    The word that adds a backend, ``plugins.backend("name")``, is the word that builds it. The built-in names are ``memory``, ``file``,
    ``dynamodb``, ``redis``, ``valkey``, ``postgres`` and ``durable_function``. This is ``skye.store.backend``; ``skye.store`` is
    imported only when this function is called.

    Raises:
        ConfigurationError: No backend has that name (the error lists the registered names).

    Example:
        >>> import skye
        >>> store = skye.backend("memory")
    """
    from skye.store.factory import backend as _backend

    return _backend(name, **config)


def mcp_client(
    target: Any,
    impl: str = "skyemcp",
    *,
    headers: "dict[str, str] | None" = None,
    timeout: float = 30.0,
) -> "MCPClientInterface":
    """Build the MCP client of the implementation ``impl`` for ``target`` (an HTTP URL).

    The word that adds an implementation, ``plugins.mcp_client("name")``, is the word that builds it. The built-ins are ``"skyemcp"``
    (the default, standard library) and ``"fastmcp"``. This is ``skye.tools.create_mcp_client``; ``skye.tools`` is imported only when
    this function is called.

    Raises:
        ConfigurationError: No implementation has that name (the error lists the registered names).
        MissingExtraError: ``impl="fastmcp"`` and the extra ``mcp`` is not installed.

    Example:
        >>> import skye
        >>> client = skye.mcp_client("http://localhost:8000/mcp")  # doctest: +SKIP
    """
    from skye.tools.mcp_client import create_mcp_client

    return create_mcp_client(target, impl, headers=headers, timeout=timeout)


def credential_source(name: str, **config: Any) -> Any:
    """Build the credential source registered under ``name``, with ``config`` as keyword arguments.

    The word that adds a source, ``plugins.credential_source("name")``, is the word that builds it. This is
    ``skye.auth.resolve_credential_source``; ``skye.auth`` is imported only when this function is called.

    Raises:
        ConfigurationError: No source has that name (the error lists the registered names).
    """
    from skye.auth.registry import resolve_credential_source

    return resolve_credential_source(name, **config)


def routing_strategy(name: str) -> Any:
    """Return the routing strategy registered under ``name``.

    The word that adds a strategy, ``plugins.routing_strategy("name")``, is the word that finds it. The result is what was registered: a
    plain function ``(models) -> str`` or a function marked with ``with_context`` for a plugin, and a ``RouterStrategy`` class for a
    built-in. It does not build a router; a router takes the name in ``strategy=``. The registrar is read only when this function is
    called.

    Raises:
        ConfigurationError: No strategy has that name (the error lists the registered names).

    Example:
        >>> import skye
        >>> strategy = skye.routing_strategy("round_robin")  # doctest: +SKIP
    """
    from skye.base.plugins import get_registrar

    return get_registrar().get("routing_strategy", name)


def toolkit(name: str, *, alias: str | None = None, **options: Any) -> "Toolkit":
    """Build the toolkit registered under ``name``, with ``options`` as keyword arguments.

    The word that adds a toolkit, ``plugins.toolkit("name")``, is the word that builds it. The registered target is a ``Toolkit`` class, or
    a function that returns a ``Toolkit`` or a ``ToolProvider`` such as a ``CapabilityRegistry``; the ``tools=`` of the registration join
    the toolkit. The name of each tool is the name of the toolkit and the name of the tool, ``jira.create_issue``. ``alias`` is the prefix
    to use instead of the name when you build one toolkit twice: ``skye.toolkit("jira", alias="jira-eu", base_url=...)`` gives
    ``jira-eu.create_issue``. Every other keyword goes to the class or the function. This is ``skye.tools.toolkit.build_toolkit``;
    ``skye.tools`` is imported only when this function is called.

    Args:
        name: The registered name of the toolkit.
        alias: The prefix of the tools when it is not the name; ``None`` keeps the name.
        **options: Keyword arguments for the class or the function.

    Returns:
        A ``Toolkit``, to give to an agent in ``toolkits=[...]``.

    Raises:
        ConfigurationError: No toolkit has that name (the error lists the registered names), the target builds something that is neither a
            ``Toolkit`` nor a ``ToolProvider``, or two tools end with the same prefixed name.

    Example:
        >>> import skye
        >>> jira = skye.toolkit("jira", base_url="https://acme.example/jira")  # doctest: +SKIP
    """
    from skye.tools.toolkit import build_toolkit

    built = build_toolkit(name, **options)
    if alias is not None:
        built.alias = alias
    return built


# The public module paths of ``base`` (``skye.messages`` and the others); imported last so that they are attributes of ``skye``.
from skye import completion, config, exceptions, messages  # noqa: E402
