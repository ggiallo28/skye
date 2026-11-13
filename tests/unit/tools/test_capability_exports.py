"""Tests for capability package exports.

This module verifies that all expected symbols are properly exported from
the skye.tools package and that __all__ is correctly defined.
"""


def test_capability_interface_import():
    """Test that CapabilityInterface can be imported."""
    from skye.tools import CapabilityInterface

    assert CapabilityInterface is not None
    assert hasattr(CapabilityInterface, "get_schema")
    assert hasattr(CapabilityInterface, "execute")
    assert hasattr(CapabilityInterface, "aexecute")


def test_capability_schema_import():
    """Test that CapabilitySchema can be imported."""
    from skye.tools import CapabilitySchema

    assert CapabilitySchema is not None


def test_capability_registry_import():
    """Test that CapabilityRegistry can be imported."""
    from skye.tools import CapabilityRegistry

    assert CapabilityRegistry is not None
    assert hasattr(CapabilityRegistry, "register")
    assert hasattr(CapabilityRegistry, "get")
    assert hasattr(CapabilityRegistry, "list_all")
    assert hasattr(CapabilityRegistry, "unregister")


def test_local_function_capability_import():
    """Test that LocalFunctionCapability can be imported."""
    from skye.tools import LocalFunctionCapability

    assert LocalFunctionCapability is not None


def test_remote_api_capability_import():
    """Test that RemoteAPICapability can be imported."""
    from skye.tools import RemoteAPICapability

    assert RemoteAPICapability is not None


def test_capability_call_import():
    """Test that CapabilityCall can be imported."""
    from skye.tools import CapabilityCall

    assert CapabilityCall is not None


def test_capability_result_import():
    """Test that CapabilityResult can be imported."""
    from skye.tools import CapabilityResult

    assert CapabilityResult is not None


def test_exception_imports():
    """Test that all exception classes can be imported."""
    from skye.tools import (
        CapabilityCallParsingError,
        CapabilityError,
        CapabilityExecutionError,
        CapabilityNotFoundError,
        CapabilityValidationError,
    )

    assert CapabilityError is not None
    assert CapabilityExecutionError is not None
    assert CapabilityNotFoundError is not None
    assert CapabilityValidationError is not None
    assert CapabilityCallParsingError is not None

    # Verify inheritance
    assert issubclass(CapabilityExecutionError, CapabilityError)
    assert issubclass(CapabilityNotFoundError, CapabilityError)
    assert issubclass(CapabilityValidationError, CapabilityError)
    assert issubclass(CapabilityCallParsingError, CapabilityError)


def test_capability_transformer_import():
    """Test that CapabilityTransformer is no longer exported (removed in consolidation)."""
    import skye.tools

    # CapabilityTransformer has been removed as part of provider consolidation
    assert not hasattr(skye.tools, "CapabilityTransformer")


def test_capability_call_handler_import():
    """Test that CapabilityCallHandler can be imported."""
    from skye.tools import CapabilityCallHandler

    assert CapabilityCallHandler is not None
    assert hasattr(CapabilityCallHandler, "parse_capability_calls")
    assert hasattr(CapabilityCallHandler, "execute_capability_calls")
    assert hasattr(CapabilityCallHandler, "format_capability_results")


def test_mcp_client_import():
    """The tri-faceted MCP client and its factory can be imported; the legacy probes are gone (task 6.3)."""
    import skye.tools
    from skye.tools import SkyeMCPClient, MCPToolCapability, create_mcp_client

    assert (
        SkyeMCPClient is not None and MCPToolCapability is not None and callable(create_mcp_client)
    )
    assert not hasattr(skye.tools, "MCPCapability")
    assert not hasattr(skye.tools, "MCPServerClient")


def test_capability_decorator_import():
    """Test that capability decorator can be imported."""
    from skye.tools import capability

    assert capability is not None
    assert callable(capability)


def test_all_defined():
    """Test that __all__ is properly defined."""
    import skye.tools

    assert hasattr(skye.tools, "__all__")
    assert isinstance(skye.tools.__all__, list)
    assert len(skye.tools.__all__) > 0


def test_all_contains_expected_symbols():
    """Test that __all__ contains all expected symbols."""
    import skye.tools

    expected_symbols = [
        "CapabilityInterface",
        "CapabilitySchema",
        "CapabilityRegistry",
        "LocalFunctionCapability",
        "RemoteAPICapability",
        "CapabilityCall",
        "CapabilityResult",
        "CapabilityError",
        "CapabilityExecutionError",
        "CapabilityNotFoundError",
        "CapabilityValidationError",
        "CapabilityCallParsingError",
        "CapabilityCallHandler",
        "SkyeMCPClient",
        "MCPToolCapability",
        "create_mcp_client",
        "capability",
    ]

    for symbol in expected_symbols:
        assert symbol in skye.tools.__all__, f"{symbol} not in __all__"


def test_all_symbols_are_importable():
    """Test that all symbols in __all__ can be imported."""
    import skye.tools

    for symbol in skye.tools.__all__:
        assert hasattr(skye.tools, symbol), f"{symbol} not importable"


def test_star_import():
    """Test that star import works correctly."""
    # This test verifies that 'from skye.tools import *' works
    namespace = {}
    exec("from skye.tools import *", namespace)

    expected_symbols = [
        "CapabilityInterface",
        "CapabilitySchema",
        "CapabilityRegistry",
        "LocalFunctionCapability",
        "RemoteAPICapability",
        "CapabilityCall",
        "CapabilityResult",
        "CapabilityError",
        "CapabilityExecutionError",
        "CapabilityNotFoundError",
        "CapabilityValidationError",
        "CapabilityCallParsingError",
    ]

    for symbol in expected_symbols:
        assert symbol in namespace, f"{symbol} not available via star import"


def test_combined_import():
    """Test that multiple symbols can be imported together."""
    from skye.tools import (
        CapabilityCall,
        CapabilityInterface,
        CapabilityRegistry,
        CapabilityResult,
        CapabilitySchema,
        LocalFunctionCapability,
        RemoteAPICapability,
    )

    assert CapabilityInterface is not None
    assert CapabilityRegistry is not None
    assert CapabilitySchema is not None
    assert LocalFunctionCapability is not None
    assert RemoteAPICapability is not None
    assert CapabilityCall is not None
    assert CapabilityResult is not None


def test_no_private_symbols_in_all():
    """Test that __all__ doesn't contain private symbols."""
    import skye.tools

    for symbol in skye.tools.__all__:
        assert not symbol.startswith("_"), f"Private symbol {symbol} in __all__"


def test_package_docstring():
    """Test that the package has a docstring."""
    import skye.tools

    assert skye.tools.__doc__ is not None
    assert len(skye.tools.__doc__) > 0
    assert "capability" in skye.tools.__doc__.lower()
