"""Tests for CapabilityRegistry."""

import threading
from typing import Any

import pytest

from skye.base.messages import CapabilityMessage
from skye.tools import (
    CapabilityExecutionError,
    CapabilityInterface,
    CapabilityNotFoundError,
    CapabilityRegistry,
    CapabilitySchema,
    CapabilityValidationError,
)


class MockCapability(CapabilityInterface):
    """Mock capability for testing."""

    def __init__(
        self,
        name: str = "test_tool",
        description: str = "Test tool",
        parameters: dict[str, Any] | None = None,
    ) -> None:
        """Initialize mock capability."""
        self.name = name
        self.description = description
        self.parameters = parameters or {}
        self.execute_called = False
        self.execute_args: dict[str, Any] = {}

    def get_schema(self) -> CapabilitySchema:
        """Return capability schema."""
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
        )

    def execute(self, **kwargs: Any) -> Any:
        """Execute capability."""
        self.execute_called = True
        self.execute_args = kwargs
        return f"Result from {self.name}"

    async def aexecute(self, **kwargs: Any) -> Any:
        """Execute capability asynchronously."""
        self.execute_called = True
        self.execute_args = kwargs
        return f"Async result from {self.name}"


class TestCapabilityRegistrySingleton:
    """Test singleton pattern of CapabilityRegistry."""

    def setup_method(self) -> None:
        """Reset registry before each test."""
        CapabilityRegistry.reset_instance()

    def test_get_instance_returns_same_object(self) -> None:
        """Test that get_instance returns the same object."""
        registry1 = CapabilityRegistry.get_instance()
        registry2 = CapabilityRegistry.get_instance()

        assert registry1 is registry2

    def test_multiple_get_instance_calls_are_thread_safe(self) -> None:
        """Test that multiple threads getting instance get the same object."""
        instances: list[CapabilityRegistry] = []
        lock = threading.Lock()

        def get_instance() -> None:
            instance = CapabilityRegistry.get_instance()
            with lock:
                instances.append(instance)

        threads = [threading.Thread(target=get_instance) for _ in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # All instances should be the same
        assert len(instances) == 10
        assert all(inst is instances[0] for inst in instances)

    def test_reset_instance_creates_new_instance(self) -> None:
        """Test that reset_instance creates a new instance."""
        registry1 = CapabilityRegistry.get_instance()
        CapabilityRegistry.reset_instance()
        registry2 = CapabilityRegistry.get_instance()

        assert registry1 is not registry2


class TestCapabilityRegistryRegistration:
    """Test capability registration."""

    def setup_method(self) -> None:
        """Reset registry before each test."""
        CapabilityRegistry.reset_instance()

    def test_register_capability(self) -> None:
        """Test registering a capability."""
        registry = CapabilityRegistry.get_instance()
        capability = MockCapability(name="test_tool")

        registry.register(capability)

        assert registry.exists("test_tool")

    def test_register_multiple_capabilities(self) -> None:
        """Test registering multiple capabilities."""
        registry = CapabilityRegistry.get_instance()
        cap1 = MockCapability(name="tool1")
        cap2 = MockCapability(name="tool2")

        registry.register(cap1)
        registry.register(cap2)

        assert registry.exists("tool1")
        assert registry.exists("tool2")

    def test_register_capability_with_namespace(self) -> None:
        """Test registering capabilities with namespaces."""
        registry = CapabilityRegistry.get_instance()
        cap1 = MockCapability(name="weather_get_current")
        cap2 = MockCapability(name="weather_forecast")

        registry.register(cap1)
        registry.register(cap2)

        assert registry.exists("weather_get_current")
        assert registry.exists("weather_forecast")

    def test_register_duplicate_raises_error(self) -> None:
        """Test that registering duplicate capability raises error."""
        registry = CapabilityRegistry.get_instance()
        cap1 = MockCapability(name="test_tool")
        cap2 = MockCapability(name="test_tool")

        registry.register(cap1)

        with pytest.raises(CapabilityValidationError) as exc_info:
            registry.register(cap2)

        assert "already registered" in str(exc_info.value).lower()
        assert "test_tool" in str(exc_info.value)

    def test_register_capability_with_invalid_schema_raises_error(self) -> None:
        """Test that registering capability with invalid schema raises error."""

        class BadCapability(CapabilityInterface):
            def get_schema(self) -> CapabilitySchema:
                raise ValueError("Schema generation failed")

            def execute(self, **kwargs: Any) -> Any:
                pass

            async def aexecute(self, **kwargs: Any) -> Any:
                pass

        registry = CapabilityRegistry.get_instance()
        capability = BadCapability()

        with pytest.raises(CapabilityValidationError) as exc_info:
            registry.register(capability)

        assert "failed to get schema" in str(exc_info.value).lower()


class TestCapabilityRegistryRetrieval:
    """Test capability retrieval."""

    def setup_method(self) -> None:
        """Reset registry before each test."""
        CapabilityRegistry.reset_instance()

    def test_get_registered_capability(self) -> None:
        """Test retrieving a registered capability."""
        registry = CapabilityRegistry.get_instance()
        capability = MockCapability(name="test_tool")
        registry.register(capability)

        retrieved = registry.get("test_tool")

        assert retrieved is capability

    def test_get_nonexistent_capability_returns_none(self) -> None:
        """Test that getting nonexistent capability returns None."""
        registry = CapabilityRegistry.get_instance()

        retrieved = registry.get("nonexistent")

        assert retrieved is None

    def test_get_capability_with_namespace(self) -> None:
        """Test retrieving capability with namespace."""
        registry = CapabilityRegistry.get_instance()
        capability = MockCapability(name="weather_get_current")
        registry.register(capability)

        retrieved = registry.get("weather_get_current")

        assert retrieved is capability

    def test_get_returns_correct_capability_among_many(self) -> None:
        """Test that get returns correct capability when multiple are registered."""
        registry = CapabilityRegistry.get_instance()
        cap1 = MockCapability(name="tool1")
        cap2 = MockCapability(name="tool2")
        cap3 = MockCapability(name="tool3")

        registry.register(cap1)
        registry.register(cap2)
        registry.register(cap3)

        assert registry.get("tool1") is cap1
        assert registry.get("tool2") is cap2
        assert registry.get("tool3") is cap3


class TestCapabilityRegistryListing:
    """Test capability listing."""

    def setup_method(self) -> None:
        """Reset registry before each test."""
        CapabilityRegistry.reset_instance()

    def test_list_all_empty_registry(self) -> None:
        """Test listing capabilities in empty registry."""
        registry = CapabilityRegistry.get_instance()

        names = registry.list_all()

        assert names == []

    def test_list_all_returns_all_capabilities(self) -> None:
        """Test that list_all returns all registered capabilities."""
        registry = CapabilityRegistry.get_instance()
        cap1 = MockCapability(name="tool1")
        cap2 = MockCapability(name="tool2")
        cap3 = MockCapability(name="tool3")

        registry.register(cap1)
        registry.register(cap2)
        registry.register(cap3)

        names = registry.list_all()

        assert set(names) == {"tool1", "tool2", "tool3"}

    def test_list_all_returns_sorted_names(self) -> None:
        """Test that list_all returns sorted names."""
        registry = CapabilityRegistry.get_instance()
        registry.register(MockCapability(name="zebra"))
        registry.register(MockCapability(name="apple"))
        registry.register(MockCapability(name="monkey"))

        names = registry.list_all()

        assert names == ["apple", "monkey", "zebra"]

    def test_list_all_with_namespaces(self) -> None:
        """Test listing capabilities with namespaces."""
        registry = CapabilityRegistry.get_instance()
        registry.register(MockCapability(name="weather_get_current"))
        registry.register(MockCapability(name="weather_forecast"))
        registry.register(MockCapability(name="database_query"))

        names = registry.list_all()

        assert set(names) == {
            "weather_get_current",
            "weather_forecast",
            "database_query",
        }


class TestCapabilityRegistryUnregistration:
    """Test capability unregistration."""

    def setup_method(self) -> None:
        """Reset registry before each test."""
        CapabilityRegistry.reset_instance()

    def test_unregister_capability(self) -> None:
        """Test unregistering a capability."""
        registry = CapabilityRegistry.get_instance()
        capability = MockCapability(name="test_tool")
        registry.register(capability)

        registry.unregister("test_tool")

        assert not registry.exists("test_tool")

    def test_unregister_nonexistent_capability_does_nothing(self) -> None:
        """Test that unregistering nonexistent capability does nothing."""
        registry = CapabilityRegistry.get_instance()

        # Should not raise
        registry.unregister("nonexistent")

    def test_unregister_removes_from_list_all(self) -> None:
        """Test that unregistered capability is removed from list_all."""
        registry = CapabilityRegistry.get_instance()
        cap1 = MockCapability(name="tool1")
        cap2 = MockCapability(name="tool2")

        registry.register(cap1)
        registry.register(cap2)
        registry.unregister("tool1")

        names = registry.list_all()

        assert names == ["tool2"]

    def test_can_reregister_after_unregister(self) -> None:
        """Test that capability can be reregistered after unregistration."""
        registry = CapabilityRegistry.get_instance()
        cap1 = MockCapability(name="test_tool")
        cap2 = MockCapability(name="test_tool")

        registry.register(cap1)
        registry.unregister("test_tool")
        registry.register(cap2)

        assert registry.get("test_tool") is cap2


class TestCapabilityRegistryClear:
    """Test clearing the registry."""

    def setup_method(self) -> None:
        """Reset registry before each test."""
        CapabilityRegistry.reset_instance()

    def test_clear_removes_all_capabilities(self) -> None:
        """Test that clear removes all capabilities."""
        registry = CapabilityRegistry.get_instance()
        registry.register(MockCapability(name="tool1"))
        registry.register(MockCapability(name="tool2"))
        registry.register(MockCapability(name="tool3"))

        registry.clear()

        assert registry.list_all() == []

    def test_clear_empty_registry_does_nothing(self) -> None:
        """Test that clearing empty registry does nothing."""
        registry = CapabilityRegistry.get_instance()

        # Should not raise
        registry.clear()

        assert registry.list_all() == []

    def test_can_register_after_clear(self) -> None:
        """Test that capabilities can be registered after clear."""
        registry = CapabilityRegistry.get_instance()
        registry.register(MockCapability(name="tool1"))
        registry.clear()
        registry.register(MockCapability(name="tool2"))

        assert registry.list_all() == ["tool2"]


class TestCapabilityRegistryNamespaceOperations:
    """Test namespace-based operations."""

    def setup_method(self) -> None:
        """Reset registry before each test."""
        CapabilityRegistry.reset_instance()

    def test_get_by_namespace(self) -> None:
        """Test retrieving capabilities by namespace."""
        registry = CapabilityRegistry.get_instance()
        cap1 = MockCapability(name="weather_get_current")
        cap2 = MockCapability(name="weather_forecast")
        cap3 = MockCapability(name="database_query")

        registry.register(cap1)
        registry.register(cap2)
        registry.register(cap3)

        weather_caps = registry.get_by_namespace("weather")

        assert len(weather_caps) == 2
        assert cap1 in weather_caps
        assert cap2 in weather_caps

    def test_get_by_namespace_with_trailing_dot(self) -> None:
        """Test get_by_namespace with trailing dot."""
        registry = CapabilityRegistry.get_instance()
        cap1 = MockCapability(name="weather_get_current")
        cap2 = MockCapability(name="weather_forecast")

        registry.register(cap1)
        registry.register(cap2)

        weather_caps = registry.get_by_namespace("weather_")

        assert len(weather_caps) == 2

    def test_get_by_namespace_empty_result(self) -> None:
        """Test get_by_namespace with no matching capabilities."""
        registry = CapabilityRegistry.get_instance()
        registry.register(MockCapability(name="weather_get_current"))

        database_caps = registry.get_by_namespace("database")

        assert database_caps == []

    def test_get_by_namespace_does_not_match_partial_names(self) -> None:
        """Test that get_by_namespace doesn't match partial names."""
        registry = CapabilityRegistry.get_instance()
        registry.register(MockCapability(name="weather-service_get_current"))
        registry.register(MockCapability(name="weather_get_current"))

        weather_caps = registry.get_by_namespace("weather")

        assert len(weather_caps) == 1
        assert weather_caps[0].get_schema().name == "weather_get_current"


class TestCapabilityRegistryUtilityMethods:
    """Test utility methods."""

    def setup_method(self) -> None:
        """Reset registry before each test."""
        CapabilityRegistry.reset_instance()

    def test_count_empty_registry(self) -> None:
        """Test count on empty registry."""
        registry = CapabilityRegistry.get_instance()

        assert registry.count() == 0

    def test_count_with_capabilities(self) -> None:
        """Test count with registered capabilities."""
        registry = CapabilityRegistry.get_instance()
        registry.register(MockCapability(name="tool1"))
        registry.register(MockCapability(name="tool2"))
        registry.register(MockCapability(name="tool3"))

        assert registry.count() == 3

    def test_exists_returns_true_for_registered(self) -> None:
        """Test exists returns True for registered capability."""
        registry = CapabilityRegistry.get_instance()
        registry.register(MockCapability(name="test_tool"))

        assert registry.exists("test_tool") is True

    def test_exists_returns_false_for_unregistered(self) -> None:
        """Test exists returns False for unregistered capability."""
        registry = CapabilityRegistry.get_instance()

        assert registry.exists("nonexistent") is False


class TestCapabilityRegistryThreadSafety:
    """Test thread safety of registry operations."""

    def setup_method(self) -> None:
        """Reset registry before each test."""
        CapabilityRegistry.reset_instance()

    def test_concurrent_registration(self) -> None:
        """Test that concurrent registration is thread-safe."""
        registry = CapabilityRegistry.get_instance()
        errors: list[Exception] = []

        def register_capability(index: int) -> None:
            try:
                capability = MockCapability(name=f"tool_{index}")
                registry.register(capability)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=register_capability, args=(i,)) for i in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert len(errors) == 0
        assert registry.count() == 10

    def test_concurrent_read_write(self) -> None:
        """Test that concurrent reads and writes are thread-safe."""
        registry = CapabilityRegistry.get_instance()
        errors: list[Exception] = []

        # Pre-register some capabilities
        for i in range(5):
            registry.register(MockCapability(name=f"tool_{i}"))

        def read_and_write(index: int) -> None:
            try:
                # Read operations
                registry.list_all()
                registry.count()
                registry.get(f"tool_{index % 5}")

                # Write operations
                registry.register(MockCapability(name=f"new_tool_{index}"))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=read_and_write, args=(i,)) for i in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert len(errors) == 0
        assert registry.count() == 15  # 5 original + 10 new

    def test_concurrent_unregister(self) -> None:
        """Test that concurrent unregistration is thread-safe."""
        registry = CapabilityRegistry.get_instance()

        # Pre-register capabilities
        for i in range(20):
            registry.register(MockCapability(name=f"tool_{i}"))

        errors: list[Exception] = []

        def unregister_capability(index: int) -> None:
            try:
                registry.unregister(f"tool_{index}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=unregister_capability, args=(i,)) for i in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert len(errors) == 0
        assert registry.count() == 0


class TestCapabilityRegistrySearch:
    """Test capability search functionality."""

    def setup_method(self) -> None:
        """Reset registry before each test."""
        CapabilityRegistry.reset_instance()

    def test_search_by_exact_name(self) -> None:
        """Test searching for capability by exact name."""
        registry = CapabilityRegistry.get_instance()
        cap1 = MockCapability(name="weather_get_current")
        cap2 = MockCapability(name="weather_forecast")
        cap3 = MockCapability(name="database_query")

        registry.register(cap1)
        registry.register(cap2)
        registry.register(cap3)

        results = registry.search("weather_get_current")

        assert len(results) == 1
        assert results[0][0] == "weather_get_current"
        assert results[0][1] is cap1

    def test_search_by_partial_name(self) -> None:
        """Test searching for capabilities by partial name."""
        registry = CapabilityRegistry.get_instance()
        cap1 = MockCapability(name="weather_get_current")
        cap2 = MockCapability(name="weather_forecast")
        cap3 = MockCapability(name="database_query")

        registry.register(cap1)
        registry.register(cap2)
        registry.register(cap3)

        results = registry.search("weather")

        assert len(results) == 2
        names = {name for name, _ in results}
        assert names == {"weather_get_current", "weather_forecast"}

    def test_search_case_insensitive(self) -> None:
        """Test that search is case-insensitive."""
        registry = CapabilityRegistry.get_instance()
        cap1 = MockCapability(name="Weather_GetCurrent")
        cap2 = MockCapability(name="database_query")

        registry.register(cap1)
        registry.register(cap2)

        results = registry.search("weather")

        assert len(results) == 1
        assert results[0][0] == "Weather_GetCurrent"

    def test_search_no_matches(self) -> None:
        """Test search with no matching capabilities."""
        registry = CapabilityRegistry.get_instance()
        registry.register(MockCapability(name="weather_get_current"))
        registry.register(MockCapability(name="database_query"))

        results = registry.search("nonexistent")

        assert results == []

    def test_search_empty_registry(self) -> None:
        """Test search on empty registry."""
        registry = CapabilityRegistry.get_instance()

        results = registry.search("anything")

        assert results == []

    def test_search_returns_tuples(self) -> None:
        """Test that search returns tuples of (name, capability)."""
        registry = CapabilityRegistry.get_instance()
        cap = MockCapability(name="test_tool")
        registry.register(cap)

        results = registry.search("test")

        assert len(results) == 1
        name, capability = results[0]
        assert name == "test_tool"
        assert capability is cap

    def test_search_multiple_matches(self) -> None:
        """Test search with multiple matching capabilities."""
        registry = CapabilityRegistry.get_instance()
        cap1 = MockCapability(name="get_weather")
        cap2 = MockCapability(name="get_forecast")
        cap3 = MockCapability(name="set_alarm")

        registry.register(cap1)
        registry.register(cap2)
        registry.register(cap3)

        results = registry.search("get")

        assert len(results) == 2
        names = {name for name, _ in results}
        assert names == {"get_weather", "get_forecast"}

    def test_search_with_namespace_pattern(self) -> None:
        """Test search with namespace pattern."""
        registry = CapabilityRegistry.get_instance()
        cap1 = MockCapability(name="weather_get_current")
        cap2 = MockCapability(name="weather_forecast")
        cap3 = MockCapability(name="database_weather_query")

        registry.register(cap1)
        registry.register(cap2)
        registry.register(cap3)

        results = registry.search("weather_")

        assert len(results) == 2
        names = {name for name, _ in results}
        assert names == {"weather_get_current", "weather_forecast"}

    def test_search_preserves_capability_references(self) -> None:
        """Test that search returns actual capability references."""
        registry = CapabilityRegistry.get_instance()
        cap1 = MockCapability(name="tool1")
        cap2 = MockCapability(name="tool2")

        registry.register(cap1)
        registry.register(cap2)

        results = registry.search("tool")

        # Verify we can execute the returned capabilities
        for name, cap in results:
            result = cap.execute()
            assert f"Result from {name}" in result


class TestCapabilityRegistryExecution:
    """Test capability execution through registry."""

    def setup_method(self) -> None:
        """Reset registry before each test."""
        CapabilityRegistry.reset_instance()

    def test_execute_capability_returns_capability_message(self) -> None:
        """Test that execute returns CapabilityMessage by default."""
        registry = CapabilityRegistry.get_instance()
        capability = MockCapability(name="test_tool")
        registry.register(capability)

        result = registry.execute("test_tool", {})

        assert isinstance(result, CapabilityMessage)
        assert result.capability_name == "test_tool"
        assert "Result from test_tool" in result.content

    def test_execute_capability_with_arguments(self) -> None:
        """Test executing capability with arguments."""
        registry = CapabilityRegistry.get_instance()
        capability = MockCapability(name="test_tool")
        registry.register(capability)

        result = registry.execute("test_tool", {"arg1": "value1", "arg2": 42})

        assert isinstance(result, CapabilityMessage)
        assert capability.execute_called
        assert capability.execute_args == {"arg1": "value1", "arg2": 42}

    def test_execute_capability_with_tool_call_id(self) -> None:
        """Test executing capability with tool call ID."""
        registry = CapabilityRegistry.get_instance()
        capability = MockCapability(name="test_tool")
        registry.register(capability)

        result = registry.execute("test_tool", {}, tool_call_id="call_123")

        assert isinstance(result, CapabilityMessage)
        assert result.capability_id == "call_123"

    def test_execute_capability_return_raw(self) -> None:
        """Test executing capability with return_raw=True."""
        registry = CapabilityRegistry.get_instance()
        capability = MockCapability(name="test_tool")
        registry.register(capability)

        result = registry.execute("test_tool", {}, return_raw=True)

        assert result == "Result from test_tool"
        assert not isinstance(result, CapabilityMessage)

    def test_execute_nonexistent_capability_raises_error(self) -> None:
        """Test that executing nonexistent capability raises error."""
        registry = CapabilityRegistry.get_instance()

        with pytest.raises(CapabilityNotFoundError) as exc_info:
            registry.execute("nonexistent", {})

        assert "nonexistent" in str(exc_info.value)

    def test_execute_capability_with_dict_result(self) -> None:
        """Test executing capability that returns dict."""
        registry = CapabilityRegistry.get_instance()

        class DictCapability(CapabilityInterface):
            def get_schema(self) -> CapabilitySchema:
                return CapabilitySchema(name="dict_tool", description="Returns dict")

            def execute(self, **kwargs: Any) -> Any:
                return {"status": "success", "data": [1, 2, 3]}

            async def aexecute(self, **kwargs: Any) -> Any:
                return {"status": "success", "data": [1, 2, 3]}

        capability = DictCapability()
        registry.register(capability)

        result = registry.execute("dict_tool", {})

        assert isinstance(result, CapabilityMessage)
        assert '"status": "success"' in result.content

    def test_execute_capability_with_string_result(self) -> None:
        """Test executing capability that returns string."""
        registry = CapabilityRegistry.get_instance()

        class StringCapability(CapabilityInterface):
            def get_schema(self) -> CapabilitySchema:
                return CapabilitySchema(name="string_tool", description="Returns string")

            def execute(self, **kwargs: Any) -> Any:
                return "Hello, World!"

            async def aexecute(self, **kwargs: Any) -> Any:
                return "Hello, World!"

        capability = StringCapability()
        registry.register(capability)

        result = registry.execute("string_tool", {})

        assert isinstance(result, CapabilityMessage)
        assert result.content == "Hello, World!"

    def test_execute_capability_with_execution_error(self) -> None:
        """Test that execution errors are wrapped properly."""
        registry = CapabilityRegistry.get_instance()

        class FailingCapability(CapabilityInterface):
            def get_schema(self) -> CapabilitySchema:
                return CapabilitySchema(name="failing_tool", description="Fails")

            def execute(self, **kwargs: Any) -> Any:
                raise ValueError("Execution failed")

            async def aexecute(self, **kwargs: Any) -> Any:
                raise ValueError("Execution failed")

        capability = FailingCapability()
        registry.register(capability)

        with pytest.raises(CapabilityExecutionError) as exc_info:
            registry.execute("failing_tool", {})

        assert "failing_tool" in str(exc_info.value)
        assert "Execution failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_aexecute_capability_returns_capability_message(self) -> None:
        """Test that aexecute returns CapabilityMessage by default."""
        registry = CapabilityRegistry.get_instance()
        capability = MockCapability(name="test_tool")
        registry.register(capability)

        result = await registry.aexecute("test_tool", {})

        assert isinstance(result, CapabilityMessage)
        assert result.capability_name == "test_tool"

    @pytest.mark.asyncio
    async def test_aexecute_capability_with_arguments(self) -> None:
        """Test async executing capability with arguments."""
        registry = CapabilityRegistry.get_instance()
        capability = MockCapability(name="test_tool")
        registry.register(capability)

        result = await registry.aexecute("test_tool", {"arg1": "value1"})

        assert isinstance(result, CapabilityMessage)
        assert capability.execute_called

    @pytest.mark.asyncio
    async def test_aexecute_capability_return_raw(self) -> None:
        """Test async executing capability with return_raw=True."""
        registry = CapabilityRegistry.get_instance()
        capability = MockCapability(name="test_tool")
        registry.register(capability)

        result = await registry.aexecute("test_tool", {}, return_raw=True)

        assert result == "Async result from test_tool"

    @pytest.mark.asyncio
    async def test_aexecute_nonexistent_capability_raises_error(self) -> None:
        """Test that async executing nonexistent capability raises error."""
        registry = CapabilityRegistry.get_instance()

        with pytest.raises(CapabilityNotFoundError) as exc_info:
            await registry.aexecute("nonexistent", {})

        assert "nonexistent" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_aexecute_capability_with_execution_error(self) -> None:
        """Test that async execution errors are wrapped properly."""
        registry = CapabilityRegistry.get_instance()

        class FailingCapability(CapabilityInterface):
            def get_schema(self) -> CapabilitySchema:
                return CapabilitySchema(name="failing_tool", description="Fails")

            def execute(self, **kwargs: Any) -> Any:
                raise ValueError("Execution failed")

            async def aexecute(self, **kwargs: Any) -> Any:
                raise ValueError("Async execution failed")

        capability = FailingCapability()
        registry.register(capability)

        with pytest.raises(CapabilityExecutionError) as exc_info:
            await registry.aexecute("failing_tool", {})

        assert "failing_tool" in str(exc_info.value)


class TestCapabilityRegistrySearch:
    """Test semantic search functionality."""

    def setup_method(self) -> None:
        """Reset registry before each test."""
        CapabilityRegistry.reset_instance()

    def test_search_finds_exact_name_match(self) -> None:
        """Test that search finds exact name matches."""
        registry = CapabilityRegistry.get_instance()
        registry.register(MockCapability(name="weather_get_current"))
        registry.register(MockCapability(name="database_query"))

        results = registry.search("weather")

        assert len(results) > 0
        assert results[0][0] == "weather_get_current"

    def test_search_finds_description_match(self) -> None:
        """Test that search finds matches in descriptions."""
        registry = CapabilityRegistry.get_instance()
        registry.register(
            MockCapability(
                name="tool1", description="Get current weather information"
            )
        )
        registry.register(MockCapability(name="tool2", description="Query database"))

        results = registry.search("weather")

        assert len(results) > 0
        assert results[0][0] == "tool1"

    def test_search_respects_limit(self) -> None:
        """Test that search respects the limit parameter."""
        registry = CapabilityRegistry.get_instance()
        for i in range(10):
            registry.register(
                MockCapability(name=f"tool_{i}", description="Tool description")
            )

        results = registry.search("tool", limit=3)

        assert len(results) <= 3

    def test_search_respects_threshold(self) -> None:
        """Test that search respects the threshold parameter."""
        registry = CapabilityRegistry.get_instance()
        registry.register(MockCapability(name="weather", description="Weather tool"))
        registry.register(MockCapability(name="xyz", description="XYZ tool"))

        results = registry.search("weather", threshold=0.8)

        # Should only include high-similarity matches
        assert all(score >= 0.8 for _, _, score in results)

    def test_search_returns_sorted_by_score(self) -> None:
        """Test that search results are sorted by similarity score."""
        registry = CapabilityRegistry.get_instance()
        registry.register(MockCapability(name="weather", description="Weather"))
        registry.register(MockCapability(name="weather_forecast", description="Forecast"))
        registry.register(MockCapability(name="database", description="Database"))

        results = registry.search("weather")

        # Results should be sorted by score (descending)
        scores = [score for _, _, score in results]
        assert scores == sorted(scores, reverse=True)

    def test_search_case_insensitive(self) -> None:
        """Test that search is case-insensitive."""
        registry = CapabilityRegistry.get_instance()
        registry.register(MockCapability(name="Weather_GetCurrent"))

        results_lower = registry.search("weather")
        results_upper = registry.search("WEATHER")

        assert len(results_lower) > 0
        assert len(results_upper) > 0
        assert results_lower[0][2] == results_upper[0][2]

    def test_search_empty_registry(self) -> None:
        """Test search on empty registry."""
        registry = CapabilityRegistry.get_instance()

        results = registry.search("anything")

        assert results == []

    def test_search_disabled_raises_error(self) -> None:
        """Test that search raises error when disabled."""
        CapabilityRegistry.reset_instance()
        registry = CapabilityRegistry(auto_search=False)

        with pytest.raises(ValueError) as exc_info:
            registry.search("query")

        assert "disabled" in str(exc_info.value).lower()

    def test_search_by_name_finds_matches(self) -> None:
        """Test that search_by_name finds name matches."""
        registry = CapabilityRegistry.get_instance()
        registry.register(
            MockCapability(
                name="weather_get_current",
                description="Some other description",
            )
        )
        registry.register(MockCapability(name="database_query"))

        results = registry.search_by_name("weather")

        assert len(results) > 0
        assert results[0][0] == "weather_get_current"

    def test_search_by_name_ignores_description(self) -> None:
        """Test that search_by_name ignores descriptions."""
        registry = CapabilityRegistry.get_instance()
        registry.register(
            MockCapability(name="tool1", description="weather information")
        )
        registry.register(MockCapability(name="weather", description="other"))

        results = registry.search_by_name("weather")

        # Should find "weather" name match first
        assert results[0][0] == "weather"

    def test_search_by_name_disabled_raises_error(self) -> None:
        """Test that search_by_name raises error when disabled."""
        CapabilityRegistry.reset_instance()
        registry = CapabilityRegistry(auto_search=False)

        with pytest.raises(ValueError) as exc_info:
            registry.search_by_name("query")

        assert "disabled" in str(exc_info.value).lower()

    def test_search_with_namespace(self) -> None:
        """Test search with namespaced capability names."""
        registry = CapabilityRegistry.get_instance()
        registry.register(MockCapability(name="weather_get_current"))
        registry.register(MockCapability(name="weather_forecast"))
        registry.register(MockCapability(name="database_query"))

        results = registry.search("weather")

        # Should find both weather capabilities
        weather_results = [name for name, _, _ in results if "weather" in name]
        assert len(weather_results) >= 2

    def test_search_substring_match_boost(self) -> None:
        """Test that substring matches get a score boost."""
        registry = CapabilityRegistry.get_instance()
        registry.register(MockCapability(name="get_weather", description="Get weather"))
        registry.register(MockCapability(name="tool_a", description="Something else"))

        results = registry.search("weather")

        # get_weather should rank higher due to substring match
        assert results[0][0] == "get_weather"

    def test_search_returns_capability_objects(self) -> None:
        """Test that search returns actual capability objects."""
        registry = CapabilityRegistry.get_instance()
        cap = MockCapability(name="test_tool")
        registry.register(cap)

        results = registry.search("test")

        assert len(results) > 0
        name, returned_cap, score = results[0]
        assert returned_cap is cap
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0


class TestCapabilityRegistryInitialization:
    """Test registry initialization with capabilities."""

    def test_init_with_capabilities_list(self) -> None:
        """Test initializing registry with capabilities list."""
        CapabilityRegistry.reset_instance()
        cap1 = MockCapability(name="tool1")
        cap2 = MockCapability(name="tool2")

        registry = CapabilityRegistry(capabilities=[cap1, cap2])

        assert registry.count() == 2
        assert registry.exists("tool1")
        assert registry.exists("tool2")

    def test_init_with_empty_capabilities_list(self) -> None:
        """Test initializing registry with empty capabilities list."""
        CapabilityRegistry.reset_instance()

        registry = CapabilityRegistry(capabilities=[])

        assert registry.count() == 0

    def test_init_with_auto_search_true(self) -> None:
        """Test initializing registry with auto_search=True."""
        CapabilityRegistry.reset_instance()
        cap = MockCapability(name="test_tool")

        registry = CapabilityRegistry(capabilities=[cap], auto_search=True)

        # Should be able to search
        results = registry.search("test")
        assert len(results) > 0

    def test_init_with_auto_search_false(self) -> None:
        """Test initializing registry with auto_search=False."""
        CapabilityRegistry.reset_instance()
        cap = MockCapability(name="test_tool")

        registry = CapabilityRegistry(capabilities=[cap], auto_search=False)

        # Should not be able to search
        with pytest.raises(ValueError):
            registry.search("test")

    def test_init_registers_capabilities_in_order(self) -> None:
        """Test that capabilities are registered in order."""
        CapabilityRegistry.reset_instance()
        caps = [MockCapability(name=f"tool_{i}") for i in range(5)]

        registry = CapabilityRegistry(capabilities=caps)

        names = registry.list_all()
        assert names == [f"tool_{i}" for i in range(5)]

    def test_init_with_duplicate_capabilities_raises_error(self) -> None:
        """Test that duplicate capabilities in init list raise error."""
        CapabilityRegistry.reset_instance()
        cap1 = MockCapability(name="tool")
        cap2 = MockCapability(name="tool")

        with pytest.raises(CapabilityValidationError):
            CapabilityRegistry(capabilities=[cap1, cap2])

    def test_direct_instantiation_with_auto_search_false(self) -> None:
        """Test direct instantiation with auto_search=False."""
        registry = CapabilityRegistry(auto_search=False)

        # auto_search should be disabled
        with pytest.raises(ValueError):
            registry.search("query")
