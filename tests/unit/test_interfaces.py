"""Unit tests for Skye interfaces.

This module tests all core interfaces to ensure they define the correct
abstract methods and that implementations must satisfy the interface contracts.
"""

from collections.abc import Callable, Iterator
from typing import Any

import pytest

from skye.base.completion import CompleteRequest, CompleteResponse, StreamChunk, TokenUsage
from skye.base.interfaces.capability import CapabilityInterface, CapabilitySchema
from skye.base.interfaces.content_reader import ContentReaderInterface
from skye.base.interfaces.event_handler import EventHandlerInterface
from skye.base.interfaces.memory import MemoryInterface
from skye.base.interfaces.model import ModelInterface
from skye.base.interfaces.observer import EventType, ObserverInterface
from skye.base.interfaces.plugin import RegistrarInterface
from skye.base.interfaces.prompt import PromptBuilderInterface
from skye.base.interfaces.router import ModelRouterInterface, RoutingStrategy
from skye.base.interfaces.safety import SafetyFilterInterface, SafetyResult
from skye.base.interfaces.vector_encoder import VectorEncoderInterface
from skye.base.messages import ContentChunk, SkyeMessage, UserMessage
from skye.memory import MemoryEntry


class TestModelInterface:
    """Tests for ModelInterface."""

    def test_model_interface_is_abstract(self):
        """Test that ModelInterface cannot be instantiated directly."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            ModelInterface()

    def test_model_interface_abstract_methods(self):
        """Test that ModelInterface defines all required abstract methods."""
        abstract_methods = ModelInterface.__abstractmethods__
        expected_methods = {"complete", "stream", "acomplete", "astream", "get_model_info"}
        assert abstract_methods == expected_methods

    def test_incomplete_implementation_raises_error(self):
        """Test that incomplete implementations raise TypeError."""

        class IncompleteModel(ModelInterface):
            def complete(self, request: CompleteRequest) -> CompleteResponse:
                pass

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            IncompleteModel()

    def test_complete_implementation_works(self):
        """Test that a complete implementation can be instantiated."""

        class CompleteModel(ModelInterface):
            def complete(self, request: CompleteRequest) -> CompleteResponse:
                return CompleteResponse(
                    model=request.model,
                    provider="test",
                    content="Test response",
                    finish_reason="stop",
                    usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                )

            def stream(self, request: CompleteRequest) -> Iterator[StreamChunk]:
                yield StreamChunk(id="test", delta="Test", index=0)

            async def acomplete(self, request: CompleteRequest) -> CompleteResponse:
                return self.complete(request)

            async def astream(self, request: CompleteRequest) -> Iterator[StreamChunk]:
                return self.stream(request)

            def get_model_info(self) -> dict:
                return {"name": "test-model", "provider": "test"}

        # Should not raise
        model = CompleteModel()
        assert model is not None

    def test_mock_model_complete(self):
        """Test that a mock implementation can execute complete()."""

        class MockModel(ModelInterface):
            def complete(self, request: CompleteRequest) -> CompleteResponse:
                return CompleteResponse(
                    model=request.model,
                    provider="mock",
                    content=f"Echo: {request.messages[0].content}",
                    finish_reason="stop",
                    usage=TokenUsage(
                        prompt_tokens=len(request.messages[0].content.split()),
                        completion_tokens=len(request.messages[0].content.split()) + 1,
                        total_tokens=len(request.messages[0].content.split()) * 2 + 1,
                    ),
                )

            def stream(self, request: CompleteRequest) -> Iterator[StreamChunk]:
                yield StreamChunk(id="mock", delta="Test", index=0)

            async def acomplete(self, request: CompleteRequest) -> CompleteResponse:
                return self.complete(request)

            async def astream(self, request: CompleteRequest) -> Iterator[StreamChunk]:
                return self.stream(request)

            def get_model_info(self) -> dict:
                return {"name": "mock-model", "provider": "mock"}

        model = MockModel()
        request = CompleteRequest(
            messages=[UserMessage(content="Hello world")], model="mock-model"
        )
        response = model.complete(request)

        assert response.content == "Echo: Hello world"
        assert response.provider == "mock"
        assert response.usage.prompt_tokens == 2

    def test_mock_model_stream(self):
        """Test that a mock implementation can execute stream()."""

        class MockModel(ModelInterface):
            def complete(self, request: CompleteRequest) -> CompleteResponse:
                return CompleteResponse(
                    model=request.model,
                    provider="mock",
                    content="Test",
                    finish_reason="stop",
                    usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                )

            def stream(self, request: CompleteRequest) -> Iterator[StreamChunk]:
                words = ["Hello", " ", "world"]
                for i, word in enumerate(words):
                    yield StreamChunk(id="stream_123", delta=word, index=i)
                yield StreamChunk(id="stream_123", delta="", finish_reason="stop", index=len(words))

            async def acomplete(self, request: CompleteRequest) -> CompleteResponse:
                return self.complete(request)

            async def astream(self, request: CompleteRequest) -> Iterator[StreamChunk]:
                return self.stream(request)

            def get_model_info(self) -> dict:
                return {"name": "mock-model", "provider": "mock"}

        model = MockModel()
        request = CompleteRequest(
            messages=[UserMessage(content="Test")], model="mock-model", stream=True
        )

        chunks = list(model.stream(request))
        assert len(chunks) == 4
        assert chunks[0].delta == "Hello"
        assert chunks[1].delta == " "
        assert chunks[2].delta == "world"
        assert chunks[3].finish_reason == "stop"

    def test_mock_model_get_info(self):
        """Test that a mock implementation can execute get_model_info()."""

        class MockModel(ModelInterface):
            def complete(self, request: CompleteRequest) -> CompleteResponse:
                return CompleteResponse(
                    model=request.model,
                    provider="mock",
                    content="Test",
                    finish_reason="stop",
                    usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                )

            def stream(self, request: CompleteRequest) -> Iterator[StreamChunk]:
                yield StreamChunk(id="test", delta="Test", index=0)

            async def acomplete(self, request: CompleteRequest) -> CompleteResponse:
                return self.complete(request)

            async def astream(self, request: CompleteRequest) -> Iterator[StreamChunk]:
                return self.stream(request)

            def get_model_info(self) -> dict:
                return {
                    "name": "mock-gpt-4",
                    "provider": "mock",
                    "capabilities": ["completion", "streaming"],
                    "max_tokens": 8192,
                }

        model = MockModel()
        info = model.get_model_info()

        assert info["name"] == "mock-gpt-4"
        assert info["provider"] == "mock"
        assert "completion" in info["capabilities"]
        assert info["max_tokens"] == 8192

    @pytest.mark.asyncio
    async def test_mock_model_acomplete(self):
        """Test that a mock implementation can execute acomplete()."""

        class MockModel(ModelInterface):
            def complete(self, request: CompleteRequest) -> CompleteResponse:
                return CompleteResponse(
                    model=request.model,
                    provider="mock",
                    content="Async response",
                    finish_reason="stop",
                    usage=TokenUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3),
                )

            def stream(self, request: CompleteRequest) -> Iterator[StreamChunk]:
                yield StreamChunk(id="test", delta="Test", index=0)

            async def acomplete(self, request: CompleteRequest) -> CompleteResponse:
                # Simulate async operation
                return self.complete(request)

            async def astream(self, request: CompleteRequest) -> Iterator[StreamChunk]:
                return self.stream(request)

            def get_model_info(self) -> dict:
                return {"name": "mock-model", "provider": "mock"}

        model = MockModel()
        request = CompleteRequest(
            messages=[UserMessage(content="Test async")], model="mock-model"
        )
        response = await model.acomplete(request)

        assert response.content == "Async response"
        assert response.provider == "mock"


class TestPromptBuilderInterface:
    """Tests for PromptBuilderInterface."""

    # Helper base class for tests
    class BaseMockBuilder(PromptBuilderInterface):
        """Base mock implementation with all required methods."""

        def __init__(self):
            self.templates = {}
            self.defaults = {}
            self.allowed_missing = []

        def render(self, template_name: str, variables: dict) -> list[SkyeMessage]:
            template = self.get_template(template_name)
            merged = {**self.defaults, **variables}
            content = template.format(**merged)
            return [UserMessage(content=content)]

        def register_template(
            self, name: str, template: str, version: str = "1.0", from_string: bool = True
        ) -> None:
            key = f"{name}:{version}"
            self.templates[key] = template

        def get_template(self, name: str, version: str | None = None) -> str:
            key = f"{name}:{version}" if version else f"{name}:1.0"
            return self.templates.get(key, "")

        def get_template_variables(self, template_name: str) -> list[str]:
            return []

        def set_default_values(self, defaults: dict) -> None:
            self.defaults.update(defaults)

        def set_allowed_missing_variables(self, variables: list[str]) -> None:
            self.allowed_missing.extend(variables)

        def partial(self, **kwargs) -> PromptBuilderInterface:
            new_builder = type(self)()
            new_builder.templates = self.templates.copy()
            new_builder.defaults = {**self.defaults, **kwargs}
            new_builder.allowed_missing = self.allowed_missing.copy()
            return new_builder

        def invoke(self, template_name: str, variables: dict) -> list[SkyeMessage]:
            return self.render(template_name, variables)

        def format(self, template_name: str, variables: dict) -> str:
            messages = self.render(template_name, variables)
            return messages[0].content if messages else ""

        # Few-shot learning
        def add_examples(
            self, template_name: str, examples: list[dict], example_template: str | None = None
        ) -> None:
            pass

        def set_example_selector(
            self, template_name: str, selector_type: str, max_examples: int = 5, **selector_kwargs
        ) -> None:
            pass

        # Multimodal support
        def add_image_content(
            self, template_name: str, image_variable: str, image_format: str = "url"
        ) -> None:
            pass

        def add_multimodal_content(
            self, template_name: str, content_variables: dict[str, str]
        ) -> None:
            pass

        # Template engine
        def register_filter(self, filter_name: str, filter_func: Callable) -> None:
            pass

        def compose_templates(
            self, name: str, template_parts: list[str], separator: str = "\n\n"
        ) -> None:
            pass

        # Message roles
        def set_message_roles(self, template_name: str, role_mapping: dict[str, str]) -> None:
            pass

        def add_message_placeholder(
            self, template_name: str, placeholder_name: str, role: str = "user"
        ) -> None:
            pass

        # Output schema
        def set_output_schema(self, template_name: str, schema: dict | type) -> None:
            pass

        def get_output_instructions(self, template_name: str) -> str:
            return ""

        # Metadata
        def get_template_metadata(self, template_name: str) -> dict:
            return {"variables": [], "optional_variables": []}

        def validate_template(self, template_name: str) -> dict:
            return {"valid": True, "errors": [], "warnings": []}

    def test_prompt_builder_interface_is_abstract(self):
        """Test that PromptBuilderInterface cannot be instantiated directly."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            PromptBuilderInterface()

    def test_prompt_builder_interface_abstract_methods(self):
        """Test that PromptBuilderInterface defines all required abstract methods."""
        abstract_methods = PromptBuilderInterface.__abstractmethods__
        expected_methods = {
            # Core methods
            "render",
            "register_template",
            "get_template",
            "get_template_variables",
            "set_default_values",
            "set_allowed_missing_variables",
            "partial",
            "invoke",
            "format",
            # Few-shot learning
            "add_examples",
            "set_example_selector",
            # Multimodal support
            "add_image_content",
            "add_multimodal_content",
            # Template engine
            "register_filter",
            "compose_templates",
            # Message roles
            "set_message_roles",
            "add_message_placeholder",
            # Output schema
            "set_output_schema",
            "get_output_instructions",
            # Metadata
            "get_template_metadata",
            "validate_template",
        }
        assert abstract_methods == expected_methods

    def test_incomplete_implementation_raises_error(self):
        """Test that incomplete implementations raise TypeError."""

        class IncompleteBuilder(PromptBuilderInterface):
            def render(self, template_name: str, variables: dict) -> list[SkyeMessage]:
                pass

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            IncompleteBuilder()

    def test_complete_implementation_works(self):
        """Test that a complete implementation can be instantiated."""
        # Use the BaseMockBuilder which has all methods
        builder = self.BaseMockBuilder()
        assert builder is not None

    def test_mock_builder_register_and_get(self):
        """Test that a mock implementation can register and retrieve templates."""
        builder = self.BaseMockBuilder()
        builder.register_template("greeting", "Hello {name}!", version="1.0")

        template = builder.get_template("greeting", version="1.0")
        assert template == "Hello {name}!"

    def test_mock_builder_render(self):
        """Test that a mock implementation can render templates."""
        builder = self.BaseMockBuilder()
        builder.register_template("greeting", "Hello {name}! Welcome to {place}.", version="1.0")

        messages = builder.render("greeting", {"name": "Alice", "place": "Wonderland"})
        assert len(messages) == 1
        assert messages[0].content == "Hello Alice! Welcome to Wonderland."
        assert messages[0].role == "user"

    def test_mock_builder_versioning(self):
        """Test that a mock implementation supports template versioning."""
        builder = self.BaseMockBuilder()
        builder.register_template("greeting", "Hello {name}!", version="1.0")
        builder.register_template("greeting", "Hi {name}!", version="2.0")

        v1 = builder.get_template("greeting", version="1.0")
        v2 = builder.get_template("greeting", version="2.0")

        assert v1 == "Hello {name}!"
        assert v2 == "Hi {name}!"

    def test_mock_builder_default_values(self):
        """Test that a mock implementation supports default values."""
        builder = self.BaseMockBuilder()
        builder.set_default_values({"domain": "general", "output_format": "json"})
        builder.register_template("test", "Domain: {domain}, Format: {output_format}")

        messages = builder.render("test", {})
        assert "Domain: general" in messages[0].content
        assert "Format: json" in messages[0].content

    def test_mock_builder_partial(self):
        """Test that a mock implementation supports partial variable binding."""
        builder = self.BaseMockBuilder()
        builder.register_template("greeting", "Hello {name}, today is {date}")

        # Create partial with date bound
        partial_builder = builder.partial(date="2024-01-15")

        # Now only need to provide name
        messages = partial_builder.render("greeting", {"name": "Alice"})
        assert "Hello Alice, today is 2024-01-15" == messages[0].content

    def test_mock_builder_invoke(self):
        """Test that invoke() works as an alias for render()."""
        builder = self.BaseMockBuilder()
        builder.register_template("test", "Hello {name}")

        messages = builder.invoke("test", {"name": "Bob"})
        assert len(messages) == 1
        assert messages[0].content == "Hello Bob"

    def test_mock_builder_format(self):
        """Test that format() returns a plain string."""
        builder = self.BaseMockBuilder()
        builder.register_template("test", "Hello {name}")

        result = builder.format("test", {"name": "Charlie"})
        assert result == "Hello Charlie"
        assert isinstance(result, str)


