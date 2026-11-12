"""The ReAct agent type (stub, no agent loop): the placeholder that ships today.

Satisfies the ``Runnable`` Port so the boundary is in place. The real implementation is deferred to the future ``agents`` spec.

Raises: ``NotImplementedError`` from ``invoke``: the loop is not written yet.
Missing: not applicable.
Concurrency: an instance holds only its options; safe to share.
"""

from typing import Any


class ReActAgent:
    """Placeholder for the ReAct agent type (stub, no agent loop)."""

    def __init__(self, **options: Any) -> None:
        self.options = options

    async def invoke(self, input: Any) -> Any:
        """Not implemented: the ReAct loop belongs to the future agents spec."""
        raise NotImplementedError(
            "ReActAgent is a placeholder; the agent loop is not implemented yet"
        )

    async def ainvoke(self, input: Any) -> Any:
        """A thin alias of :meth:`invoke`."""
        return await self.invoke(input)
