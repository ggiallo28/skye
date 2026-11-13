# O80
"""The A2A client of ``a2a``. SKELETON: every method raises ``NotImplementedError``."""

from __future__ import annotations

from typing import Any


class A2AClient:
    """An A2A client (official SDK, imported inside the methods once written). Not implemented."""

    def __init__(self, target: str, **config: Any) -> None:
        self.target = target
        self.config = config

    async def describe(self) -> dict[str, Any]:
        """The agent card of the remote agent."""
        raise NotImplementedError("a2a is a skeleton")

    async def send_message(self, text: str, **options: Any) -> dict[str, Any]:
        """Send a message to the remote agent and return its task or reply."""
        raise NotImplementedError("a2a is a skeleton")

    async def get_task(self, task_id: str) -> dict[str, Any]:
        """The state of a task."""
        raise NotImplementedError("a2a is a skeleton")

    async def cancel_task(self, task_id: str) -> dict[str, Any]:
        """Ask the remote agent to cancel a task."""
        raise NotImplementedError("a2a is a skeleton")