class TestCapabilityInterface:
    """Tests for CapabilityInterface and CapabilitySchema."""

    def test_capability_schema_validation(self):
        """Test that CapabilitySchema validates correctly."""
        schema = CapabilitySchema(
            name="test_capability",
            description="A test capability",
            parameters={"type": "object", "properties": {"arg1": {"type": "string"}}},
            returns={"type": "string"},
        )
        assert schema.name == "test_capability"
        assert schema.description == "A test capability"
        assert "properties" in schema.parameters

    def test_capability_schema_empty_name_fails(self):
        """Test that CapabilitySchema requires non-empty name."""
        from skye.base.exceptions import ValidationError

        with pytest.raises(ValidationError):
            CapabilitySchema(name="", description="Test", parameters={}, returns={})

    def test_capability_interface_is_abstract(self):
        """Test that CapabilityInterface cannot be instantiated directly."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            CapabilityInterface()

    def test_capability_interface_abstract_methods(self):
        """Test that CapabilityInterface defines all required abstract methods."""
        abstract_methods = CapabilityInterface.__abstractmethods__
        expected_methods = {"get_schema", "execute", "aexecute"}
        assert abstract_methods == expected_methods

    def test_incomplete_implementation_raises_error(self):
        """Test that incomplete implementations raise TypeError."""

        class IncompleteCapability(CapabilityInterface):
            def get_schema(self) -> CapabilitySchema:
                return CapabilitySchema(
                    name="incomplete",
                    description="Incomplete capability",
                    parameters={},
                    returns={},
                )

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            IncompleteCapability()

    def test_complete_implementation_works(self):
        """Test that a complete implementation can be instantiated."""

        class CompleteCapability(CapabilityInterface):
            def get_schema(self) -> CapabilitySchema:
                return CapabilitySchema(
                    name="complete", description="Complete capability", parameters={}, returns={}
                )

            def execute(self, **kwargs) -> Any:
                return "executed"

            async def aexecute(self, **kwargs) -> Any:
                return "async executed"

        # Should not raise
        capability = CompleteCapability()
        assert capability is not None

    def test_mock_capability_get_schema(self):
        """Test that a mock capability can return schema."""

        class MockCapability(CapabilityInterface):
            def get_schema(self) -> CapabilitySchema:
                return CapabilitySchema(
                    name="calculator",
                    description="Perform arithmetic operations",
                    parameters={
                        "type": "object",
                        "properties": {
                            "operation": {
                                "type": "string",
                                "enum": ["add", "subtract", "multiply", "divide"],
                            },
                            "a": {"type": "number"},
                            "b": {"type": "number"},
                        },
                        "required": ["operation", "a", "b"],
                    },
                    returns={"type": "number"},
                )

            def execute(self, **kwargs) -> Any:
                op = kwargs.get("operation")
                a = kwargs.get("a", 0)
                b = kwargs.get("b", 0)
                if op == "add":
                    return a + b
                elif op == "subtract":
                    return a - b
                elif op == "multiply":
                    return a * b
                elif op == "divide":
                    return a / b if b != 0 else None
                return None

            async def aexecute(self, **kwargs) -> Any:
                return self.execute(**kwargs)

        capability = MockCapability()
        schema = capability.get_schema()

        assert schema.name == "calculator"
        assert schema.description == "Perform arithmetic operations"
        assert "properties" in schema.parameters
        assert schema.returns["type"] == "number"

    def test_mock_capability_execute(self):
        """Test that a mock capability can execute."""

        class MockCapability(CapabilityInterface):
            def get_schema(self) -> CapabilitySchema:
                return CapabilitySchema(
                    name="greeter",
                    description="Greet someone",
                    parameters={"name": {"type": "string"}},
                    returns={"type": "string"},
                )

            def execute(self, **kwargs) -> Any:
                name = kwargs.get("name", "World")
                return f"Hello, {name}!"

            async def aexecute(self, **kwargs) -> Any:
                return self.execute(**kwargs)

        capability = MockCapability()
        result = capability.execute(name="Alice")
        assert result == "Hello, Alice!"

    def test_mock_capability_execute_with_logic(self):
        """Test that a mock capability can execute complex logic."""

        class CalculatorCapability(CapabilityInterface):
            def get_schema(self) -> CapabilitySchema:
                return CapabilitySchema(
                    name="calculator",
                    description="Calculate",
                    parameters={},
                    returns={"type": "number"},
                )

            def execute(self, **kwargs) -> Any:
                operation = kwargs.get("operation")
                a = kwargs.get("a", 0)
                b = kwargs.get("b", 0)

                operations = {
                    "add": lambda x, y: x + y,
                    "subtract": lambda x, y: x - y,
                    "multiply": lambda x, y: x * y,
                    "divide": lambda x, y: x / y if y != 0 else None,
                }

                return operations.get(operation, lambda x, y: None)(a, b)

            async def aexecute(self, **kwargs) -> Any:
                return self.execute(**kwargs)

        capability = CalculatorCapability()

        assert capability.execute(operation="add", a=5, b=3) == 8
        assert capability.execute(operation="subtract", a=10, b=4) == 6
        assert capability.execute(operation="multiply", a=3, b=7) == 21
        assert capability.execute(operation="divide", a=20, b=4) == 5

    @pytest.mark.asyncio
    async def test_mock_capability_aexecute(self):
        """Test that a mock capability can execute asynchronously."""

        class MockCapability(CapabilityInterface):
            def get_schema(self) -> CapabilitySchema:
                return CapabilitySchema(
                    name="async_greeter",
                    description="Async greet",
                    parameters={},
                    returns={"type": "string"},
                )

            def execute(self, **kwargs) -> Any:
                name = kwargs.get("name", "World")
                return f"Hello, {name}!"

            async def aexecute(self, **kwargs) -> Any:
                # Simulate async operation
                return self.execute(**kwargs)

        capability = MockCapability()
        result = await capability.aexecute(name="Bob")
        assert result == "Hello, Bob!"


class TestMemoryInterface:
    """Tests for MemoryInterface and MemoryEntry."""

    def test_memory_entry_validation(self):
        """Test that MemoryEntry validates correctly."""
        entry = MemoryEntry(
            content="Test memory", memory_type="episodic", metadata={"source": "test"}
        )
        assert entry.content == "Test memory"
        assert entry.memory_type == "episodic"
        assert entry.id is not None

    def test_memory_interface_is_abstract(self):
        """Test that MemoryInterface cannot be instantiated directly."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            MemoryInterface()

    def test_memory_interface_abstract_methods(self):
        """Test that MemoryInterface defines all required abstract methods."""
        abstract_methods = MemoryInterface.__abstractmethods__
        expected_methods = {"store", "retrieve", "get_by_id", "delete"}
        assert abstract_methods == expected_methods

    def test_incomplete_implementation_raises_error(self):
        """Test that incomplete implementations raise TypeError."""

        class IncompleteMemory(MemoryInterface):
            def store(self, entry: MemoryEntry) -> str:
                return entry.id

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            IncompleteMemory()

    def test_complete_implementation_works(self):
        """Test that a complete implementation can be instantiated."""

        class CompleteMemory(MemoryInterface):
            def __init__(self):
                self.memories = {}

            def store(self, entry: MemoryEntry) -> str:
                self.memories[entry.id] = entry
                return entry.id

            def retrieve(
                self, query: str, limit: int = 10, filters: dict | None = None
            ) -> list[MemoryEntry]:
                return list(self.memories.values())[:limit]

            def get_by_id(self, entry_id: str) -> MemoryEntry | None:
                return self.memories.get(entry_id)

            def delete(self, entry_id: str) -> bool:
                if entry_id in self.memories:
                    del self.memories[entry_id]
                    return True
                return False

        # Should not raise
        memory = CompleteMemory()
        assert memory is not None

    def test_mock_memory_store(self):
        """Test that a mock memory can store entries."""

        class MockMemory(MemoryInterface):
            def __init__(self):
                self.memories = {}

            def store(self, entry: MemoryEntry) -> str:
                self.memories[entry.id] = entry
                return entry.id

            def retrieve(
                self, query: str, limit: int = 10, filters: dict | None = None
            ) -> list[MemoryEntry]:
                return []

            def get_by_id(self, entry_id: str) -> MemoryEntry | None:
                return self.memories.get(entry_id)

            def delete(self, entry_id: str) -> bool:
                return False

        memory = MockMemory()
        entry = MemoryEntry(content="Test memory", memory_type="episodic")
        entry_id = memory.store(entry)

        assert entry_id == entry.id
        assert entry_id in memory.memories

    def test_mock_memory_retrieve(self):
        """Test that a mock memory can retrieve entries."""

        class MockMemory(MemoryInterface):
            def __init__(self):
                self.memories = {}

            def store(self, entry: MemoryEntry) -> str:
                self.memories[entry.id] = entry
                return entry.id

            def retrieve(
                self, query: str, limit: int = 10, filters: dict | None = None
            ) -> list[MemoryEntry]:
                results = [m for m in self.memories.values() if query.lower() in m.content.lower()]
                if filters:
                    results = [
                        m
                        for m in results
                        if all(
                            m.metadata.get(k) == v or getattr(m, k, None) == v
                            for k, v in filters.items()
                        )
                    ]
                return results[:limit]

            def get_by_id(self, entry_id: str) -> MemoryEntry | None:
                return self.memories.get(entry_id)

            def delete(self, entry_id: str) -> bool:
                return False

        memory = MockMemory()
        memory.store(MemoryEntry(content="Alice likes coffee", memory_type="persona"))
        memory.store(MemoryEntry(content="Bob prefers tea", memory_type="persona"))
        memory.store(MemoryEntry(content="Meeting at 3pm", memory_type="episodic"))

        results = memory.retrieve("coffee")
        assert len(results) == 1
        assert "Alice" in results[0].content

    def test_mock_memory_get_by_id(self):
        """Test that a mock memory can get entries by ID."""

        class MockMemory(MemoryInterface):
            def __init__(self):
                self.memories = {}

            def store(self, entry: MemoryEntry) -> str:
                self.memories[entry.id] = entry
                return entry.id

            def retrieve(
                self, query: str, limit: int = 10, filters: dict | None = None
            ) -> list[MemoryEntry]:
                return []

            def get_by_id(self, entry_id: str) -> MemoryEntry | None:
                return self.memories.get(entry_id)

            def delete(self, entry_id: str) -> bool:
                return False

        memory = MockMemory()
        entry = MemoryEntry(content="Test", memory_type="semantic")
        entry_id = memory.store(entry)

        retrieved = memory.get_by_id(entry_id)
        assert retrieved is not None
        assert retrieved.content == "Test"

    def test_mock_memory_delete(self):
        """Test that a mock memory can delete entries."""

        class MockMemory(MemoryInterface):
            def __init__(self):
                self.memories = {}

            def store(self, entry: MemoryEntry) -> str:
                self.memories[entry.id] = entry
                return entry.id

            def retrieve(
                self, query: str, limit: int = 10, filters: dict | None = None
            ) -> list[MemoryEntry]:
                return []

            def get_by_id(self, entry_id: str) -> MemoryEntry | None:
                return self.memories.get(entry_id)

            def delete(self, entry_id: str) -> bool:
                if entry_id in self.memories:
                    del self.memories[entry_id]
                    return True
                return False

        memory = MockMemory()
        entry = MemoryEntry(content="Test", memory_type="semantic")
        entry_id = memory.store(entry)

        assert memory.delete(entry_id) is True
        assert memory.get_by_id(entry_id) is None
        assert memory.delete(entry_id) is False  # Already deleted


