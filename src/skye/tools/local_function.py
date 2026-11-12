"""Local function capability implementation.

This module provides the LocalFunctionCapability class for wrapping Python
functions as capabilities that can be invoked by LLMs.
"""

import asyncio
import copy
import dataclasses
import inspect
import logging
import re
import types
import typing
from collections.abc import Callable
from functools import partial
from typing import Any, Literal, Union

from skye.base.interfaces.capability import CapabilityInterface, CapabilitySchema
from skye.tools.exceptions import CapabilityValidationError

logger = logging.getLogger(__name__)


class LocalFunctionCapability(CapabilityInterface):
    """Capability wrapping a local Python function.

    Automatically extracts schema from function signature and type hints.
    Supports both synchronous and asynchronous functions. Validates arguments
    against the schema before execution.

    Type hints map to JSON Schema: ``list[X]``, ``set[X]`` and ``tuple[X, ...]`` are arrays of
    ``X``, ``tuple[X, Y]`` is an array with ``prefixItems``, ``dict[str, X]`` is an object whose
    values are ``X``, ``X | None`` (``Optional[X]``) is ``X`` and not required, any other union is
    ``anyOf`` and ``Literal[...]`` is ``enum``. The description of each parameter comes from the
    Google-style ``Args:`` section of the docstring. Logs carry the capability name and the
    outcome, never the call arguments (they may hold personal data).

    On a method of a class the capability is a descriptor: read through an instance it is bound to that
    instance (``self`` is not part of the schema), see :meth:`__get__`.

    Attributes:
        func: The wrapped Python function
        name: The capability name (defaults to function name)
        description: The capability description (defaults to function docstring)

    Example:
        >>> def get_weather(location: str) -> str:
        ...     '''Get weather for a location.'''
        ...     return f"Weather for {location}"
        >>>
        >>> capability = LocalFunctionCapability(get_weather)
        >>> schema = capability.get_schema()
        >>> result = capability.execute(location="New York")
        >>> # For async functions:
        >>> async def async_get_weather(location: str) -> str:
        ...     '''Get weather asynchronously.'''
        ...     return f"Weather for {location}"
        >>>
        >>> async_capability = LocalFunctionCapability(async_get_weather)
        >>> result = await async_capability.aexecute(location="New York")
    """

    def __init__(
        self,
        func: Callable[..., Any],
        name: str | None = None,
        description: str | None = None,
        schema_override: CapabilitySchema | None = None,
        return_direct: bool = False,
    ) -> None:
        """Initialize LocalFunctionCapability.

        Args:
            func: The Python function to wrap as a capability
            name: Optional override for capability name (defaults to function name)
            description: Optional override for capability description
                (defaults to first line of function docstring)
            schema_override: Optional complete schema override. If provided,
                this schema will be used instead of extracting from the function.
            return_direct: ``True`` when the result of this capability is the answer of the agent and the
                model is not asked again (Requirement 62.3). The default is ``False``. It is only stored
                and put on the schema: the loop that uses it is the agents spec. With a
                ``schema_override`` the flag is ``True`` when either the argument or the override says so.

        Raises:
            CapabilityValidationError: If func is not callable, or ``return_direct`` is not a bool
        """
        if not callable(func):
            raise CapabilityValidationError(
                f"func must be callable, got {type(func).__name__}",
                capability_name=name or "<unknown>",
            )

        if not isinstance(return_direct, bool):
            raise CapabilityValidationError(
                f"return_direct must be a bool, got {type(return_direct).__name__}",
                capability_name=name or getattr(func, "__name__", "<unknown>"),
            )
        self.func = func
        self._return_direct = return_direct
        # With a schema override the capability is known by the overridden name, errors included
        self._name = schema_override.name if schema_override else (name or func.__name__)
        self._description = description or self._extract_docstring(func)
        self._schema_override = schema_override
        self._is_async = inspect.iscoroutinefunction(func)

    def __get__(
        self, instance: object | None, owner: type | None = None
    ) -> "LocalFunctionCapability":
        """Bind the capability to the object it is read from, so that ``@capability`` works on a method.

        Read through the class, or on a function whose first parameter is neither ``self`` nor ``cls``, it is
        this same capability, as before. Read through an instance, a capability whose first parameter is
        ``self`` comes back bound to that instance, and one whose first parameter is ``cls`` is bound to the
        class. The bound capability is a new object on every read, as a bound method is; its schema, its
        parameter descriptions and the validation of the arguments never show ``self`` or ``cls``. A
        ``staticmethod`` that holds a capability is not bound (Python returns what it holds), so a function
        written outside a class and added with ``staticmethod(...)`` stays a free function.

        Args:
            instance: The object the capability is read from, or ``None`` when it is read through the class.
            owner: The class it is read from.

        Returns:
            This capability, or a copy of it bound to ``instance`` (or to its class for ``cls``).
        """
        if instance is None:
            return self
        first = self._first_parameter()
        if first == "self":
            target: object = instance
        elif first == "cls":
            target = owner if owner is not None else type(instance)
        else:
            return self
        bound = copy.copy(self)
        bound.func = types.MethodType(self.func, target)
        return bound

    def _first_parameter(self) -> str | None:
        """The name of the first parameter of the wrapped function, or ``None`` when it has none."""
        try:
            parameters = list(inspect.signature(self.func).parameters)
        except (TypeError, ValueError):
            return None
        return parameters[0] if parameters else None

    def get_schema(self) -> CapabilitySchema:
        """Get the schema for this capability.

        If schema_override was provided during initialization, returns that.
        Otherwise, automatically extracts schema from the function signature
        and type hints.

        Returns:
            CapabilitySchema: The schema definition for this capability

        Raises:
            CapabilityValidationError: If schema extraction fails
        """
        if self._schema_override:
            if self._return_direct and not self._schema_override.return_direct:
                return dataclasses.replace(self._schema_override, return_direct=True)
            return self._schema_override

        try:
            sig = inspect.signature(self.func)
            hints = _type_hints(self.func)
            parameters = self._extract_parameters(sig, hints, _docstring_args(self.func.__doc__))
            returns = self._extract_return_type(sig, hints)

            return CapabilitySchema(
                name=self._name,
                description=self._description or "No description provided",
                parameters=parameters,
                returns=returns,
                return_direct=self._return_direct,
            )
        except Exception as e:
            raise CapabilityValidationError(
                f"Failed to extract schema from function '{self._name}': {e}",
                capability_name=self._name,
                original_error=str(e),
            ) from e

    def execute(self, **kwargs: Any) -> Any:
        """Execute the function synchronously.

        Validates arguments against the schema before execution.

        Args:
            **kwargs: Arguments to pass to the function. Must match the
                parameters defined in the capability schema.

        Returns:
            The function's return value

        Raises:
            CapabilityValidationError: If arguments don't match schema
            CapabilityValidationError: If the function is async
            Exception: Any exception raised by the wrapped function
        """
        if self._is_async:
            raise CapabilityValidationError(
                f"Cannot call async function '{self._name}' synchronously. "
                "Use aexecute() instead.",
                capability_name=self._name,
            )

        # Validate arguments against schema
        self._validate_arguments(kwargs)

        try:
            result = self.func(**kwargs)
            # The arguments are never logged: they may hold personal data
            logger.debug(
                "Local function executed successfully",
                extra={"capability_name": self._name, "outcome": "ok"},
            )
            return result
        except Exception as e:
            logger.error(
                "Local function execution failed",
                extra={
                    "capability_name": self._name,
                    "outcome": "error",
                    "error_type": type(e).__name__,
                },
            )
            raise

    async def aexecute(self, **kwargs: Any) -> Any:
        """Execute the function asynchronously.

        Validates arguments against the schema before execution. Works with
        both async and sync functions (sync functions are run in a thread pool).

        Args:
            **kwargs: Arguments to pass to the function. Must match the
                parameters defined in the capability schema.

        Returns:
            The function's return value

        Raises:
            CapabilityValidationError: If arguments don't match schema
            Exception: Any exception raised by the wrapped function
        """
        # Validate arguments against schema
        self._validate_arguments(kwargs)

        try:
            if self._is_async:
                result = await self.func(**kwargs)
            else:
                # Run sync function in thread pool to avoid blocking
                loop = asyncio.get_event_loop()
                func_with_args = partial(self.func, **kwargs)
                result = await loop.run_in_executor(None, func_with_args)

            logger.debug(
                "Local function executed successfully (async)",
                extra={"capability_name": self._name, "outcome": "ok"},
            )
            return result
        except Exception as e:
            logger.error(
                "Local function execution failed (async)",
                extra={
                    "capability_name": self._name,
                    "outcome": "error",
                    "error_type": type(e).__name__,
                },
            )
            raise

    def _validate_arguments(self, kwargs: dict[str, Any]) -> None:
        """Validate arguments against the capability schema.

        Args:
            kwargs: Arguments to validate

        Raises:
            CapabilityValidationError: If arguments don't match schema
        """
        schema = self.get_schema()
        required_params = schema.parameters.get("required", [])
        properties = schema.parameters.get("properties", {})

        # Check for missing required parameters
        for param in required_params:
            if param not in kwargs:
                raise CapabilityValidationError(
                    f"Missing required parameter '{param}' for capability '{self._name}'",
                    capability_name=self._name,
                    missing_parameter=param,
                )

        # Check for unexpected parameters
        for param in kwargs:
            if param not in properties:
                raise CapabilityValidationError(
                    f"Unexpected parameter '{param}' for capability '{self._name}'",
                    capability_name=self._name,
                    unexpected_parameter=param,
                )

    @staticmethod
    def _extract_docstring(func: Callable[..., Any]) -> str:
        """Extract first line of docstring from function.

        Args:
            func: The function to extract docstring from

        Returns:
            First line of docstring, or empty string if no docstring
        """
        if func.__doc__:
            return func.__doc__.split("\n")[0].strip()
        return ""

    @staticmethod
    def _extract_parameters(
        sig: inspect.Signature,
        hints: dict[str, Any] | None = None,
        descriptions: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Extract parameters from function signature.

        Converts function parameters to JSON Schema format, handling type hints,
        default values and the descriptions of the docstring's ``Args:`` section.
        A parameter with a default, or typed ``X | None``, is not required.

        Args:
            sig: The function signature
            hints: Resolved type hints by parameter name (string annotations resolved)
            descriptions: Parameter descriptions by name, from the ``Args:`` section

        Returns:
            JSON Schema for parameters
        """
        hints = hints or {}
        descriptions = descriptions or {}
        properties: dict[str, Any] = {}
        required: list[str] = []

        for param_name, param in sig.parameters.items():
            # Skip self and cls parameters
            if param_name in ("self", "cls"):
                continue

            annotation = hints.get(param_name, param.annotation)
            optional = False
            if annotation is inspect.Parameter.empty:
                prop: dict[str, Any] = {"type": "string"}
            else:
                annotation, optional = _strip_optional(annotation)
                prop = _type_to_json_schema(annotation)

            if param_name in descriptions:
                prop = {**prop, "description": descriptions[param_name]}
            properties[param_name] = prop

            # Required: no default and not Optional
            if param.default is inspect.Parameter.empty and not optional:
                required.append(param_name)

        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }

    @staticmethod
    def _extract_return_type(
        sig: inspect.Signature, hints: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Extract return type from function signature.

        Converts return type annotation to JSON Schema format.

        Args:
            sig: The function signature
            hints: Resolved type hints (the ``return`` key holds the return type)

        Returns:
            JSON Schema for return type
        """
        annotation = (hints or {}).get("return", sig.return_annotation)
        if annotation is inspect.Signature.empty:
            return {"type": "string"}

        return _type_to_json_schema(annotation)


_PRIMITIVES: dict[Any, str] = {str: "string", int: "integer", float: "number", bool: "boolean"}
_ARG_LINE = re.compile(r"^(\*{0,2}\w+)\s*(?:\([^)]*\))?\s*:\s*(.*)$")


def _type_hints(func: Callable[..., Any]) -> dict[str, Any]:
    """The resolved type hints of ``func``, or an empty dict when they cannot be resolved."""
    try:
        return typing.get_type_hints(func)
    except Exception:
        return {}


def _is_union(python_type: Any) -> bool:
    return typing.get_origin(python_type) in (Union, types.UnionType)


def _strip_optional(python_type: Any) -> tuple[Any, bool]:
    """Remove ``None`` from a union: ``(X, True)`` for ``X | None``, ``(T, False)`` otherwise."""
    if not _is_union(python_type):
        return python_type, False
    args = [arg for arg in typing.get_args(python_type) if arg is not type(None)]
    if len(args) == len(typing.get_args(python_type)):
        return python_type, False
    if len(args) == 1:
        return args[0], True
    return Union[tuple(args)], True  # noqa: UP007 - built at run time from a tuple


def _docstring_args(doc: str | None) -> dict[str, str]:
    """Parameter descriptions from the Google-style ``Args:`` section of a docstring.

    A description may continue on more indented lines; it ends at the next parameter or at the next
    section (``Returns:``, ``Raises:``), which is not indented.

    Args:
        doc: The docstring, or ``None``.

    Returns:
        The description of each documented parameter, by name (``*args`` is ``args``).
    """
    if not doc:
        return {}
    lines = inspect.cleandoc(doc).splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() in ("Args:", "Arguments:"))
    except StopIteration:
        return {}

    descriptions: dict[str, str] = {}
    current: str | None = None
    entry_indent: int | None = None
    for line in lines[start + 1 :]:
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if entry_indent is None:
            entry_indent = indent
        if indent == 0 or indent < entry_indent:
            break
        match = _ARG_LINE.match(line.strip()) if indent == entry_indent else None
        if match:
            current = match.group(1).lstrip("*")
            descriptions[current] = match.group(2).strip()
        elif current is not None:
            descriptions[current] = f"{descriptions[current]} {line.strip()}".strip()
    return {name: text for name, text in descriptions.items() if text}


