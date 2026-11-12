"""A component of a Port is validated when built and while it runs; plugins register and are found.

The registry Port (Requirement 16.2, 16.3).
"""

from typing import Any

import pytest

from skye.base.exceptions import ConfigurationError, ValidationError
from skye.base.interfaces.model import ModelInterface
from skye.base.interfaces.registry import ProviderRegistryInterface, get_provider_registry
from skye.models.registry import ProviderRegistry
from tests.unit.plugins.registrar_state import restored_default_registrar
from skye.utils.validation import port_signature_mismatches, validate_interface_compliance


class ModelPlugin(ModelInterface):
    """A provider plugin: it implements the model Port, enough to be registered."""

    def __init__(self, **config: Any) -> None:
        self.config = config

    def complete(self, request: Any) -> Any: ...
    def stream(self, request: Any) -> Any: ...
    async def acomplete(self, request: Any) -> Any: ...
    async def astream(self, request: Any) -> Any: ...
    def get_capabilities(self) -> dict[str, Any]:
        return {}

    def get_model_info(self) -> dict[str, Any]:
        return {}


class TestRegistryPort:
    def setup_method(self):
        self._restore = restored_default_registrar()
        self._restore.__enter__()

    def teardown_method(self):
        self._restore.__exit__(None, None, None)

    def test_the_default_registry_implements_the_registry_port(self):
        assert issubclass(ProviderRegistry, ProviderRegistryInterface)
        assert get_provider_registry() is ProviderRegistry

    def test_a_plugin_registers_and_is_found_by_name(self):
        registry = get_provider_registry()
        registry.register_model_provider("plugged", ModelPlugin)
        assert "plugged" in registry.list_model_providers()
        instance = registry.get_model_provider("plugged", api_key="k")
        assert isinstance(instance, ModelPlugin) and instance.config["api_key"] == "k"

    def test_an_incomplete_implementation_fails_when_the_registry_builds_it(self):
        class HalfModel(ModelInterface):
            def complete(self, request: Any) -> Any: ...

        registry = get_provider_registry()
        registry.register_model_provider("half", HalfModel)
        with pytest.raises(ConfigurationError):
            registry.get_model_provider("half")

    def test_an_unknown_name_is_a_configuration_error(self):
        with pytest.raises(ConfigurationError):
            get_provider_registry().get_model_provider("nobody-registered-this")