class TestSafetyFilterInterface:
    """Tests for SafetyFilterInterface and SafetyResult."""

    def test_safety_result_validation(self):
        """Test that SafetyResult validates correctly."""
        result = SafetyResult(is_safe=True, violations=[], confidence=0.95)
        assert result.is_safe is True
        assert len(result.violations) == 0
        assert result.confidence == 0.95

    def test_safety_filter_interface_is_abstract(self):
        """Test that SafetyFilterInterface cannot be instantiated directly."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            SafetyFilterInterface()

    def test_safety_filter_interface_abstract_methods(self):
        """Test that SafetyFilterInterface defines all required abstract methods."""
        abstract_methods = SafetyFilterInterface.__abstractmethods__
        expected_methods = {"validate_input", "validate_output", "get_policies"}
        assert abstract_methods == expected_methods

    def test_complete_implementation_works(self):
        """Test that a complete implementation can be instantiated."""

        class CompleteSafetyFilter(SafetyFilterInterface):
            def validate_input(self, content: str) -> SafetyResult:
                return SafetyResult(is_safe=True)

            def validate_output(self, content: str) -> SafetyResult:
                return SafetyResult(is_safe=True)

            def get_policies(self) -> list[str]:
                return ["profanity"]

        filter = CompleteSafetyFilter()
        assert filter is not None

    def test_mock_filter_validate_input(self):
        """Test that a mock filter can validate input."""

        class MockFilter(SafetyFilterInterface):
            def __init__(self):
                self.blocked_words = ["badword", "offensive"]

            def validate_input(self, content: str) -> SafetyResult:
                violations = [word for word in self.blocked_words if word in content.lower()]
                return SafetyResult(
                    is_safe=len(violations) == 0,
                    violations=violations,
                    confidence=1.0 if violations else 0.9,
                )

            def validate_output(self, content: str) -> SafetyResult:
                return self.validate_input(content)

            def get_policies(self) -> list[str]:
                return ["profanity"]

        filter = MockFilter()
        result = filter.validate_input("Hello world")
        assert result.is_safe is True

        result = filter.validate_input("This is badword content")
        assert result.is_safe is False
        assert "badword" in result.violations

    def test_mock_filter_get_policies(self):
        """Test that a mock filter can return policies."""

        class MockFilter(SafetyFilterInterface):
            def validate_input(self, content: str) -> SafetyResult:
                return SafetyResult(is_safe=True)

            def validate_output(self, content: str) -> SafetyResult:
                return SafetyResult(is_safe=True)

            def get_policies(self) -> list[str]:
                return ["hate_speech", "violence", "pii"]

        filter = MockFilter()
        policies = filter.get_policies()
        assert len(policies) == 3
        assert "hate_speech" in policies


class TestObserverInterface:
    """Tests for ObserverInterface."""

    def test_event_type_enum(self):
        """Test that EventType enum has expected values."""
        assert EventType.MODEL_INVOKE_START.value == "model_invoke_start"
        assert EventType.AGENT_COMPLETE.value == "agent_complete"

    def test_observer_interface_is_abstract(self):
        """Test that ObserverInterface cannot be instantiated directly."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            ObserverInterface()

    def test_observer_interface_abstract_methods(self):
        """Test that ObserverInterface defines all required abstract methods."""
        abstract_methods = ObserverInterface.__abstractmethods__
        expected_methods = {"log_event", "record_metric", "start_trace", "end_trace"}
        assert abstract_methods == expected_methods

    def test_complete_implementation_works(self):
        """Test that a complete implementation can be instantiated."""

        class CompleteObserver(ObserverInterface):
            def log_event(self, event_type: EventType, data: dict) -> None:
                pass

            def record_metric(self, name: str, value: float, tags: dict | None = None) -> None:
                pass

            def start_trace(self, name: str, metadata: dict | None = None) -> str:
                return "trace_123"

            def end_trace(self, trace_id: str, metadata: dict | None = None) -> None:
                pass

        observer = CompleteObserver()
        assert observer is not None


