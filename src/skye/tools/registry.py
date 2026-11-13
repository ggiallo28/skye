"""Capability registry for managing and discovering capabilities.

This module provides the CapabilityRegistry class for centralized management
of capabilities with support for namespacing, validation, semantic search,
and thread-safe operations.
"""

import logging
import threading
from difflib import SequenceMatcher
from typing import Any

from skye.base.capability_execution import arun_capability_call, format_capability_result
from skye.base.completion import CapabilityCall
from skye.base.interfaces.capability import CapabilityInterface, CapabilitySchema
from skye.base.interfaces.tool_provider import CapabilityContext
from skye.base.messages import CapabilityMessage
from skye.tools.exceptions import (
    CapabilityError,
    CapabilityExecutionError,
    CapabilityNotFoundError,
    CapabilityValidationError,
)

logger = logging.getLogger(__name__)


class CapabilityRegistry:
    """Centralized registry for managing capabilities.

    Provides a singleton registry for registering, retrieving, and managing
    capabilities across the application. Supports namespace-based organization
    (e.g., "weather.get_current", "database.query"), semantic search, and
    thread-safe operations.

    The registry validates capabilities on registration and provides methods
    for discovery, lifecycle management, and semantic search. Supports mixing
    different capability types (LocalFunctionCapability, RemoteAPICapability,
    MCPToolCapability, etc.) in the same registry.

    Features:
    - Singleton pattern for global registry access
    - Thread-safe operations with RLock
    - Namespace support for organizing capabilities
    - Semantic search by name and description
    - Execution of capabilities with automatic result wrapping
    - Support for both sync and async execution
    - Initialization with capability list and auto_search flag

    Example:
        >>> # Using singleton
        >>> registry = CapabilityRegistry.get_instance()
        >>> registry.register(my_capability)
        >>> capability = registry.get("my_tool")
        >>> all_names = registry.list_all()
        >>>
        >>> # Semantic search
        >>> results = registry.search("get weather")
        >>> for name, cap, score in results:
        ...     print(f"{name}: {score:.2f}")
        >>>
        >>> # Direct instantiation with capabilities
        >>> registry = CapabilityRegistry(
        ...     capabilities=[cap1, cap2],
        ...     auto_search=True
        ... )
        >>> result = registry.execute("my_tool", {"arg": "value"})
    """

    _instance: "CapabilityRegistry | None" = None
    _lock = threading.Lock()

    # Requirement 62.1
    def __init__(
        self,
        capabilities: list[CapabilityInterface] | None = None,
        auto_search: bool = True,
    ) -> None:
        """Initialize the capability registry.

        A new registry starts empty, or with the ``capabilities`` passed. It is no view of the registrar: what is registered
        on it, with ``register``, stays local to it and never reaches another registry. A set of tools that several agents share is a toolkit.

        Args:
            capabilities: Optional list of capabilities to register on initialization
            auto_search: Enable semantic search functionality (default: True)

        This should not be called directly. Use get_instance() instead.
        """
        self._capabilities: dict[str, CapabilityInterface] = {}
        self._registry_lock = threading.RLock()
        self._auto_search = auto_search

        # Register initial capabilities if provided
        if capabilities:
            for capability in capabilities:
                self.register(capability)

    @classmethod
    def get_instance(cls) -> "CapabilityRegistry":
        """Get the singleton instance of CapabilityRegistry.

        Uses double-checked locking pattern for thread-safe singleton creation.

        Returns:
            CapabilityRegistry: The singleton instance

        Example:
            >>> registry = CapabilityRegistry.get_instance()
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def register(self, capability: CapabilityInterface) -> None:
        """Register a capability in the registry.

        Validates the capability schema and checks for duplicates before
        registration. Raises an error if a capability with the same name
        is already registered.

        Args:
            capability: The capability to register

        Raises:
            CapabilityValidationError: If the capability schema is invalid
            CapabilityValidationError: If a capability with the same name
                is already registered

        Example:
            >>> registry = CapabilityRegistry.get_instance()
            >>> registry.register(my_capability)
        """
        with self._registry_lock:
            # Get and validate schema
            try:
                schema = capability.get_schema()
            except Exception as e:
                raise CapabilityValidationError(
                    f"Failed to get schema from capability: {e}",
                    capability_name="<unknown>",
                    original_error=str(e),
                ) from e

            # Validate schema
            if not isinstance(schema, CapabilitySchema):
                raise CapabilityValidationError(
                    f"Capability schema must be CapabilitySchema, got {type(schema).__name__}",
                    capability_name=schema.name if hasattr(schema, "name") else "<unknown>",
                )

            # Check for duplicates
            if schema.name in self._capabilities:
                raise CapabilityValidationError(
                    f"Capability '{schema.name}' is already registered",
                    capability_name=schema.name,
                    existing_capability=True,
                )

            # Register the capability
            self._capabilities[schema.name] = capability
            logger.info(
                "Capability registered",
                extra={
                    "capability_name": schema.name,
                    "description": schema.description,
                },
            )

    def get(self, name: str) -> CapabilityInterface | None:
        """Retrieve a capability by name.

        Supports namespace-based lookup (e.g., "weather.get_current").

        Args:
            name: The name of the capability to retrieve

        Returns:
            The capability if found, None otherwise

        Example:
            >>> registry = CapabilityRegistry.get_instance()
            >>> capability = registry.get("weather.get_current")
            >>> if capability:
            ...     result = capability.execute(location="New York")
        """
        with self._registry_lock:
            return self._capabilities.get(name)

    def list_all(self) -> list[str]:
        """List all registered capability names.

        Returns a sorted list of all registered capability names, including
        namespaced names.

        Returns:
            Sorted list of capability names

        Example:
            >>> registry = CapabilityRegistry.get_instance()
            >>> names = registry.list_all()
            >>> print(names)
            ['database.query', 'weather.get_current']
        """
        with self._registry_lock:
            return sorted(self._capabilities.keys())

    def unregister(self, name: str) -> None:
        """Unregister a capability from the registry.

        Removes a capability from the registry. Does nothing if the capability
        is not registered.

        Args:
            name: The name of the capability to unregister

        Example:
            >>> registry = CapabilityRegistry.get_instance()
            >>> registry.unregister("weather.get_current")
        """
        with self._registry_lock:
            if name in self._capabilities:
                del self._capabilities[name]
                logger.info(
                    "Capability unregistered",
                    extra={"capability_name": name},
                )

    def clear(self) -> None:
        """Clear all registered capabilities.

        Removes all capabilities from the registry. Useful for testing
        and resetting the registry state.

        Example:
            >>> registry = CapabilityRegistry.get_instance()
            >>> registry.clear()
        """
        with self._registry_lock:
            self._capabilities.clear()
            logger.info("Capability registry cleared")

    def get_by_namespace(self, namespace: str) -> list[CapabilityInterface]:
        """Get all capabilities in a specific namespace.

        Retrieves all capabilities whose names start with the given namespace
        prefix (e.g., "weather" returns "weather.get_current", "weather.forecast").

        Args:
            namespace: The namespace prefix to search for

        Returns:
            List of capabilities in the namespace

        Example:
            >>> registry = CapabilityRegistry.get_instance()
            >>> weather_tools = registry.get_by_namespace("weather")
        """
        with self._registry_lock:
            prefix = namespace if namespace.endswith(".") else f"{namespace}."
            return [cap for name, cap in self._capabilities.items() if name.startswith(prefix)]

    def count(self) -> int:
        """Get the total number of registered capabilities.

        Returns:
            Number of registered capabilities

        Example:
            >>> registry = CapabilityRegistry.get_instance()
            >>> total = registry.count()
        """
        with self._registry_lock:
            return len(self._capabilities)

    def exists(self, name: str) -> bool:
        """Check if a capability is registered.

        Args:
            name: The name of the capability to check

        Returns:
            True if the capability is registered, False otherwise

        Example:
            >>> registry = CapabilityRegistry.get_instance()
            >>> if registry.exists("weather.get_current"):
            ...     capability = registry.get("weather.get_current")
        """
        with self._registry_lock:
            return name in self._capabilities

    def search(
        self,
        query: str,
        limit: int = 5,
        threshold: float = 0.3,
    ) -> list[tuple[str, CapabilityInterface, float]]:
        """Search for capabilities matching a query using semantic similarity.

        Performs a semantic search across all registered capabilities by comparing
        the query against capability names and descriptions. Returns matches sorted
        by similarity score in descending order.

        Args:
            query: Search query string
            limit: Maximum number of results to return (default: 5)
            threshold: Minimum similarity score (0.0-1.0) to include in results
                (default: 0.3)

        Returns:
            List of tuples (capability_name, capability, similarity_score) sorted
            by similarity score in descending order

        Raises:
            ValueError: If search is disabled (auto_search=False)

        Example:
            >>> registry = CapabilityRegistry.get_instance()
            >>> results = registry.search("get weather")
            >>> for name, cap, score in results:
            ...     print(f"{name}: {score:.2f}")
        """
        if not self._auto_search:
            raise ValueError(
                "Search is disabled for this registry. "
                "Create registry with auto_search=True to enable search."
            )

        with self._registry_lock:
            capabilities_snapshot = dict(self._capabilities)

        # Calculate similarity scores
        scores: list[tuple[str, CapabilityInterface, float]] = []

        for name, capability in capabilities_snapshot.items():
            try:
                schema = capability.get_schema()
                # Combine name and description for matching
                searchable_text = f"{schema.name} {schema.description}".lower()
                query_lower = query.lower()

                # Calculate similarity using SequenceMatcher
                similarity = SequenceMatcher(None, query_lower, searchable_text).ratio()

                # Also check for substring matches (boost score)
                if query_lower in searchable_text:
                    similarity = min(1.0, similarity + 0.2)

                if similarity >= threshold:
                    scores.append((name, capability, similarity))

            except Exception as e:
                logger.warning(
                    "Error calculating similarity for capability",
                    extra={"capability_name": name, "error": str(e)},
                )

        # Sort by similarity score (descending) and return top results
        scores.sort(key=lambda x: x[2], reverse=True)
        return scores[:limit]

    def search_by_name(
        self,
        query: str,
        limit: int = 5,
        threshold: float = 0.3,
    ) -> list[tuple[str, CapabilityInterface, float]]:
        """Search for capabilities by name only (faster than full search).

        Performs a semantic search across capability names only, ignoring
        descriptions. Useful for quick name-based lookups.

        Args:
            query: Search query string
            limit: Maximum number of results to return (default: 5)
            threshold: Minimum similarity score (0.0-1.0) to include in results
                (default: 0.3)

        Returns:
            List of tuples (capability_name, capability, similarity_score) sorted
            by similarity score in descending order

        Raises:
            ValueError: If search is disabled (auto_search=False)

        Example:
            >>> registry = CapabilityRegistry.get_instance()
            >>> results = registry.search_by_name("weather")
            >>> for name, cap, score in results:
            ...     print(f"{name}: {score:.2f}")
        """
        if not self._auto_search:
            raise ValueError(
                "Search is disabled for this registry. "
                "Create registry with auto_search=True to enable search."
            )

        with self._registry_lock:
            capabilities_snapshot = dict(self._capabilities)

        # Calculate similarity scores for names only
        scores: list[tuple[str, CapabilityInterface, float]] = []
        query_lower = query.lower()

        for name, capability in capabilities_snapshot.items():
            try:
                name_lower = name.lower()

                # Calculate similarity using SequenceMatcher
                similarity = SequenceMatcher(None, query_lower, name_lower).ratio()

                # Boost score for substring matches
                if query_lower in name_lower:
                    similarity = min(1.0, similarity + 0.2)

                if similarity >= threshold:
                    scores.append((name, capability, similarity))

            except Exception as e:
                logger.warning(
                    "Error calculating name similarity for capability",
                    extra={"capability_name": name, "error": str(e)},
                )

        # Sort by similarity score (descending) and return top results
        scores.sort(key=lambda x: x[2], reverse=True)
        return scores[:limit]

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance.

        Clears the current instance and allows a new one to be created.
        Useful for testing.

        Example:
            >>> CapabilityRegistry.reset_instance()
            >>> new_registry = CapabilityRegistry.get_instance()
        """
        with cls._lock:
            cls._instance = None

    def execute(
        self,
        capability_name: str,
        arguments: dict[str, Any],
        tool_call_id: str | None = None,
        return_raw: bool = False,
    ) -> CapabilityMessage | Any:
        """Execute a capability and return the result.

        Executes a registered capability with the provided arguments and returns
        either a CapabilityMessage (default) or the raw function output.

        Args:
            capability_name: Name of the capability to execute
            arguments: Dictionary of arguments to pass to the capability
            tool_call_id: Optional ID from the LLM tool call for tracking
            return_raw: If True, return raw function output; if False, wrap
                in CapabilityMessage

        Returns:
            CapabilityMessage containing the result (default), or raw function
            output if return_raw=True

        Raises:
            CapabilityNotFoundError: If the capability is not registered
            CapabilityValidationError: If the arguments do not match the schema
            CapabilityExecutionError: If the capability fails while running

        Example:
            >>> registry = CapabilityRegistry.get_instance()
            >>> result = registry.execute("weather.get_current", {"location": "NYC"})
            >>> print(result.content)
            '{"temperature": 72, "condition": "sunny"}'
        """
        with self._registry_lock:
            capability = self._capabilities.get(capability_name)

        if capability is None:
            raise CapabilityNotFoundError(
                f"Capability '{capability_name}' is not registered",
                capability_name=capability_name,
            )

        try:
            # Execute the capability
            result = capability.execute(**arguments)

            # Log execution
            # The arguments are never logged: they may hold personal data
            logger.info(
                "Capability executed successfully",
                extra={"capability_name": capability_name, "tool_call_id": tool_call_id},
            )

            # Return raw result if requested
            if return_raw:
                return result

            # Convert result to text for CapabilityMessage
            # (a value JSON cannot hold is rendered, never raised)
            content = format_capability_result(result)

            # Return as CapabilityMessage
            return CapabilityMessage(
                content=content,
                capability_id=tool_call_id or capability_name,
                capability_name=capability_name,
            )

        except CapabilityError:
            # A validation error (bad arguments) stays one; an execution error is already one
            raise
        except Exception as e:
            logger.error(
                "Capability execution failed",
                extra={
                    "capability_name": capability_name,
                    "tool_call_id": tool_call_id,
                    "error_type": type(e).__name__,
                },
            )
            raise CapabilityExecutionError(
                f"Failed to execute capability '{capability_name}': {e}",
                capability_name=capability_name,
                original_error=str(e),
            ) from e

    async def aexecute(
        self,
        capability_name: str,
        arguments: dict[str, Any],
        tool_call_id: str | None = None,
        return_raw: bool = False,
    ) -> CapabilityMessage | Any:
        """Execute a capability asynchronously and return the result.

        Asynchronous version of execute(). Executes a registered capability with
        the provided arguments and returns either a CapabilityMessage (default)
        or the raw function output.

        Args:
            capability_name: Name of the capability to execute
            arguments: Dictionary of arguments to pass to the capability
            tool_call_id: Optional ID from the LLM tool call for tracking
            return_raw: If True, return raw function output; if False, wrap
                in CapabilityMessage

        Returns:
            CapabilityMessage containing the result (default), or raw function
            output if return_raw=True

        Raises:
            CapabilityNotFoundError: If the capability is not registered
            CapabilityValidationError: If the arguments do not match the schema
            CapabilityExecutionError: If the capability fails while running

        Example:
            >>> registry = CapabilityRegistry.get_instance()
            >>> result = await registry.aexecute("weather.get_current", {"location": "NYC"})
            >>> print(result.content)
            '{"temperature": 72, "condition": "sunny"}'
        """
        with self._registry_lock:
            capability = self._capabilities.get(capability_name)

        if capability is None:
            raise CapabilityNotFoundError(
                f"Capability '{capability_name}' is not registered",
                capability_name=capability_name,
            )

        try:
            # Execute the capability asynchronously
            result = await capability.aexecute(**arguments)

            # Log execution
            # The arguments are never logged: they may hold personal data
            logger.info(
                "Capability executed successfully (async)",
                extra={"capability_name": capability_name, "tool_call_id": tool_call_id},
            )

            # Return raw result if requested
            if return_raw:
                return result

            # Convert result to text for CapabilityMessage
            # (a value JSON cannot hold is rendered, never raised)
            content = format_capability_result(result)

            # Return as CapabilityMessage
            return CapabilityMessage(
                content=content,
                capability_id=tool_call_id or capability_name,
                capability_name=capability_name,
            )

        except CapabilityError:
            # A validation error (bad arguments) stays one; an execution error is already one
            raise
        except Exception as e:
            logger.error(
                "Capability execution failed (async)",
                extra={
                    "capability_name": capability_name,
                    "tool_call_id": tool_call_id,
                    "error_type": type(e).__name__,
                },
            )
            raise CapabilityExecutionError(
                f"Failed to execute capability '{capability_name}': {e}",
                capability_name=capability_name,
                original_error=str(e),
            ) from e

    # --- the ToolProvider Port: how an agent takes its toolset from this registry -------------

    def add(self, capability: CapabilityInterface) -> None:
        """Add a capability (the object ``@capability`` returns); the same as ``register``."""
        self.register(capability)

    async def list_schemas(self, operation: str | None = None) -> "list[CapabilitySchema]":
        """The schemas of every registered capability.

        A local registry has no operations, so ``operation`` selects nothing.
        """
        with self._registry_lock:
            capabilities = [self._capabilities[name] for name in sorted(self._capabilities)]
        return [capability.get_schema() for capability in capabilities]

    async def run(
        self, call: CapabilityCall, context: CapabilityContext | None = None
    ) -> CapabilityMessage:
        """Run one call and say how it ended; never raises.

        ``context`` is for providers that need a scope; a local run ignores it.
        """
        return await arun_capability_call(self.get(call.name), call.id, call.name, call.arguments)

    async def close(self) -> None:
        """A local registry holds nothing to release."""

    def list(self) -> "list[str]":
        """The registered capability names, sorted: a thin alias of ``list_all``.

        It is the name users of other libraries try first.
        """
        return self.list_all()
