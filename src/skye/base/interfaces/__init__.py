"""Core interface definitions for Skye.

This module provides all the abstract interfaces that define contracts for
Skye components. All implementations must adhere to these interfaces.
"""

from skye.base.interfaces.authentication import AuthenticationInterface
from skye.base.interfaces.authorizer import AuthorizerInterface, Decision
from skye.base.interfaces.capability import CapabilityInterface, CapabilitySchema
from skye.base.interfaces.config_loader import ConfigLoaderInterface
from skye.base.interfaces.content_reader import ContentReaderInterface
from skye.base.interfaces.cost_calculator import CostCalculatorInterface
from skye.base.interfaces.decision import DecisionModel, DecisionResult
from skye.base.interfaces.event_handler import EventHandlerInterface
from skye.base.interfaces.memory import MemoryInterface
from skye.base.interfaces.model import ModelInterface
from skye.base.interfaces.observer import EventType, ObserverInterface
from skye.base.interfaces.plugin import RegistrarInterface
from skye.base.interfaces.prompt import (
    OutputSchema,
    PromptBuilderInterface,
    PromptParts,
    PromptRegistryInterface,
    PromptRenderingInterface,
    PromptSchemaInterface,
)
from skye.base.interfaces.registry import (
    ProviderRegistryInterface,
)
from skye.base.interfaces.resource import Resource, ResourceProviderInterface
from skye.base.interfaces.router import (
    ModelHealthInterface,
    ModelRouterInterface,
    ModelSelectionInterface,
    RouterConfigurationInterface,
    RoutingStrategy,
)
from skye.base.interfaces.runnable import Runnable
from skye.base.interfaces.safety import SafetyFilterInterface, SafetyResult
from skye.base.interfaces.storage import (
    CounterStore,
    ExpiryStore,
    KeyValueStore,
    ScanStore,
    StorageBackend,
)
from skye.base.interfaces.token_counter import TokenCounterInterface
from skye.base.interfaces.tool_provider import CapabilityContext, ToolProvider
from skye.base.interfaces.vector_encoder import VectorEncoderInterface

__all__ = [
    # Core model and provider interfaces
    "ModelInterface",
    "VectorEncoderInterface",
    "ModelRouterInterface",
    "ModelSelectionInterface",
    "ModelHealthInterface",
    "RouterConfigurationInterface",
    "ProviderRegistryInterface",
    "RoutingStrategy",
    # Prompt and message interfaces
    "PromptBuilderInterface",
    "PromptRenderingInterface",
    "PromptRegistryInterface",
    "PromptSchemaInterface",
    "PromptParts",
    "OutputSchema",
    # Composition and decision Ports
    "AuthorizerInterface",
    "Decision",
    "AuthenticationInterface",
    "Runnable",
    "DecisionModel",
    "DecisionResult",
    # Capability interfaces
    "CapabilityContext",
    "CapabilityInterface",
    "CapabilitySchema",
    "ToolProvider",
    # Memory and storage interfaces
    "MemoryInterface",
    "StorageBackend",
    "KeyValueStore",
    "CounterStore",
    "ExpiryStore",
    "ScanStore",
    # Safety and filtering interfaces
    "SafetyFilterInterface",
    "SafetyResult",
    # Observability interfaces
    "ObserverInterface",
    "EventType",
    "EventHandlerInterface",
    # Plugin and extension interfaces
    "RegistrarInterface",
    # Content handling interfaces
    "ContentReaderInterface",
    "Resource",
    "ResourceProviderInterface",
    # Utility interfaces
    "CostCalculatorInterface",
    "TokenCounterInterface",
    "ConfigLoaderInterface",
]