class TestRegistrarInterface:
    """Tests for RegistrarInterface (plugins:2.2); the Port PluginInterface is gone (task 13.4, D111)."""

    def test_registrar_has_the_nine_methods_of_the_final_kinds(self):
        methods = {n for n, m in vars(RegistrarInterface).items() if not n.startswith("_") and callable(m)}
        assert methods == {
            "provider",
            "backend",
            "credential_source",
            "routing_strategy",
            "mcp_client",
            "tokenizer",
            "template_filter",
            "agent",
            "toolkit",
            "profile",  # the call that merges a change into the profile of an existing provider (task 17.1)
        }
        assert not {"model_provider", "embedding_provider", "decision_model"} & methods

    def test_registrar_methods_take_name_target_and_a_keyword_only_replace(self):
        import inspect

        for name in ("provider", "backend", "agent", "toolkit"):
            params = inspect.signature(getattr(RegistrarInterface, name)).parameters
            assert list(params)[:3] == ["self", "name", "target"]
            assert params["replace"].kind is inspect.Parameter.KEYWORD_ONLY
            assert params["replace"].default is False

    def test_only_the_provider_method_takes_a_profile(self):
        import inspect

        with_profile = {
            n for n, m in vars(RegistrarInterface).items() if not n.startswith("_") and "profile" in inspect.signature(m).parameters
        }
        assert with_profile == {"provider"}