def _type_to_json_schema(python_type: Any) -> dict[str, Any]:
    """Convert Python type to JSON Schema.

    Handles basic types, nested generic types (``list[X]``, ``set[X]``, ``tuple``,
    ``dict[str, X]``), unions (``X | None`` is ``X``; others are ``anyOf``) and
    ``Literal`` (``enum``). Falls back to string type for unknown types.

    Args:
        python_type: The Python type to convert

    Returns:
        JSON Schema representation of the type
    """
    # Handle None/NoneType
    if python_type is None or python_type is type(None):
        return {"type": "null"}

    if python_type is Any:
        return {}

    # Handle basic types
    if python_type in _PRIMITIVES:
        return {"type": _PRIMITIVES[python_type]}

    origin = typing.get_origin(python_type)
    args = typing.get_args(python_type)

    if _is_union(python_type):
        inner, _ = _strip_optional(python_type)
        if not _is_union(inner):
            return _type_to_json_schema(inner)
        return {"anyOf": [_type_to_json_schema(arg) for arg in typing.get_args(inner)]}

    if origin is Literal:
        values = list(args)
        kinds = {_PRIMITIVES.get(type(value)) for value in values}
        schema: dict[str, Any] = {"enum": values}
        if len(kinds) == 1 and None not in kinds:
            schema = {"type": kinds.pop(), "enum": values}
        return schema

    # Handle list, set and frozenset
    if python_type in (list, set, frozenset) or origin in (list, set, frozenset):
        items = _type_to_json_schema(args[0]) if args else {"type": "string"}
        schema = {"type": "array", "items": items}
        if origin in (set, frozenset) or python_type in (set, frozenset):
            schema["uniqueItems"] = True
        return schema

    # Handle tuple: tuple[X, ...] is a list of X, tuple[X, Y] has one schema per position
    if python_type is tuple or origin is tuple:
        if not args:
            return {"type": "array"}
        if len(args) == 2 and args[1] is Ellipsis:
            return {"type": "array", "items": _type_to_json_schema(args[0])}
        return {
            "type": "array",
            "prefixItems": [_type_to_json_schema(arg) for arg in args],
            "minItems": len(args),
            "maxItems": len(args),
        }

    # Handle dict
    if python_type is dict or origin is dict:
        if len(args) == 2 and args[1] is not Any:
            return {"type": "object", "additionalProperties": _type_to_json_schema(args[1])}
        return {"type": "object"}

    # Default to string for unknown types
    return {"type": "string"}
