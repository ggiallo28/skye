"""Capability call and result models for capability execution.

This module provides validated dataclasses for representing capability calls from LLMs
and the results of executing those capability calls.
"""

from typing import TYPE_CHECKING, Any

from skye.base.completion import CapabilityCall
from skye.base.validated import Validated, field, validated

if TYPE_CHECKING:
    from skye.base.messages import CapabilityMessage

__all__ = [
    "CapabilityCall",
    "CapabilityResult",
]


@validated
class CapabilityResult(Validated):
    """Represents the result of executing a capability call.

    After a capability is executed, the result is wrapped in this model
    to be returned to the LLM. It includes the original capability call ID,
    the execution result, and any error information if execution failed.

    Attributes:
        capability_call_id: ID of the capability call this result corresponds to
        name: Name of the capability that was executed
        result: The return value from executing the capability
        error: Error message if execution failed, None if successful

    Example:
        >>> result = CapabilityResult(
        ...     capability_call_id="call_123",
        ...     name="weather_get_current",
        ...     result={"temperature": 72, "condition": "sunny"}
        ... )

        >>> error_result = CapabilityResult(
        ...     capability_call_id="call_124",
        ...     name="weather_get_current",
        ...     result=None,
        ...     error="Location not found"
        ... )
    """

    capability_call_id: str = field(
        description="ID of the capability call this result corresponds to",
    )
    name: str = field(
        description="Name of the capability that was executed",
    )
    result: Any = field(
        default=None,
        description="The return value from executing the capability",
    )
    error: str | None = field(
        default=None,
        description="Error message if execution failed, None if successful",
    )

    def to_message(self) -> "CapabilityMessage":
        """Convert the capability result to a CapabilityMessage for conversation continuation.

        Returns:
            CapabilityMessage containing the result or error.

        Example:
            >>> result = CapabilityResult(
            ...     capability_call_id="call_123",
            ...     name="get_weather",
            ...     result={"temperature": 72, "condition": "sunny"}
            ... )
            >>> msg = result.to_message()
            >>> msg.role
            'capability'
            >>> msg.capability_name
            'get_weather'
        """
        from skye.base.capability_execution import format_capability_result
        from skye.base.messages import CapabilityMessage, CapabilityStatus

        # The same text and the same status as every other execution path
        if self.error:
            content, status = f"Error: {self.error}", CapabilityStatus.ERROR
        else:
            content, status = format_capability_result(self.result), CapabilityStatus.OK

        return CapabilityMessage(
            content=content,
            capability_id=self.capability_call_id,
            capability_name=self.name,
            status=status,
        )
