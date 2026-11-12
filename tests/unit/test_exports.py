"""Tests for package exports."""

import skye


def test_version_export():
    """Test that __version__ is exported."""
    assert hasattr(skye, "__version__")
    assert isinstance(skye.__version__, str)


def test_all_defined():
    """Test that __all__ is properly defined."""
    assert hasattr(skye, "__all__")
    assert isinstance(skye.__all__, list)
    assert len(skye.__all__) > 0


def test_provider_is_exported_and_loads_the_registry_only_when_called():
    """`skye.provider(name, **config)` is the boto3-style way to create a client; `import skye` must not import `skye.models`."""
    import subprocess
    import sys

    assert "provider" in skye.__all__
    code = (
        "import sys, skye; assert 'skye.models' not in sys.modules; "
        "c = skye.provider('openai', api_key='k'); assert hasattr(c, 'complete') and hasattr(c, 'stream'); "
        "e = skye.provider('openai', model='text-embedding-3-small', api_key='k', provider_type='embedding'); "
        "assert hasattr(e, 'encode_batch'); assert 'skye.models' in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_exception_exports():
    """Test that all exceptions are importable from skye.base.exceptions."""
    from skye.base.exceptions import (
        AuthenticationError,
        BadRequestError,
        CapabilityExecutionError,
        ConfigurationError,
        ContentPolicyError,
        ProviderError,
        ProviderTimeoutError,
        RateLimitError,
        ServerError,
        SkyeError,
        ValidationError,
    )

    # Verify they are exception classes
    assert issubclass(SkyeError, Exception)
    assert issubclass(ProviderError, SkyeError)
    assert issubclass(ConfigurationError, SkyeError)
    assert issubclass(ValidationError, SkyeError)
    assert issubclass(CapabilityExecutionError, SkyeError)
    for cls in (RateLimitError, ServerError, ProviderTimeoutError, AuthenticationError, BadRequestError):
        assert issubclass(cls, ProviderError)
    assert issubclass(ContentPolicyError, BadRequestError)


def test_message_exports():
    """Test that all message types are importable from skye.base.messages."""
    from skye.base.messages import (
        AssistantMessage,
        CapabilityMessage,
        ContentChunk,
        SkyeMessage,
        SystemMessage,
        UserMessage,
    )

    # Verify they are classes
    assert isinstance(SkyeMessage, type)
    assert isinstance(UserMessage, type)
    assert isinstance(AssistantMessage, type)
    assert isinstance(SystemMessage, type)
    assert isinstance(CapabilityMessage, type)
    assert isinstance(ContentChunk, type)


def test_completion_exports():
    """Test that completion models are importable from skye.base.completion."""
    from skye.base.completion import (
        CompleteRequest,
        CompleteResponse,
        StreamChunk,
        TokenUsage,
    )

    # Verify they are classes
    assert isinstance(TokenUsage, type)
    assert isinstance(CompleteRequest, type)
    assert isinstance(CompleteResponse, type)
    assert isinstance(StreamChunk, type)


def test_config_exports():
    """Test that configuration models and loader are importable from skye.base.config."""
    from skye.base.config import (
        ConfigLoader,
        CooldownConfig,
        ModelConfig,
        RateLimitConfig,
        RetryConfig,
        SkyeConfig,
    )

    # Verify they are classes
    assert isinstance(RateLimitConfig, type)
    assert isinstance(RetryConfig, type)
    assert isinstance(CooldownConfig, type)
    assert isinstance(ModelConfig, type)
    assert isinstance(SkyeConfig, type)
    assert isinstance(ConfigLoader, type)


def test_interface_exports():
    """Test that all interfaces are importable from skye.base.interfaces."""
    from skye.base.interfaces import (
        CapabilityInterface,
        CapabilitySchema,
        ContentReaderInterface,
        EventHandlerInterface,
        EventType,
        MemoryInterface,
        ModelInterface,
        ModelRouterInterface,
        ObserverInterface,
        PromptBuilderInterface,
        RoutingStrategy,
        SafetyFilterInterface,
        SafetyResult,
        VectorEncoderInterface,
    )

    # Verify they are classes or types
    assert isinstance(ModelInterface, type)
    assert isinstance(PromptBuilderInterface, type)
    assert isinstance(CapabilityInterface, type)
    assert isinstance(CapabilitySchema, type)
    assert isinstance(MemoryInterface, type)
    assert isinstance(SafetyFilterInterface, type)
    assert isinstance(SafetyResult, type)
    assert isinstance(ObserverInterface, type)
    assert isinstance(EventType, type)
    assert isinstance(EventHandlerInterface, type)
    assert isinstance(VectorEncoderInterface, type)
    assert isinstance(ContentReaderInterface, type)
    assert isinstance(ModelRouterInterface, type)
    assert isinstance(RoutingStrategy, type)


CURATED = ["messages", "completion", "exceptions", "config"]
# The builders: the word that adds a kind is the word that builds it (task 16.1, Requirement 56.11).
BUILDERS = [
    "provider", "agent", "backend", "mcp_client", "credential_source", "routing_strategy", "toolkit",
]
# The commonest names, loaded lazily on first access (decision D34).
LAZY_NAMES = {
    "UserMessage", "SystemMessage", "AssistantMessage", "CapabilityMessage", "CompleteRequest", "CompleteResponse",
    "StreamChunk", "TokenUsage", "SkyeError", "ProviderError", "ConfigurationError", "ValidationError", "MissingExtraError",
    # The provider errors chosen by the response (decision D104).
    "RateLimitError", "ServerError", "ProviderTimeoutError", "AuthenticationError", "BadRequestError", "ContentPolicyError",
    # The `.skye` loading API (decision D61): `skye.load(path)` and `skye.Flow` (task 8.4 of the uxui spec).
    "load", "Flow",
    # The configuration file is read in `skye.utils` (decision D91): `skye.load_config(path)`.
    "load_config",
    # The object that adds an integration (task 14.3 of the plugins spec, decision D111): `skye.Plugins()`.
    "Plugins",
    # The base class of a toolkit (task 18.4, decision D111): `class JiraToolkit(skye.Toolkit)`.
    "Toolkit",
}


def test_all_exports_in_all_list():
    """__all__ is the version, the four curated modules, the builders and the lazy common names (Requirement 7.8, decisions D28 and D34)."""
    from skye import __all__

    head = 1 + len(CURATED) + len(BUILDERS)
    assert __all__[:head] == ["__version__", *CURATED, *BUILDERS]
    assert set(__all__[head:]) == LAZY_NAMES


def test_curated_top_level_modules():
    """The four curated re-exports are the base modules."""
    import types

    import skye

    for name in CURATED:
        assert isinstance(getattr(skye, name), types.ModuleType), name


def test_combined_import():
    """Multiple symbols can be imported together from their Component paths."""
    from skye.base.config import ConfigLoader
    from skye.base.exceptions import SkyeError
    from skye.base.interfaces import ModelInterface
    from skye.base.messages import UserMessage

    assert ModelInterface is not None
    assert UserMessage is not None
    assert SkyeError is not None
    assert ConfigLoader is not None


def test_removed_names_not_reexported():
    """Names re-exported before task 10.1 are no longer on the top-level package (`provider` came back as a lazy function, D28)."""
    import skye

    for name in ["ModelRouter", "ConfigLoader", "ModelInterface", "MemoryInterface"]:
        assert not hasattr(skye, name), name


def test_all_exports_exist():
    """Every item in __all__ exists."""
    import skye

    for export_name in skye.__all__:
        assert getattr(skye, export_name) is not None, export_name