class TestEventHandlerInterface:
    """Tests for EventHandlerInterface."""

    def test_event_handler_interface_is_abstract(self):
        """Test that EventHandlerInterface cannot be instantiated directly."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            EventHandlerInterface()

    def test_event_handler_interface_abstract_methods(self):
        """Test that EventHandlerInterface defines all required abstract methods."""
        abstract_methods = EventHandlerInterface.__abstractmethods__
        expected_methods = {
            "on_model_invoke_start",
            "on_model_invoke_end",
            "on_model_invoke_error",
            "on_capability_invoke_start",
            "on_capability_invoke_end",
            "on_capability_invoke_error",
            "on_execution_step",
            "on_execution_complete",
        }
        assert abstract_methods == expected_methods

    def test_complete_implementation_works(self):
        """Test that a complete implementation can be instantiated."""

        class CompleteEventHandler(EventHandlerInterface):
            def on_model_invoke_start(self, model_id: str, request: Any) -> None:
                pass

            def on_model_invoke_end(self, model_id: str, response: Any) -> None:
                pass

            def on_model_invoke_error(self, model_id: str, error: Exception) -> None:
                pass

            def on_capability_invoke_start(self, capability_name: str, args: dict) -> None:
                pass

            def on_capability_invoke_end(self, capability_name: str, result: Any) -> None:
                pass

            def on_capability_invoke_error(self, capability_name: str, error: Exception) -> None:
                pass

            def on_execution_step(self, step_number: int, data: dict) -> None:
                pass

            def on_execution_complete(self, result: Any) -> None:
                pass

        handler = CompleteEventHandler()
        assert handler is not None


class TestVectorEncoderInterface:
    """Tests for VectorEncoderInterface."""

    def test_vector_encoder_interface_is_abstract(self):
        """Test that VectorEncoderInterface cannot be instantiated directly."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            VectorEncoderInterface()

    def test_vector_encoder_interface_abstract_methods(self):
        """Test that VectorEncoderInterface defines all required abstract methods."""
        abstract_methods = VectorEncoderInterface.__abstractmethods__
        expected_methods = {
            "encode",
            "encode_batch",
            "aencode",
            "aencode_batch",
            "get_vector_dimension",
        }
        assert abstract_methods == expected_methods

    def test_complete_implementation_works(self):
        """Test that a complete implementation can be instantiated."""

        class CompleteEncoder(VectorEncoderInterface):
            def encode(self, text: str) -> list[float]:
                return [0.1, 0.2, 0.3]

            def encode_batch(self, texts: list[str]) -> list[list[float]]:
                return [[0.1, 0.2, 0.3] for _ in texts]

            async def aencode(self, text: str) -> list[float]:
                return self.encode(text)

            async def aencode_batch(self, texts: list[str]) -> list[list[float]]:
                return self.encode_batch(texts)

            def get_vector_dimension(self) -> int:
                return 3

        encoder = CompleteEncoder()
        assert encoder is not None


