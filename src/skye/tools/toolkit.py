"""``Toolkit``: a named set of tools that an agent takes apart from its own (Requirement 62.5, D111).

A toolkit is a class that extends ``Toolkit``. Its methods carry the ``@capability`` that a free function carries; the toolkit
collects them, gives each the prefix ``<toolkit name>.<name>`` and runs a call by that name. It is a ``ToolProvider``
(the Port in ``base``), so an agent takes it wherever it takes a provider of tools.

The name of a tool is the name of its capability (the method name, or the ``name=`` of the decorator). The prefix is the
``alias`` when there is one, else the ``toolkit_name`` (the name the toolkit is registered or built with), else the class
name in lower case without a trailing ``Toolkit`` (``JiraToolkit`` is ``jira``). Both ``toolkit_name`` and ``alias`` are plain
attributes: the builder ``skye.toolkit(name, **options)`` sets them after it builds the object, and a toolkit built twice
(two Jira servers) takes an ``alias`` for each. A subclass needs no call to ``super().__init__``.

Functions written outside the class join a toolkit through ``tools=[...]`` in the registration (``@plugins.toolkit("jira",
tools=[slugify])``, or with no class: ``plugins.toolkit("text", tools=[slugify])``). The registrar keeps them beside the target
and :func:`build_toolkit` adds them to the object it builds, so a toolkit made by hand does not have them. A target that is a
function returning a ``CapabilityRegistry`` (or any ``ToolProvider``) is wrapped, and the names of its tools get the prefix too.
A tool that a method and a listed function (or two listed functions) give with one prefixed name raises ``ConfigurationError``
naming both.

A ``staticmethod`` that holds a capability is a tool as well: a function written outside the class and added with
``staticmethod(function)`` is a tool with no ``self``. The collected tools are bound to the instance when they are first
needed, so two instances of one class keep their own state.

Example:
    >>> import asyncio
    >>> from skye.tools import Toolkit, capability
    >>> class JiraToolkit(Toolkit):
    ...     @capability
    ...     def create_issue(self, title: str) -> str:
    ...         '''Create an issue and return its key.'''
    ...         return "PROJ-1"
    >>> [schema.name for schema in asyncio.run(JiraToolkit().list_schemas())]
    ['jira.create_issue']

Raises: ``ConfigurationError`` at construction when two tools of one toolkit end with the same prefixed name (the error names both
    attributes); ``run`` never raises for a failing call, it returns a ``CapabilityMessage`` whose status is ``error``.
Missing: a toolkit with no tool lists no schema; a call to an unknown name is an ``error`` message; ``close`` does nothing unless
    the subclass overrides it.
Concurrency: the tools of an instance are bound once and then only read, so several tasks may call ``run`` at once; what a method
    does with the state of its object is the subclass's concern.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from typing import Any

from skye.base.capability_execution import arun_capability_call
from skye.base.completion import CapabilityCall
from skye.base.exceptions import ConfigurationError
from skye.base.interfaces.capability import CapabilitySchema
from skye.base.interfaces.tool_provider import CapabilityContext
from skye.base.messages import CapabilityMessage
from skye.base.plugins import Registrar, get_registrar
from skye.tools.local_function import LocalFunctionCapability

_SUFFIX = "Toolkit"


def _capability_of(raw: object) -> LocalFunctionCapability | None:
    """The capability that a class attribute holds, directly or inside a ``staticmethod``, else ``None``."""
    if isinstance(raw, LocalFunctionCapability):
        return raw
    if isinstance(raw, staticmethod) and isinstance(raw.__func__, LocalFunctionCapability):
        return raw.__func__
    return None


def _tool_attributes(cls: type) -> dict[str, LocalFunctionCapability]:
    """The attributes of ``cls`` (and its bases) that hold a capability, by attribute name; an override that holds none removes it."""
    found: dict[str, LocalFunctionCapability] = {}
    for klass in reversed(cls.__mro__):
        for attribute, raw in vars(klass).items():
            capability = _capability_of(raw)
            if capability is not None:
                found[attribute] = capability
            else:
                found.pop(attribute, None)
    return found


class Toolkit:
    """A named set of tools: the methods of the subclass marked with ``@capability``, each named ``<toolkit>.<name>``.

    Attributes:
        toolkit_name: The name the toolkit is registered or built with; ``None`` until a builder sets it.
        alias: Replaces ``toolkit_name`` in the prefix when one toolkit is built twice; ``None`` by default.
    """

    toolkit_name: str | None = None
    alias: str | None = None

    def __new__(cls, *args: Any, **kwargs: Any) -> Toolkit:
        # The check is here, and not in an ``__init__``, so that it holds for a subclass that does not call ``super().__init__``.
        owners: dict[str, str] = {}
        for attribute, capability in _tool_attributes(cls).items():
            name = capability.get_schema().name
            if name in owners:
                raise ConfigurationError(
                    f"{cls.__name__}: the attributes '{owners[name]}' and '{attribute}' are both the tool '{name}'; "
                    "give one of them another name with @capability(name=...)"
                )
            owners[name] = attribute
        return super().__new__(cls)

    def _prefix(self) -> str:
        """The prefix of the tools: the alias, else the toolkit name, else the class name without ``Toolkit``."""
        if self.alias:
            return self.alias
        if self.toolkit_name:
            return self.toolkit_name
        name = type(self).__name__
        if name.endswith(_SUFFIX) and name != _SUFFIX:
            name = name[: -len(_SUFFIX)]
        return name.lower()

    def _tools(self) -> dict[str, tuple[Any, CapabilitySchema]]:
        """The tools by prefixed name, bound to this instance; built on first use and again if the prefix changed."""
        prefix = self._prefix()
        cached: tuple[str, dict[str, tuple[Any, CapabilitySchema]]] | None = self.__dict__.get(
            "_skye_tools"
        )
        if cached is not None and cached[0] == prefix:
            return cached[1]
        table: dict[str, tuple[Any, CapabilitySchema]] = {}
        for attribute in _tool_attributes(type(self)):
            bound = getattr(
                self, attribute
            )  # the descriptor binds it; a staticmethod gives the capability itself
            schema = bound.get_schema()
            name = f"{prefix}.{schema.name}"
            table[name] = (bound, dataclasses.replace(schema, name=name))
        for _label, held in self.__dict__.get("_skye_extra", ()):
            schema = held.get_schema()
            name = f"{prefix}.{schema.name}"
            table[name] = (held, dataclasses.replace(schema, name=name))
        self.__dict__["_skye_tools"] = (prefix, table)
        return table

    def _add_tools(self, tools: Sequence[Any]) -> None:
        """Add capabilities written outside the class (the ``tools=`` of the registration); the builder calls this once.

        Raises:
            ConfigurationError: A listed function has the name of a method of the class or of another listed function (the error names both).
        """
        owners: dict[str, str] = {
            capability.get_schema().name: f"the attribute '{attribute}'"
            for attribute, capability in _tool_attributes(type(self)).items()
        }
        extra: list[tuple[str, Any]] = list(self.__dict__.get("_skye_extra", ()))
        for label, held in extra:
            owners[held.get_schema().name] = f"the listed function '{label}'"
        for held in tools:
            name = held.get_schema().name
            label = getattr(getattr(held, "func", held), "__name__", name)
            if name in owners:
                raise ConfigurationError(
                    f"{type(self).__name__}: {owners[name]} and the listed function '{label}' are both the tool '{name}'; "
                    "give one of them another name with @capability(name=...)"
                )
            owners[name] = f"the listed function '{label}'"
            extra.append((label, held))
        self.__dict__["_skye_extra"] = tuple(extra)
        self.__dict__.pop("_skye_tools", None)  # the table is built again with the new tools

    async def list_schemas(self, operation: str | None = None) -> list[CapabilitySchema]:
        """The schemas of every tool, with the prefixed names, in name order; ``operation`` selects nothing."""
        table = self._tools()
        return [table[name][1] for name in sorted(table)]

    async def run(
        self, call: CapabilityCall, context: CapabilityContext | None = None
    ) -> CapabilityMessage:
        """Run one call by its prefixed name and say how it ended; never raises, an unknown name is an ``error`` message."""
        entry = self._tools().get(call.name)
        return await arun_capability_call(
            entry[0] if entry else None, call.id, call.name, call.arguments
        )

    async def close(self) -> None:
        """Release what the toolkit holds; a subclass that holds a connection overrides this."""
        return None


class ToolSet(Toolkit):
    """A toolkit with no tool of its own: its tools are the ``tools=`` of the registration (``plugins.toolkit("text", tools=[...])``)."""


class _ProviderToolkit(Toolkit):
    """A ``ToolProvider`` (a ``CapabilityRegistry`` returned by the function of a toolkit) that takes the prefix of the toolkit."""

    def __init__(self, provider: Any) -> None:
        self._provider = provider

    def _check_clash(self) -> None:
        """Name the clash of a listed function with a tool of the provider when the provider can say its names at once."""
        names = getattr(self._provider, "list_all", None)
        if not callable(names):
            return
        taken = set(names())
        for _label, held in self.__dict__.get("_skye_extra", ()):
            name = held.get_schema().name
            if name in taken:
                raise ConfigurationError(
                    f"{type(self).__name__}: the tool '{name}' of the registry and the listed function '{_label}' have one name; "
                    "give one of them another name with @capability(name=...)"
                )

    async def list_schemas(self, operation: str | None = None) -> list[CapabilitySchema]:
        own = await Toolkit.list_schemas(self, operation)
        prefix = self._prefix()
        seen = {schema.name for schema in own}
        schemas = list(own)
        for schema in await self._provider.list_schemas(operation):
            name = f"{prefix}.{schema.name}"
            if name in seen:
                raise ConfigurationError(
                    f"{type(self).__name__}: the tool '{schema.name}' of the registry and a listed function have one name '{name}'"
                )
            seen.add(name)
            schemas.append(dataclasses.replace(schema, name=name))
        return sorted(schemas, key=lambda schema: schema.name)

    async def run(
        self, call: CapabilityCall, context: CapabilityContext | None = None
    ) -> CapabilityMessage:
        prefix = f"{self._prefix()}."
        if call.name not in self._tools() and call.name.startswith(prefix):
            inner = dataclasses.replace(call, name=call.name[len(prefix) :])
            message: CapabilityMessage = await self._provider.run(inner, context)
            return dataclasses.replace(message, capability_name=call.name)
        return await Toolkit.run(self, call, context)

    async def close(self) -> None:
        await self._provider.close()


def _is_tool_provider(obj: Any) -> bool:
    return all(callable(getattr(obj, method, None)) for method in ("list_schemas", "run", "close"))


def build_toolkit(name: str, registrar: Registrar | None = None, **options: Any) -> Toolkit:
    """Build the toolkit registered under ``name``: the one place where a registration becomes a ``Toolkit`` object.

    The target is a ``Toolkit`` class, or a function (a factory) that returns a ``Toolkit`` or a ``ToolProvider`` such as a
    ``CapabilityRegistry``; ``options`` go to it as keyword arguments. The result is a ``Toolkit`` whose ``toolkit_name`` is ``name``
    unless the class set one, with the ``tools=`` of the registration added. A registration made with ``tools=`` and no class builds a
    :class:`ToolSet`. The builder ``skye.toolkit(name, **options)`` calls this and sets the ``alias``.

    Args:
        name: The registered name of the toolkit.
        registrar: The registrar to read; the default registrar of the process when omitted.
        **options: Keyword arguments for the class or the function.

    Returns:
        A ``Toolkit``, ready to be given to an agent as a ``ToolProvider``.

    Raises:
        ConfigurationError: The name is not registered; the target builds something that is neither a ``Toolkit`` nor a ``ToolProvider``;
            or two tools end with one prefixed name (the error names both).
    """
    source = registrar if registrar is not None else get_registrar()
    target = source.get("toolkit", name)
    built = target(**options) if callable(target) else _no_options(name, target, options)
    if isinstance(built, Toolkit):
        toolkit = built
    elif _is_tool_provider(built):
        toolkit = _ProviderToolkit(built)
    else:
        raise ConfigurationError(
            f"the toolkit {name!r} built {type(built).__name__}, which is neither a Toolkit nor a ToolProvider",
            {"kind": "toolkit", "name": name},
        )
    if toolkit.toolkit_name is None:
        toolkit.toolkit_name = name
    extra = source.toolkit_tools(name)
    if extra:
        toolkit._add_tools(extra)
    if isinstance(toolkit, _ProviderToolkit):
        toolkit._check_clash()
    return toolkit


def _no_options(name: str, target: Any, options: dict[str, Any]) -> Any:
    """A toolkit registered as an object (not a class or a function) is used as it is; options have nothing to go to."""
    if options:
        raise ConfigurationError(
            f"the toolkit {name!r} is registered as an object, which takes no options; got {sorted(options)}",
            {"kind": "toolkit", "name": name},
        )
    return target


__all__ = ["Toolkit"]
