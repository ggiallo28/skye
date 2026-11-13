"""Inject optional services into an agent (proposed-interface, guarded).

An agent gets its optional services (memory, guard, observe) through the real Ports, never by importing a concrete component. The services
below are small local classes that satisfy ``MemoryInterface``, ``SafetyFilterInterface`` and ``ObserverInterface``. The agent loop that consumes
them ships with the future agents spec, so this builds the wiring and stops before invoking any loop.
"""

import asyncio
from typing import Any

import skye
from skye.agents import REACT
from skye.interfaces import (
    EventType,
    MemoryEntryLike,
    MemoryInterface,
    ObserverInterface,
    Runnable,
    SafetyFilterInterface,
    SafetyResult,
)


class InMemoryStore(MemoryInterface):
    def __init__(self) -> None:
        self._entries: dict[str, MemoryEntryLike] = {}

    def store(self, entry: MemoryEntryLike) -> str:
        self._entries[entry.id] = entry
        return entry.id

    def retrieve(self, query: str, limit: int = 10, filters: dict[str, Any] | None = None) -> list[MemoryEntryLike]:
        return [e for e in self._entries.values() if query.lower() in e.content.lower()][:limit]

    def get_by_id(self, entry_id: str) -> MemoryEntryLike | None:
        return self._entries.get(entry_id)

    def delete(self, entry_id: str) -> bool:
        return self._entries.pop(entry_id, None) is not None


class AllowAllFilter(SafetyFilterInterface):
    def validate_input(self, content: str) -> SafetyResult:
        return SafetyResult(is_safe=True)

    def validate_output(self, content: str) -> SafetyResult:
        return SafetyResult(is_safe=True)

    def get_policies(self) -> list[str]:
        return ["none"]


class PrintObserver(ObserverInterface):
    def log_event(self, event_type: EventType, data: dict[str, Any]) -> None:
        print(f"event: {event_type.value} {data}")

    def record_metric(self, name: str, value: float, tags: dict[str, str] | None = None) -> None:
        print(f"metric: {name}={value}")

    def start_trace(self, name: str, metadata: dict[str, Any] | None = None) -> str:
        return f"trace-{name}"

    def end_trace(self, trace_id: str, metadata: dict[str, Any] | None = None) -> None:
        print(f"trace end: {trace_id}")


async def main() -> None:
    memory, guard, observe = InMemoryStore(), AllowAllFilter(), PrintObserver()
    # The services behave as their Ports promise, with no agent loop needed.
    observe.log_event(EventType.AGENT_STEP, {"step": 1})
    print("guard policies:", guard.get_policies())
    print("memory hits for 'x':", memory.retrieve("x"))

    agent = skye.agent(REACT, memory=memory, guard=guard, observe=observe)
    assert isinstance(agent, Runnable)
    print("Agent constructed with memory/guard/observe wiring; the loop ships with the future agents spec.")


if __name__ == "__main__":
    asyncio.run(main())
