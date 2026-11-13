"""Capability interface for capabilities and functions.

This module defines the abstract interface for capabilities (functions)
that agents can invoke. It includes schema definition for LLM function calling.

Example:
    >>> from skye.base.interfaces.capability import CapabilityInterface, CapabilitySchema
    >>>
    >>> class WeatherCapability(CapabilityInterface):
    ...     def get_schema(self) -> CapabilitySchema:
    ...         return CapabilitySchema(
    ...             name="get_weather",
    ...             description="Get current weather for a city",
    ...             parameters={"city": {"type": "string"}},
    ...             returns={"type": "object"}
    ...         )

Raises: CapabilityExecutionError when the capability fails, ValidationError when the arguments do not match the schema.
Missing: not applicable (a capability returns its own result; absence of a capability is the registry's concern).
Concurrency: ``execute`` is called from the calling thread, ``aexecute`` from the event loop; an implementation must not assume it is called once at a time.
"""

import dataclasses
from abc import ABC, abstractmethod
from typing import Any

from skye.base.exceptions import ValidationError
from skye.base.validated import Validated, field, validated


# Requirement 62.3
@validated(frozen=True)
class CapabilitySchema(Validated):
    """Schema defining a capability's signature.

    This model describes the capability's interface for LLM function calling,
    including its name, description, parameters, and return type. It is frozen; the name and
    the description are stripped and must not be blank. This is the only ``CapabilitySchema``:
    ``skye.tools`` re-exports it.

    Attributes:
        name: Unique name of the capability.
        description: Human-readable description of what the capability does.
        parameters: JSON Schema describing the capability's parameters.
        returns: JSON Schema describing the capability's return value.
        return_direct: ``True`` when the result of the capability is the answer of the agent and the model
            is not asked again. It is a flag for the agent, read through the
            ``ToolProvider`` Port; no adapter sends it to a model. It must be a ``bool``.

    Example:
        >>> schema = CapabilitySchema(
        ...     name="calculate",
        ...     description="Perform arithmetic calculation",
        ...     parameters={
        ...         "type": "object",
        ...         "properties": {
        ...             "operation": {"type": "string", "enum": ["add", "subtract"]},
        ...             "a": {"type": "number"},
        ...             "b": {"type": "number"}
        ...         },
        ...         "required": ["operation", "a", "b"]
        ...     },
        ...     returns={"type": "number"}
        ... )
        >>> schema.name
        'calculate'
    """

    name: str = field(min_length=1)
    description: str = field(min_length=1)
    parameters: dict[str, Any] = field(default_factory=dict)
    returns: dict[str, Any] = field(default_factory=dict)
    return_direct: bool = False

    def __post_init__(self) -> None:
        """Validate the fields, then strip the name and the description, which must not be blank."""
        if not isinstance(self.return_direct, bool):
            raise ValidationError(
                "return_direct must be a bool", field="return_direct", value=self.return_direct
            )
        try:
            super().__post_init__()
        except dataclasses.FrozenInstanceError as error:
            raise ValidationError(
                "parameters and returns must be dicts with string keys",
                field="parameters",
                value=None,
            ) from error
        for field_name in ("name", "description"):
            value = getattr(self, field_name)
            if not value.strip():
                raise ValidationError(
                    f"{field_name} cannot be empty or whitespace", field=field_name, value=value
                )
            object.__setattr__(self, field_name, value.strip())


class CapabilityInterface(ABC):
    """Abstract interface for agent capabilities.

    This interface defines the contract for executable capabilities that extend
    agent functionality. Capabilities can be synchronous or asynchronous and
    provide schema information for LLM function calling.

    Example:
        >>> class CalculatorCapability(CapabilityInterface):
        ...     def get_schema(self) -> CapabilitySchema:
        ...         return CapabilitySchema(
        ...             name="calculator",
        ...             description="Perform calculations",
        ...             parameters={"expression": {"type": "string"}},
        ...             returns={"type": "number"}
        ...         )
        ...
        ...     def execute(self, **kwargs) -> Any:
        ...         expression = kwargs.get("expression", "")
        ...         return eval(expression)  # Note: eval is unsafe, just for example
        ...
        ...     async def aexecute(self, **kwargs) -> Any:
        ...         return self.execute(**kwargs)
    """

    @abstractmethod
    def get_schema(self) -> CapabilitySchema:
        """Return the capability's schema for LLM function calling.

        Returns:
            CapabilitySchema describing the capability's interface.

        Example:
            >>> capability = MyCapability()
            >>> schema = capability.get_schema()
            >>> schema.name
            'my_capability'
        """
        pass

    @abstractmethod
    def execute(self, **kwargs: Any) -> Any:
        """Execute the capability with provided arguments.

        Args:
            **kwargs: Keyword arguments matching the capability's parameter schema.

        Returns:
            The result of executing the capability.

        Raises:
            CapabilityExecutionError: If execution fails.
            ValidationError: If arguments don't match the schema.

        Example:
            >>> capability = MyCapability()
            >>> result = capability.execute(param1="value1", param2=42)
            >>> print(result)
        """
        pass

    @abstractmethod
    async def aexecute(self, **kwargs: Any) -> Any:
        """Execute the capability asynchronously.

        Args:
            **kwargs: Keyword arguments matching the capability's parameter schema.

        Returns:
            The result of executing the capability.

        Raises:
            CapabilityExecutionError: If execution fails.
            ValidationError: If arguments don't match the schema.

        Example:
            >>> capability = MyCapability()
            >>> result = await capability.aexecute(param1="value1", param2=42)
            >>> print(result)
        """
        pass
