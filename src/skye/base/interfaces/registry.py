# task 4.6, Requirement 10.1, decision D41
"""Registry Port: the provider registry contract.

Single home for the registry contract (Overlap A). The route registry Port was removed: the router keeps its aliases itself.
The provider registry discovers and instantiates providers. Consumers (e.g. the
router) reach the implementation in ``models`` only through this Port.

Raises: ConfigurationError for an unknown provider.
Missing: an unknown provider name raises ``ConfigurationError``.
Concurrency: registries are filled at start-up and read afterwards; reads are safe from many threads and tasks.
"""

import importlib
from abc import ABC, abstractmethod
from typing import Any

_provider_registry: Any = None


def set_provider_registry(registry: Any) -> None:
    """Install the provider registry used by consumers of the Port."""
    global _provider_registry
    _provider_registry = registry


def get_provider_registry() -> Any:
    """Return the installed provider registry (a ProviderRegistryInterface).

    Falls back to lazily loading the default implementation in ``models`` by
    dotted name, so ``base`` and consumers carry no static dependency on it.
    """
    if _provider_registry is None:
        mod = importlib.import_module("skye.models.registry")
        return mod.ProviderRegistry
    return _provider_registry


class ProviderRegistryInterface(ABC):
    """Abstract contract for registering and instantiating providers."""

    @classmethod
    @abstractmethod
    def register_model_provider(cls, name: str, provider_class: type) -> None:
        """Register a model provider class under ``name``."""

    @classmethod
    @abstractmethod
    def register_embedding_provider(cls, name: str, provider_class: type) -> None:
        """Register an embedding provider class under ``name``."""

    @classmethod
    @abstractmethod
    def get_model_provider(cls, name: str, **config: Any) -> Any:
        """Instantiate a model provider by name."""

    @classmethod
    @abstractmethod
    def get_embedding_provider(cls, name: str, **config: Any) -> Any:
        """Instantiate an embedding provider by name."""

    @classmethod
    @abstractmethod
    def list_model_providers(cls) -> list[str]:
        """List registered model provider names."""

    @classmethod
    @abstractmethod
    def list_embedding_providers(cls) -> list[str]:
        """List registered embedding provider names."""
