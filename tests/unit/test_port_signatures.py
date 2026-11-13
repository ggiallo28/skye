"""Every built-in implementation conforms to its Port by signature (Requirements 16.6, 16.7, 16.9; tasks 3.1, 3.2, 3.8).

The checker compares parameter names and kinds, the ``def`` / ``async def`` / async-generator form, and the return annotation by
name. ``KNOWN_MISMATCHES`` lists the differences that exist today; it only shrinks: an entry that no longer mismatches fails.
Every exported Port with methods also has a short reference implementation in this file, so no Port is exported untested.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from collections.abc import Iterator, Sequence
from typing import Any

import pytest

import skye
import skye.interfaces as interfaces
from skye.base.exceptions import ValidationError
from skye.base.plugins import Registrar
from skye.interfaces import (
    AuthenticationInterface,
    AuthorizerInterface,
    CapabilityInterface,
    ConfigLoaderInterface,
    ContentReaderInterface,
    CostCalculatorInterface,
    Decision,
    DecisionModel,
    DecisionResult,
    EventHandlerInterface,
    MemoryInterface,
    ObserverInterface,
    RegistrarInterface,
    Runnable,
    SafetyFilterInterface,
    TokenCounterInterface,
    ToolProvider,
)
from skye.utils.validation import port_methods, port_signature_mismatches, validate_port_signatures

# Exported names that are data types or enums, not Ports.
NOT_PORTS = {"CapabilityContext", "CapabilitySchema", "Decision", "DecisionResult", "EventType", "MemoryEntryLike", "Resource", "RoutingStrategy", "SafetyResult"}

# (implementation, Port) pairs that differ today. Only shrinks; empty after D36 (model call shape) and D41 (Port reconciliation).
KNOWN_MISMATCHES: set[tuple[str, str]] = set()


def _load_everything() -> None:
    for module in pkgutil.walk_packages(skye.__path__, "skye."):
        try:
            importlib.import_module(module.name)
        except Exception:  # an optional dependency that is not installed
            continue


def _subclasses(port: type) -> list[type]:
    found: list[type] = []
    for sub in port.__subclasses__():
        found.append(sub)
        found += _subclasses(sub)
    return found


def _ports() -> list[type]:
    ports = []
    for name in interfaces.__all__:
        obj = getattr(interfaces, name)
        if name not in NOT_PORTS and inspect.isclass(obj) and port_methods(obj):
            ports.append(obj)
    return ports


_load_everything()
PORTS = _ports()
PAIRS = sorted(
    {(impl, port) for port in PORTS for impl in _subclasses(port) if impl.__module__.startswith("skye.")},
    key=lambda pair: (pair[1].__name__, pair[0].__name__),
)


def _problems(impl: type, port: type) -> list[str]:
    problems = port_signature_mismatches(impl, port)
    if inspect.isabstract(impl):  # an abstract base may leave methods abstract
        problems = [p for p in problems if "still abstract" not in p]
    return problems


@pytest.mark.parametrize("impl,port", PAIRS, ids=[f"{i.__name__}-{p.__name__}" for i, p in PAIRS])
def test_built_in_implementation_conforms(impl: type, port: type):
    problems = _problems(impl, port)
    if (impl.__name__, port.__name__) in KNOWN_MISMATCHES:
        assert problems, f"{impl.__name__} now conforms to {port.__name__}: remove it from KNOWN_MISMATCHES"
    else:
        assert not problems, problems


def test_known_mismatches_name_real_pairs():
    pairs = {(i.__name__, p.__name__) for i, p in PAIRS}
    assert KNOWN_MISMATCHES <= pairs


# --- the checker itself ------------------------------------------------------------------------------------------------


def test_checker_catches_a_renamed_parameter_a_missing_method_and_a_changed_form():
    class Renamed:
        def count_tokens(self, content: str, model: str) -> int:
            return 0

    class Asynced:
        async def count_tokens(self, text: str, model: str) -> int:
            return 0

        def count_message_tokens(self, messages: list[Any], model: str) -> int:
            return 0

    assert any("count_tokens: parameters" in p for p in port_signature_mismatches(Renamed, TokenCounterInterface))
    assert "count_message_tokens: missing" in port_signature_mismatches(Renamed, TokenCounterInterface)
    assert any("form async def" in p for p in port_signature_mismatches(Asynced, TokenCounterInterface))
    with pytest.raises(ValidationError):
        validate_port_signatures(Renamed, TokenCounterInterface)


def test_checker_allows_added_methods_and_defaulted_parameters():
    class Extra:
        def count_tokens(self, text: str, model: str, cache: bool = False) -> int:
            return 0

        def count_message_tokens(self, messages: list[Any], model: str, **options: Any) -> int:
            return 0

        def extra(self) -> None: ...

    assert port_signature_mismatches(Extra(), TokenCounterInterface) == []


# --- reference implementations: one per Port, short, offline -----------------------------------------------------------


class RefAuthentication:
    def apply(self, method: str, url: str, headers: Any, body: bytes = b"") -> dict[str, str]:
        return {**headers, "Authorization": "Bearer x"}


class RefAuthorizer:
    def authorize(self, principal: str, action: str, resource: str) -> Decision:
        return Decision(allowed=True, reason="reference") if "allowed" in Decision.__dataclass_fields__ else Decision()  # type: ignore[call-arg]


class RefCapability(CapabilityInterface):
    def get_schema(self):  # type: ignore[no-untyped-def]
        return interfaces.CapabilitySchema(name="echo", description="echo")

    def execute(self, **kwargs: Any) -> Any:
        return kwargs

    async def aexecute(self, **kwargs: Any) -> Any:
        return kwargs


class RefConfigLoader(ConfigLoaderInterface):
    def load(self, text: str | None = None, overrides: dict[str, Any] | None = None):  # type: ignore[no-untyped-def]
        raise NotImplementedError


class RefContentReader(ContentReaderInterface):
    def read(self, source: str) -> list[Any]:
        return []

    async def aread(self, source: str) -> list[Any]:
        return []

    def read_stream(self, source: str) -> Iterator[Any]:
        return iter(())

    def get_reader_metadata(self) -> dict[str, Any]:
        return {}


class RefCostCalculator(CostCalculatorInterface):
    def __init__(self) -> None:
        self.prices: dict[str, dict[str, float]] = {}

    def calculate_cost(self, model: str, usage: Any, custom_pricing: dict[str, float] | None = None) -> float:
        return 0.0

    def get_pricing(self, model: str) -> dict[str, float] | None:
        return self.prices.get(model)

    def list_models(self) -> list[str]:
        return list(self.prices)

    def add_custom_pricing(self, model: str, prompt_price: float, completion_price: float) -> None:
        self.prices[model] = {"prompt": prompt_price, "completion": completion_price}


class RefDecisionModel:
    async def decide(self, prompt: str, options: Sequence[str]) -> DecisionResult:
        raise NotImplementedError


class RefEventHandler(EventHandlerInterface):
    def on_model_invoke_start(self, model_id: str, request: Any) -> None: ...
    def on_model_invoke_end(self, model_id: str, response: Any) -> None: ...
    def on_model_invoke_error(self, model_id: str, error: Exception) -> None: ...
    def on_capability_invoke_start(self, capability_name: str, args: dict[str, Any]) -> None: ...
    def on_capability_invoke_end(self, capability_name: str, result: Any) -> None: ...
    def on_capability_invoke_error(self, capability_name: str, error: Exception) -> None: ...
    def on_execution_step(self, step_number: int, data: dict[str, Any]) -> None: ...
    def on_execution_complete(self, result: Any) -> None: ...


class RefMemory(MemoryInterface):
    def __init__(self) -> None:
        self.items: dict[str, Any] = {}

    def store(self, entry: Any) -> str:
        self.items[str(len(self.items))] = entry
        return str(len(self.items) - 1)

    def retrieve(self, query: str, limit: int = 10, filters: dict[str, Any] | None = None) -> list[Any]:
        return list(self.items.values())[:limit]

    def get_by_id(self, entry_id: str) -> Any | None:
        return self.items.get(entry_id)

    def delete(self, entry_id: str) -> bool:
        return self.items.pop(entry_id, None) is not None


class RefObserver(ObserverInterface):
    def start_trace(self, name: str, metadata: dict[str, Any] | None = None) -> str:
        return "t1"

    def end_trace(self, trace_id: str, metadata: dict[str, Any] | None = None) -> None: ...
    def log_event(self, event_type: Any, data: dict[str, Any]) -> None: ...
    def record_metric(self, name: str, value: float, tags: dict[str, str] | None = None) -> None: ...


class RefRunnable:
    async def invoke(self, input: Any) -> Any:
        return input


class RefToolProvider:
    async def list_schemas(self, operation: str | None = None):  # type: ignore[no-untyped-def]
        return []

    async def run(self, call, context=None):  # type: ignore[no-untyped-def]
        return None

    async def close(self) -> None:
        return None


class RefSafetyFilter(SafetyFilterInterface):
    def validate_input(self, content: str):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def validate_output(self, content: str):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def get_policies(self) -> list[str]:
        return []


class RefTokenCounter(TokenCounterInterface):
    def count_tokens(self, text: str, model: str) -> int:
        return len(text.split())

    def count_message_tokens(self, messages: list[Any], model: str) -> int:
        return 0


REFERENCES: dict[type, type] = {
    AuthenticationInterface: RefAuthentication,
    AuthorizerInterface: RefAuthorizer,
    CapabilityInterface: RefCapability,
    ConfigLoaderInterface: RefConfigLoader,
    ContentReaderInterface: RefContentReader,
    CostCalculatorInterface: RefCostCalculator,
    DecisionModel: RefDecisionModel,
    EventHandlerInterface: RefEventHandler,
    MemoryInterface: RefMemory,
    ObserverInterface: RefObserver,
    RegistrarInterface: Registrar,  # the built-in implementation (plugins:2.6)
    Runnable: RefRunnable,
    SafetyFilterInterface: RefSafetyFilter,
    TokenCounterInterface: RefTokenCounter,
    ToolProvider: RefToolProvider,
}


@pytest.mark.parametrize("port", list(REFERENCES), ids=lambda p: p.__name__)
def test_reference_implementation_conforms(port: type):
    assert port_signature_mismatches(REFERENCES[port], port) == []


def test_every_exported_port_has_a_built_in_or_reference_implementation():
    covered = {port for _, port in PAIRS} | set(REFERENCES)
    missing = sorted(p.__name__ for p in PORTS if p not in covered)
    assert not missing, f"Ports with no implementation checked: {missing}"


def test_the_capability_registry_is_a_tool_provider():
    from skye.tools import CapabilityRegistry

    assert port_signature_mismatches(CapabilityRegistry, ToolProvider) == []
    assert isinstance(CapabilityRegistry(), ToolProvider)


# --- implementations that satisfy a Port by structure, not by inheritance (decision D41) ---------------------------------


def test_config_loader_satisfies_its_port_by_structure():
    """``skye.config.ConfigLoader`` cannot inherit the Port (the Port imports ``SkyeConfig`` from the same module)."""
    from skye.base.config import ConfigLoader

    assert port_signature_mismatches(ConfigLoader, ConfigLoaderInterface) == []