class TestContentReaderInterface:
    """Tests for ContentReaderInterface."""

    def test_content_reader_interface_is_abstract(self):
        """Test that ContentReaderInterface cannot be instantiated directly."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            ContentReaderInterface()

    def test_content_reader_interface_abstract_methods(self):
        """Test that ContentReaderInterface defines all required abstract methods."""
        abstract_methods = ContentReaderInterface.__abstractmethods__
        expected_methods = {"read", "read_stream", "aread", "get_reader_metadata"}
        assert abstract_methods == expected_methods

    def test_complete_implementation_works(self):
        """Test that a complete implementation can be instantiated."""

        class CompleteReader(ContentReaderInterface):
            def read(self, source: str) -> list[ContentChunk]:
                return [ContentChunk(text="test", source=source)]

            def read_stream(self, source: str) -> Iterator[ContentChunk]:
                yield ContentChunk(text="test", source=source)

            async def aread(self, source: str) -> list[ContentChunk]:
                return self.read(source)

            def get_reader_metadata(self) -> dict:
                return {"formats": ["txt"]}

        reader = CompleteReader()
        assert reader is not None


class TestModelRouterInterface:
    """Tests for ModelRouterInterface."""

    def test_routing_strategy_enum(self):
        """Test that RoutingStrategy enum has expected values."""
        assert RoutingStrategy.ROUND_ROBIN.value == "round_robin"
        assert RoutingStrategy.COST_BASED.value == "cost_based"

    def test_model_router_interface_is_abstract(self):
        """Test that ModelRouterInterface cannot be instantiated directly."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            ModelRouterInterface()

    def test_model_router_interface_abstract_methods(self):
        """Test that ModelRouterInterface defines all required abstract methods."""
        abstract_methods = ModelRouterInterface.__abstractmethods__
        expected_methods = {
            "register_model",
            "select_model",
            "complete",
            "acomplete",
            "mark_model_failed",
            "get_model_health",
            "set_routing_strategy",
            "set_fallbacks",
            "set_retry_policy",
            "set_allowed_fails_policy",
            "set_cooldown_time",
            "enable_pre_call_checks",
            "set_rate_limits",
            "get_usage_stats",
            "get_cooldown_models",
            "set_model_tags",
        }
        assert abstract_methods == expected_methods

    def test_complete_implementation_works(self):
        """Test that a complete implementation can be instantiated."""

        class CompleteRouter(ModelRouterInterface):
            def register_model(self, model_id: str, model: Any) -> None:
                pass

            async def select_model(self, request: CompleteRequest) -> str:
                return "model_1"

            def complete(
                self,
                messages: list[Any],
                model: str | None = None,
                tags: list[str] | None = None,
                **kwargs: Any,
            ) -> CompleteResponse:
                return CompleteResponse(
                    model="model_1",
                    provider="test",
                    content="test",
                    finish_reason="stop",
                    usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                )

            async def acomplete(
                self,
                messages: list[Any],
                model: str | None = None,
                tags: list[str] | None = None,
                **kwargs: Any,
            ) -> CompleteResponse:
                return self.complete(messages, model=model, tags=tags, **kwargs)

            def mark_model_failed(self, model_id: str) -> None:
                pass

            def get_model_health(self, model_id: str) -> dict:
                return {"status": "healthy"}

            def set_routing_strategy(self, strategy: RoutingStrategy) -> None:
                pass

            def set_fallbacks(self, fallbacks: list[dict]) -> None:
                pass

            def set_retry_policy(self, retry_policy: dict[str, int]) -> None:
                pass

            def set_allowed_fails_policy(self, allowed_fails: dict[str, int]) -> None:
                pass

            def set_cooldown_time(self, cooldown_seconds: float) -> None:
                pass

            def enable_pre_call_checks(self, enabled: bool = True) -> None:
                pass

            def set_rate_limits(
                self, model_id: str, tpm: int | None = None, rpm: int | None = None
            ) -> None:
                pass

            def get_usage_stats(self, model_id: str) -> dict:
                return {"tpm_used": 0, "rpm_used": 0}

            def get_cooldown_models(self) -> list[dict]:
                return []

            def set_model_tags(self, model_id: str, tags: list[str]) -> None:
                pass

        router = CompleteRouter()
        assert router is not None
