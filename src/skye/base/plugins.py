"""The registrar: one in-memory table per kind of integration (Requirement 56, plugins:2.3 to 2.5).

``Registrar`` implements ``RegistrarInterface``: one method per kind, and the owners of each kind read it with ``get(kind, name)`` and
``names(kind)``. There is one default registrar per process (``get_registrar``); a test builds its own ``Registrar()`` and leaves the default
untouched. Nothing is written to a file and no thread is started (D27).

``Plugins`` is how a plugin author adds an integration (D111): ``plugins = skye.Plugins()`` is a handle on the default registrar and holds no
table, so two handles in two modules see one set of registrations. Each kind has one method of it. With the name and the target
(``plugins.provider("acme", Cls, profile=...)``) it registers; with the name only it returns a decorator that registers the class or function
it is put on and returns it unchanged (``@plugins.agent("reverse")``). The registration is made when the call or the decorator runs, wherever
that is in the program. ``Plugins(registrar=...)`` is a handle on a private registrar, for a test.

A target is the object, a factory, or a ``"module:attribute"`` text. A text is imported at the first ``get`` of the name, never at
registration, so registering a built-in costs no import. A name is registered once per kind; a second registration raises unless
``replace=True``. The kind ``provider`` (Requirement 56.12) is keyed by name and function: ``acme`` may be a chat class and an embedding class, and the function
is deduced from the methods of the class (``acomplete`` for a model, ``aencode`` for an embedding, ``decide`` for a decision) or given with
``function=``, which a text target needs because it is not imported at registration. A provider profile is kept by provider name, shared by
every function of that name: a second,
different profile for the same name raises, the same profile given again is accepted.

The default registrar has two more duties, both lazy (Requirement 57.1 to 57.3, 7.8, 7.9; plugins:4.2). The first call that reads or writes
it loads the built-in plugins of the owners, named by the fixed tuple of texts ``BUILTIN_PLUGINS`` and never imported by ``base``; and the
first ``get`` of a name it does not know scans the entry-point group ``skye.plugins`` once (the scan is ``"skye.utils.plugins:discover"``,
imported by text) and looks again. ``import skye`` does neither. A private ``Registrar()`` does neither unless asked with ``scan=True`` and
``builtin_plugins=``.

Raises: ``ConfigurationError`` for an unknown kind or name, a duplicate name, a conflicting profile, an empty name, a missing target,
    a text target that does not import (the cause is kept), a ``provider`` whose function cannot be told or whose class has the methods of two
    functions, and a ``provider`` lookup that omits the function when the name has two.
Missing: ``get`` of an unregistered name raises, listing the names of the kind; ``get_profile`` returns ``None`` for a provider with no profile.
Concurrency: a registration is safe from any thread (Requirement 56.6). A write takes a lock, checks the name and publishes a new copy of
    the table of its kind, so two threads that register one name give one success and one ``ConfigurationError``. A read takes no lock: it
    reads a table that is never changed after it is published, so it never sees a half-written entry. The first read loads the built-in
    plugins and the first unknown name scans the entry points, each once; a thread that needs them while another runs them waits for it.
    The import of a text target is idempotent.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import re
import threading
import dataclasses
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, TypeVar, get_type_hints, overload

from skye.base.exceptions import ConfigurationError
from skye.base.profile import ModelProfile, ProviderProfile

#: The kinds of integration, named as the registrar methods that add them (Requirement 56.2).
KINDS: tuple[str, ...] = (
    "provider",
    "backend",
    "credential_source",
    "routing_strategy",
    "mcp_client",
    "tokenizer",
    "template_filter",
    "agent",
    "toolkit",
)

#: The built-in plugin of each owner, as ``"module:attribute"`` texts, in the order they register. ``base`` never imports them: the default
#: registrar imports each at its first use. An owner whose ``plugins`` package does not exist yet is skipped.
BUILTIN_PLUGINS: tuple[str, ...] = (
    "skye.models.plugins:register",
    "skye.store.plugins:register",
    "skye.auth.plugins:register",
    "skye.router.plugins:register",
    "skye.tools.plugins:register",
    "skye.prompts.plugins:register",
    "skye.agents.plugins:register",
)

#: The scan of the installed plugins, imported by text at the first miss of ``Registrar.get`` (``utils`` does the I/O, ``base`` does not).
DISCOVER = "skye.utils.plugins:discover"
#: The text target of a toolkit that is only a list of tools (``plugins.toolkit("text", tools=[...])``): ``base`` names it and never imports it.
TOOLSET = "skye.tools.toolkit:ToolSet"
PLUGIN_REPORTS = "skye.utils.plugins:plugin_reports"

_LOG = logging.getLogger(__name__)

_TEXT_TARGET = re.compile(r"^[A-Za-z_][\w.]*:[A-Za-z_][\w.]*$")
#: The kind that holds the three functions of a provider in one table, keyed by name and function (Requirement 56.12, task 15.1).
PROVIDER = "provider"

#: What a ``provider`` does. The words are those of ``provider_type=`` of the builder (``"embedding"``, ``"decision"``; the model is the default).
ProviderFunction = Literal["model", "embedding", "decision"]
PROVIDER_FUNCTIONS: tuple[str, ...] = ("model", "embedding", "decision")

#: The methods that say what a class does: a class that has one of them of a function is a provider of that function.
_FUNCTION_METHODS: dict[str, tuple[str, ...]] = {
    "model": ("generate", "complete", "acomplete"),
    "embedding": ("encode", "aencode", "encode_batch", "aencode_batch"),
    "decision": ("decide",),
}


def _functions_of(shape: Any) -> list[str]:
    """The functions of a provider that the methods of ``shape`` (a class or an object) show, in the order of ``PROVIDER_FUNCTIONS``."""
    return [
        function
        for function in PROVIDER_FUNCTIONS
        if any(callable(getattr(shape, method, None)) for method in _FUNCTION_METHODS[function])
    ]


def _returned_class(factory: Any) -> Any | None:
    """The class that a factory function says it returns, or ``None`` when it has no annotation or the annotation is not a plain, non-builtin class."""
    try:
        annotation = get_type_hints(factory).get("return")
    except Exception:  # a forward reference that does not resolve, a builtin without hints
        return None
    # A builtin says nothing about a provider (``str`` has an ``encode``): only a class of a library or of the program counts.
    if isinstance(annotation, type) and annotation.__module__ != "builtins":
        return annotation
    return None


def _shape_of(target: Any) -> Any | None:
    """What shows the methods of a target: a class is its own shape, a factory is the class it returns, any other object is itself."""
    if isinstance(target, type):
        return target
    if inspect.isroutine(target):
        return _returned_class(target)
    return target


def _label(target: Any) -> str:
    return getattr(target, "__qualname__", None) or type(target).__qualname__


def _check_tools(name: str, tools: Sequence[Any] | None) -> tuple[Any, ...] | None:
    """The ``tools=`` of a toolkit as a tuple, or ``None``; each item must be a capability, which is an object with ``get_schema``."""
    if tools is None:
        return None
    if isinstance(tools, (str, bytes)) or not isinstance(tools, Iterable):
        raise ConfigurationError(
            f"tools= of toolkit {name!r} is a list of capabilities (functions with @capability), got {type(tools).__name__}",
            {"kind": "toolkit", "name": name},
        )
    held = tuple(tools)
    for item in held:
        if not callable(getattr(item, "get_schema", None)):
            raise ConfigurationError(
                f"tools= of toolkit {name!r} takes capabilities, and {_label(item)} is not one: write @capability on the function",
                {"kind": "toolkit", "name": name},
            )
    return held


def _check_function(name: str, function: Any) -> None:
    if function not in PROVIDER_FUNCTIONS:
        raise ConfigurationError(
            f"the function of provider {name!r} is {function!r}; it is one of {', '.join(PROVIDER_FUNCTIONS)}",
            {
                "kind": PROVIDER,
                "name": name,
                "function": function,
                "functions": list(PROVIDER_FUNCTIONS),
            },
        )


def _provider_function(name: str, target: Any, function: str | None) -> str:
    """What a provider does, from ``function=`` and the methods of its class (Requirement 56.12).

    A text target is not imported at registration, so it cannot be inspected: ``function=`` is required. For any other target the methods
    say it (``acomplete`` for a model, ``aencode`` for an embedding, ``decide`` for a decision); a factory function is read through the class
    that its return annotation names. ``function=`` is optional then, and a wrong one is an error.
    """
    if function is not None:
        _check_function(name, function)
    if isinstance(target, str):
        if function is None:
            raise ConfigurationError(
                f"provider {name!r} is the text {target!r}, which is not imported now; give function= ({', '.join(PROVIDER_FUNCTIONS)})",
                {"kind": PROVIDER, "name": name, "target": target},
            )
        return function
    shape = _shape_of(target)
    found = _functions_of(shape) if shape is not None else []
    label = _label(shape if shape is not None else target)
    if function is not None:
        if found and function not in found:
            raise ConfigurationError(
                f"provider {name!r} says function={function!r}, but {label} has the methods of {' and '.join(found)}",
                {"kind": PROVIDER, "name": name, "function": function, "found": found},
            )
        return function
    if len(found) == 1:
        return found[0]
    if not found:
        raise ConfigurationError(
            f"cannot tell what provider {name!r} does: {label} has none of the methods acomplete (model), aencode (embedding) or decide "
            "(decision); give function=",
            {"kind": PROVIDER, "name": name},
        )
    raise ConfigurationError(
        f"provider {name!r}: {label} has the methods of two functions, {found[0]} and {found[1]}; give function= to say which one",
        {"kind": PROVIDER, "name": name, "found": found},
    )


@dataclass
class _Entry:
    """A registered target and, once a text has been imported, what it resolved to."""

    target: Any
    resolved: Any = None
    is_resolved: bool = False


class Registrar:
    """The in-memory tables of the registered integrations, one per kind.

    Args:
        scan: Scan the entry-point group ``skye.plugins`` once, at the first ``get`` of a name that is not registered. Off for a private
            registrar; the default registrar turns it on.
        builtin_plugins: ``"module:attribute"`` texts of built-in plugins (functions of one parameter, the registrar), loaded once, before
            the first read or write. Empty for a private registrar; the default registrar passes ``BUILTIN_PLUGINS``.
    """

    def __init__(self, *, scan: bool = False, builtin_plugins: tuple[str, ...] = ()) -> None:
        self._tables: dict[str, dict[Any, _Entry]] = {kind: {} for kind in KINDS}
        self._profiles: dict[str, Any] = {}
        self._toolkit_tools: dict[
            str, tuple[Any, ...]
        ] = {}  # the tools= of each toolkit, published whole like a table
        self._scan = scan
        self._scanned = False  # the scan has finished (read without a lock)
        self._scan_started = False  # the scan has started, or the running thread is inside it (read under _load_lock)
        self._builtin_plugins = tuple(builtin_plugins)
        self._builtins_loaded = False  # the built-ins have been loaded (read without a lock)
        self._builtins_started = (
            False  # loading has started, or the running thread is inside it (read under _load_lock)
        )
        # Two locks, always taken in this order: _load_lock (the first read and the first scan, re-entrant because a built-in or a
        # scanned plugin registers through this registrar), then _write_lock (every registration and removal). A read takes neither
        # after the first read and the first scan.
        self._load_lock = threading.RLock()
        self._write_lock = threading.Lock()

    # -- registration: one method per kind (RegistrarInterface) ------------------------------------------------

    def provider(
        self,
        name: str,
        target: Any,
        *,
        profile: Any | None = None,
        function: ProviderFunction | None = None,
        replace: bool = False,
    ) -> None:
        """Register a provider under ``name`` for one function: a model, an embedding or a decision (Requirement 56.12).

        The function is deduced from the methods of ``target`` (a class, a factory with a return annotation, or an object). A text target is
        not imported now, so it must come with ``function=``; for any other target ``function=`` is optional and a wrong one raises. The same
        name may be registered for two functions (``acme`` as a chat class and an embedding class); the profile is the one of the name.
        """
        self._register(PROVIDER, name, target, replace, profile, function)

    def backend(self, name: str, target: Any, *, replace: bool = False) -> None:
        """Register a storage backend under ``name``."""
        self._register("backend", name, target, replace)

    def credential_source(self, name: str, target: Any, *, replace: bool = False) -> None:
        """Register a credential source under ``name``."""
        self._register("credential_source", name, target, replace)

    def routing_strategy(self, name: str, target: Any, *, replace: bool = False) -> None:
        """Register a routing strategy under ``name``."""
        self._register("routing_strategy", name, target, replace)

    def mcp_client(self, name: str, target: Any, *, replace: bool = False) -> None:
        """Register an MCP client implementation under ``name`` (the ``impl`` of a server)."""
        self._register("mcp_client", name, target, replace)

    def tokenizer(self, name: str, target: Any, *, replace: bool = False) -> None:
        """Register a tokenizer under ``name`` (the name a ``ModelProfile`` refers to)."""
        self._register("tokenizer", name, target, replace)

    def template_filter(self, name: str, target: Any, *, replace: bool = False) -> None:
        """Register a prompt filter in the default set under ``name``."""
        self._register("template_filter", name, target, replace)

    def agent(self, name: str, target: Any, *, replace: bool = False) -> None:
        """Register an agent type under ``name``."""
        self._register("agent", name, target, replace)

    def toolkit(
        self, name: str, target: Any, *, tools: Sequence[Any] | None = None, replace: bool = False
    ) -> None:
        """Register a toolkit under ``name``: a named set of tools that an agent takes apart from its own (Requirement 62.5).

        ``tools`` is a sequence of capabilities (objects made by ``@capability``) that join the toolkit when it is built, with the
        prefix of the toolkit: functions written outside the class. The registrar keeps them beside the target, and the builder of
        ``tools`` reads them with :meth:`toolkit_tools`; ``base`` never imports ``tools``. A new registration under the same name
        with ``replace=True`` replaces them too.
        """
        self._register("toolkit", name, target, replace, tools=_check_tools(name, tools))

    def toolkit_tools(self, name: str) -> tuple[Any, ...]:
        """The ``tools=`` that the toolkit ``name`` was registered with; empty when it had none or is not registered. Reads take no lock."""
        self._ensure_builtins()
        return self._toolkit_tools.get(name, ())

    def _upgrade_toolkit(
        self, name: str, placeholder: str, held_tools: tuple[Any, ...], target: Any
    ) -> None:
        """Give the class ``target`` to a toolkit that was registered as a list of tools only, in the decorator form of ``Plugins.toolkit``.

        The call ``plugins.toolkit("jira", tools=[...])`` registers the list at once, so that it also works with no class; the decorator
        that it returns then puts the class on the same registration. It changes nothing when the registration is no longer the one that
        the call made (another thread or call replaced it), and says so.
        """
        if target is None or (isinstance(target, str) and not _TEXT_TARGET.match(target)):
            raise ConfigurationError(
                f"the target of toolkit {name!r} is missing or is not 'module:attribute'",
                {"kind": "toolkit", "name": name},
            )
        with self._write_lock:
            table = self._tables["toolkit"]
            entry = table.get(name)
            if (
                entry is None
                or entry.target != placeholder
                or self._toolkit_tools.get(name) is not held_tools
            ):
                raise ConfigurationError(
                    f"toolkit {name!r} was registered again between the call and the decorator; pass replace=True to a single registration",
                    {"kind": "toolkit", "name": name},
                )
            published = dict(table)
            published[name] = _Entry(target)
            self._tables["toolkit"] = published

    # -- lookup -----------------------------------------------------------------------------------------------

    def get(self, kind: str, name: str, function: ProviderFunction | None = None) -> Any:
        """The target registered for ``name``; a ``"module:attribute"`` text is imported now, the first time it is asked for.

        ``function=`` is for the kind ``provider`` only: the name may be registered for two functions, and then it says which one. When
        only one function has the name, it may be left out.

        Raises:
            ConfigurationError: The kind or the name is unknown (the error lists the names of the kind), a text target does not import,
                ``function=`` is given for another kind, or a provider name has two functions and none is asked for.
        """
        table = self._table(kind)
        entry = self._find(kind, table, name, function)
        if entry is None and self._scan and not self._scanned:
            self._scan_once()
            table = self._table(kind)  # a write publishes a new table: read it again
            entry = self._find(kind, table, name, function)
        if entry is None:
            known = self._names_in(kind, table, function)
            failures = self._scan_failures()
            for_function = f" for the function {function!r}" if function is not None else ""
            text = f"no {kind} named {name!r}{for_function}; registered: {', '.join(known) if known else 'none'}"
            others = (
                sorted(f for n, f in table if n == name) if kind == PROVIDER and function else []
            )
            if others:  # the name exists, for another function: say so
                text += f"; {name!r} is registered for {' and '.join(others)}"
            if failures:
                text += "; failed in the scan of the entry points: " + ", ".join(
                    f"{entry_point} ({error})" for entry_point, error in failures
                )
            details: dict[str, Any] = {"kind": kind, "name": name, "known": known}
            if function is not None:
                details["function"] = function
            if others:
                details["functions"] = others
            if failures:
                details["failures"] = [{"entry_point": e, "error": err} for e, err in failures]
            raise ConfigurationError(text, details)
        if not entry.is_resolved:
            entry.resolved = (
                _import_text(kind, name, entry.target)
                if isinstance(entry.target, str)
                else entry.target
            )
            entry.is_resolved = True
        return entry.resolved

    def names(self, kind: str, function: ProviderFunction | None = None) -> list[str]:
        """The names registered for ``kind``, sorted. Nothing is imported. For ``provider``, ``function=`` keeps the names of that function."""
        return self._names_in(kind, self._table(kind), function)

    def has(self, kind: str, name: str, function: ProviderFunction | None = None) -> bool:
        """Whether ``name`` is registered for ``kind``. Nothing is imported. For ``provider`` with no ``function=``, for any function."""
        table = self._table(kind)
        if kind != PROVIDER:
            self._reject_function(kind, function)
            return name in table
        if function is not None:
            _check_function(name, function)
            return (name, function) in table
        return any(entry_name == name for entry_name, _ in table)

    def default_set(self, kind: str) -> dict[str, Any]:
        """The names of ``kind`` mapped to what they resolve to: the default set that every new instance of a registry starts with (Requirement 56.8).

        For the kinds held per instance (the filters of a prompt builder). The tools are not one of them: a ``CapabilityRegistry`` starts empty
        and is no view of the registrar. The scan of the installed plugins runs once, because a plugin may register into a default set; the
        built-in plugins are not loaded, because none of them registers a default-set kind, so reading it costs nothing when no plugin is installed. A target that cannot be resolved is skipped with a warning:
        one broken plugin must not break every registry.
        """
        if kind == PROVIDER:
            raise ConfigurationError(
                "a provider has no default set: it is read by name and function", {"kind": kind}
            )
        # No built-in is loaded to say it: an old kind such as ``capability`` fails here as it does in ``get``.
        if kind not in self._tables:
            raise ConfigurationError(
                f"unknown kind {kind!r}; the kinds are {', '.join(KINDS)}",
                {"kind": kind, "kinds": list(KINDS)},
            )
        self._scan_once()
        found: dict[str, Any] = {}
        for name, entry in sorted(self._tables[kind].items()):
            try:
                found[name] = self.get(kind, name)
            except ConfigurationError as exc:
                _LOG.warning("the %s %r is not in the default set: %s", kind, name, exc)
        return found

    def unregister(self, kind: str, name: str, function: ProviderFunction | None = None) -> bool:
        """Remove ``name`` from ``kind``; ``True`` when it was registered. A provider's profile stays: it belongs to the provider name.

        For ``provider``, ``function=`` says which function to remove; it may be left out when only one function has the name.

        Not part of ``RegistrarInterface``: a plugin adds integrations and does not take them away; this is for the owners' registry
        views (``unregister_credential_source``, ``unregister_tokenizer``) and for tests that clean up after themselves.

        Raises:
            ConfigurationError: ``function=`` is given for another kind, or a provider name has two functions and none is given.
        """
        self._table(kind)  # loads the built-ins and checks the kind, before the lock
        with self._write_lock:
            table = self._tables[kind]
            key: Any = name
            if kind == PROVIDER:
                if function is not None:
                    _check_function(name, function)
                    key = (name, function)
                else:
                    found = [entry_key for entry_key in table if entry_key[0] == name]
                    if len(found) > 1:
                        raise self._ambiguous(name, [entry_key[1] for entry_key in found])
                    key = found[0] if found else (name, "")
            else:
                self._reject_function(kind, function)
            if key not in table:
                return False
            published = dict(table)
            del published[key]
            self._tables[kind] = published
            if kind == "toolkit" and name in self._toolkit_tools:
                tools = dict(self._toolkit_tools)
                del tools[name]
                self._toolkit_tools = tools
            return True

    def get_profile(self, provider: str) -> Any | None:
        """The profile registered with the provider ``provider``, or ``None`` when it has none."""
        self._ensure_builtins()
        return self._profiles.get(provider)

    def profile(
        self,
        provider: str,
        models: Mapping[str, Mapping[str, Any] | ModelProfile] | None = None,
        **fields: Any,
    ) -> None:
        """Merge a change into the profile of the provider ``provider`` and change nothing else (Requirement 59.11).

        Args:
            provider: The registered name of a provider that has a profile.
            models: A model name mapped to the change of its entry. A mapping of fields (``{"tokenizer": "words"}``) changes only those
                fields. A ``ModelProfile`` changes the fields that differ from the defaults of the class and keeps the others, so
                ``ModelProfile(tokenizer="words")`` does not erase a price; a field cannot be set back to its default this way, the
                mapping form with the value does it. The ``info`` of a change is merged key by key into the ``info`` of the entry.
                A model the profile does not have is added.
            **fields: A scalar field of the provider profile (``api_key_variables``, ``region``, ``default_api_base``,
                ``client_settings``, ``model_is_deployment``, ``map_error``), checked as the profile constructor checks it.

        Raises:
            ConfigurationError: The provider has no profile (the error lists the providers that have one).
            TypeError: A name in ``fields``, or in the mapping of a model, is not a field; or a model change is neither a mapping nor a
                ``ModelProfile``.
            ValidationError: A given value is not valid for its field.

        The profile is frozen: a new one is built and published under the same name under the write lock, as a table is, so a read
        sees the old profile or the new one and never half of a change, and a call that raises changes nothing.
        """
        self._ensure_builtins()  # before the lock: the built-ins hold the profiles of the providers they own
        with self._write_lock:
            held = self._profiles.get(provider)
            if held is None:
                known = sorted(self._profiles)
                raise ConfigurationError(
                    f"provider {provider!r} has no profile to change; the providers that have one: "
                    f"{', '.join(known) if known else 'none'}",
                    {"provider": provider, "known": known},
                )
            merged = _merge_profile(held, models, fields)
            if merged is held:
                return
            profiles = dict(self._profiles)
            profiles[provider] = merged
            self._profiles = profiles

    def profiles_token(self) -> object:
        """An opaque token that changes whenever a profile is written: keep it with a cache of something read from a profile.

        Compare with ``is``: a cache made when the token was ``t`` is valid while ``profiles_token() is t``. A write publishes a new
        mapping, so the token of a registrar whose profiles were restored by replacing them changes too.
        """
        return self._profiles

    # -- internals --------------------------------------------------------------------------------------------

    @staticmethod
    def _reject_function(kind: str, function: Any) -> None:
        if function is not None:
            raise ConfigurationError(
                f"function= is for the kind {PROVIDER!r} only, not for {kind!r}",
                {"kind": kind, "function": function},
            )

    @staticmethod
    def _ambiguous(name: str, functions: list[str]) -> ConfigurationError:
        return ConfigurationError(
            f"provider {name!r} is registered for {' and '.join(sorted(functions))}; give function= to say which one",
            {"kind": PROVIDER, "name": name, "functions": sorted(functions)},
        )

    def _find(
        self, kind: str, table: dict[Any, _Entry], name: str, function: str | None
    ) -> _Entry | None:
        """The entry of ``name`` in ``table``; for ``provider`` the entry of its function, or the only one it has."""
        if kind != PROVIDER:
            self._reject_function(kind, function)
            return table.get(name)
        if function is not None:
            _check_function(name, function)
            return table.get((name, function))
        found = [entry_key for entry_key in table if entry_key[0] == name]
        if len(found) > 1:
            raise self._ambiguous(name, [entry_key[1] for entry_key in found])
        return table[found[0]] if found else None

    @staticmethod
    def _names_in(kind: str, table: dict[Any, _Entry], function: str | None) -> list[str]:
        if kind != PROVIDER:
            Registrar._reject_function(kind, function)
            return sorted(table)
        return sorted({n for n, f in table if function is None or f == function})

    def _ensure_builtins(self) -> None:
        """Run the built-in plugins, once, before the first read or write (so a name a built-in owns is a duplicate, as it is today).

        The started flag is set first, because a built-in registers through this registrar and asks for the built-ins again. The lock is
        re-entrant for that thread, and another thread waits until the loading has finished, so it never reads half of the built-ins.
        A built-in whose ``plugins`` package does not exist is skipped (so is one whose parent package is missing); any other error, in
        the module or in ``register``, is raised, and the loading is not tried again.
        """
        if self._builtins_loaded:
            return
        with self._load_lock:
            if self._builtins_started:
                return
            self._builtins_started = True
            try:
                for text in self._builtin_plugins:
                    module_name, _, attribute = text.partition(":")
                    try:
                        module = importlib.import_module(module_name)
                    except ModuleNotFoundError as exc:
                        # The module itself, or a package above it, is absent (the owner has no plugin yet): skip it. A missing
                        # dependency of a plugin that exists has another name, and is raised.
                        if exc.name is not None and (
                            module_name == exc.name or module_name.startswith(exc.name + ".")
                        ):
                            continue
                        raise
                    getattr(module, attribute)(self)
            finally:
                self._builtins_loaded = True

    def _scan_failures(self) -> list[tuple[str, str]]:
        """The entry points that failed in the scan of this registrar: ``(name, error)``; empty when it did not scan (Requirement 57.7)."""
        if not (self._scan and self._scanned):
            return []
        try:
            reports = _import_text("plugins", "plugin_reports", PLUGIN_REPORTS)()
        except ConfigurationError:
            return []
        return [(r.name, r.error) for r in reports if not r.loaded and r.error]

    def _scan_once(self) -> None:
        """Scan the entry points, once per registrar, by the first thread that needs it; the others wait until it has finished.

        A lookup made by the scan itself (a plugin that reads the registrar while it registers) finds the scan started and does not start another.
        """
        if not self._scan or self._scanned:
            return
        with self._load_lock:
            if self._scan_started:
                return
            self._scan_started = True
            try:
                _import_text("plugins", "discover", DISCOVER)(self)
            finally:
                self._scanned = True

    def _table(self, kind: str) -> dict[Any, _Entry]:
        self._ensure_builtins()
        try:
            return self._tables[kind]
        except KeyError:
            raise ConfigurationError(
                f"unknown kind {kind!r}; the kinds are {', '.join(KINDS)}",
                {"kind": kind, "kinds": list(KINDS)},
            ) from None

    def _register(
        self,
        kind: str,
        name: str,
        target: Any,
        replace: bool,
        profile: Any | None = None,
        function: str | None = None,
        tools: tuple[Any, ...] | None = None,
    ) -> None:
        """Validate, then write: a registration that raises changes nothing."""
        if not isinstance(name, str) or not name:
            raise ConfigurationError(
                f"the name of a {kind} must be a non-empty string, got {name!r}",
                {"kind": kind, "name": name},
            )
        if target is None:
            raise ConfigurationError(
                f"the target of {kind} {name!r} is missing", {"kind": kind, "name": name}
            )
        if isinstance(target, str) and not _TEXT_TARGET.match(target):
            raise ConfigurationError(
                f"the target of {kind} {name!r} is the text {target!r}; a text target is 'module:attribute'",
                {"kind": kind, "name": name, "target": target},
            )
        key: Any = name
        if kind == PROVIDER:
            function = _provider_function(name, target, function)
            key = (name, function)
        else:
            self._reject_function(kind, function)
        self._table(kind)  # loads the built-ins and checks the kind, before the lock
        with self._write_lock:
            table = self._tables[kind]
            if key in table and not replace:
                what = f"{kind} {name!r} ({function})" if kind == PROVIDER else f"{kind} {name!r}"
                details: dict[str, Any] = {"kind": kind, "name": name}
                if kind == PROVIDER:
                    details["function"] = function
                raise ConfigurationError(
                    f"{what} is already registered; pass replace=True to override it", details
                )
            if profile is not None and kind == PROVIDER:
                held = self._profiles.get(name)
                if held is not None and held != profile and not replace:
                    raise ConfigurationError(
                        f"provider {name!r} already has a different profile; pass replace=True to override it",
                        {"kind": kind, "name": name},
                    )
                profiles = dict(self._profiles)
                profiles[name] = profile
                self._profiles = profiles  # published whole, like a table
            if kind == "toolkit":
                toolkit_tools = dict(self._toolkit_tools)
                if tools is None:
                    toolkit_tools.pop(name, None)
                else:
                    toolkit_tools[name] = tools
                self._toolkit_tools = toolkit_tools  # published whole, like a table
            # A copy of the table is published, never a change in place: a reader holds a table that stays as it was.
            published = dict(table)
            published[key] = _Entry(target)
            self._tables[kind] = published


_PROFILE_FIELDS = frozenset(f.name for f in dataclasses.fields(ProviderProfile)) - {
    "name",
    "models",
}
_MODEL_FIELDS = frozenset(f.name for f in dataclasses.fields(ModelProfile))


def _merge_model(held: ModelProfile | None, change: Any, model: str) -> ModelProfile:
    """The entry of ``model`` with ``change`` merged into ``held`` (``None`` for a model the profile lacks)."""
    if isinstance(change, ModelProfile):
        defaults = ModelProfile()
        given = {
            f.name: getattr(change, f.name)
            for f in dataclasses.fields(ModelProfile)
            if getattr(change, f.name) != getattr(defaults, f.name)
        }
    elif isinstance(change, Mapping):
        unknown = sorted(set(change) - _MODEL_FIELDS)
        if unknown:
            raise TypeError(
                f"model {model!r}: {', '.join(unknown)} is not a field of ModelProfile; the fields are {', '.join(sorted(_MODEL_FIELDS))}"
            )
        given = dict(change)
    else:
        raise TypeError(
            f"model {model!r}: a change is a ModelProfile or a mapping of fields, not {type(change).__name__}"
        )
    base = held if held is not None else ModelProfile()
    if "info" in given and given["info"] is not None:
        given["info"] = {**base.info, **dict(given["info"])}  # key by key: the keys not given stay
    return dataclasses.replace(base, **given) if given else base


def _merge_profile(
    held: ProviderProfile,
    models: Mapping[str, Mapping[str, Any] | ModelProfile] | None,
    fields: Mapping[str, Any],
) -> ProviderProfile:
    """``held`` with the given scalar fields and model changes merged in; ``held`` itself when nothing is given."""
    unknown = sorted(set(fields) - _PROFILE_FIELDS)
    if unknown:
        raise TypeError(
            f"profile() got {', '.join(unknown)}, which is not a field that can change; the fields are {', '.join(sorted(_PROFILE_FIELDS))}"
        )
    changes: dict[str, Any] = dict(fields)
    if models:
        merged = dict(held.models)
        for model, change in models.items():
            merged[model] = _merge_model(held.models.get(model), change, model)
        changes["models"] = merged
    return dataclasses.replace(held, **changes) if changes else held


def _import_text(kind: str, name: str, text: str) -> Any:
    """Import ``"module:attribute"`` (the attribute may be dotted); a failure is a ``ConfigurationError`` that keeps its cause."""
    module_name, _, attribute = text.partition(":")
    try:
        target: Any = importlib.import_module(module_name)
        for part in attribute.split("."):
            target = getattr(target, part)
    except (ImportError, AttributeError) as exc:
        raise ConfigurationError(
            f"{kind} {name!r} points to {text!r}, which cannot be imported: {exc}",
            {"kind": kind, "name": name, "target": text},
        ) from exc
    return target


_default: Registrar | None = None


def get_registrar() -> Registrar:
    """The default registrar of the process, created on first use."""
    global _default
    if _default is None:
        _default = Registrar(scan=True, builtin_plugins=BUILTIN_PLUGINS)
    return _default


_T = TypeVar("_T")

#: Told apart from ``None``: a call with no target returns a decorator, a call with ``target=None`` is a missing target (an error).
_NO_TARGET: Any = object()


class Plugins:
    """A handle on the registrar that registers by call or by decorator, at the moment it runs (Requirement 56.1, 56.2; D111).

    The handle holds no table. ``Plugins()`` forwards to the default registrar of the process, read at each call, so a test that replaces the
    default sees its own registrar and two handles made in two modules see the same registrations. ``Plugins(registrar=registrar)`` forwards to
    that registrar instead.

    One method for each kind in ``KINDS``. With the name and the target it registers and returns ``None``; with the name only it returns a
    decorator that registers the function or class it is put on and returns it unchanged, so the object stays usable by its own name:

        >>> plugins = Plugins(registrar=Registrar())
        >>> @plugins.agent("reverse")
        ... class ReverseAgent:
        ...     pass
        >>> plugins.get("agent", "reverse") is ReverseAgent
        True
        >>> plugins.names("agent")
        ['reverse']

    Every kind method takes ``replace=False``; ``provider`` takes ``profile=`` and ``function=`` (``"model"``, ``"embedding"``, ``"decision"``) for a
    text target or to say it; ``toolkit`` takes ``tools=``, the capabilities written outside the class that join the toolkit when it is built.

    Raises: ``ConfigurationError`` for a name already registered for the kind (unless ``replace=True``), for an unknown kind, for an empty
        name, for a ``target`` of ``None`` and for a text target that does not import at the first ``get``.
    Missing: nothing is held here; the registrar holds the tables.
    Concurrency: as the registrar: registration at start-up from one thread today, a lock on the write is the next task.
    """

    def __init__(self, *, registrar: Registrar | None = None) -> None:
        self._registrar = registrar

    @property
    def registrar(self) -> Registrar:
        """The registrar this handle forwards to: the one it was given, else the default registrar of the process, read now."""
        return self._registrar if self._registrar is not None else get_registrar()

    # -- one method for each kind ---------------------------------------------------------------------------

    @overload
    def provider(
        self,
        name: str,
        target: Any,
        *,
        profile: Any | None = ...,
        function: ProviderFunction | None = ...,
        replace: bool = ...,
    ) -> None: ...
    @overload
    def provider(
        self,
        name: str,
        *,
        profile: Any | None = ...,
        function: ProviderFunction | None = ...,
        replace: bool = ...,
    ) -> Callable[[_T], _T]: ...
    def provider(
        self,
        name: str,
        target: Any = _NO_TARGET,
        *,
        profile: Any | None = None,
        function: ProviderFunction | None = None,
        replace: bool = False,
    ) -> Callable[[_T], _T] | None:
        """Register a provider under ``name`` for one function: a model, an embedding or a decision (Requirement 56.12).

        The function is deduced from the methods of the class (``acomplete``, ``aencode``, ``decide``). A text target must come with
        ``function=``, because it is not imported now; for any other target it is optional and a wrong one raises. The same name may be
        registered for two functions, and the profile is the one of the name.
        """
        return self._add(PROVIDER, name, target, replace, profile=profile, function=function)

    @overload
    def backend(self, name: str, target: Any, *, replace: bool = ...) -> None: ...
    @overload
    def backend(self, name: str, *, replace: bool = ...) -> Callable[[_T], _T]: ...
    def backend(
        self, name: str, target: Any = _NO_TARGET, *, replace: bool = False
    ) -> Callable[[_T], _T] | None:
        """Register a storage backend under ``name``."""
        return self._add("backend", name, target, replace)

    @overload
    def credential_source(self, name: str, target: Any, *, replace: bool = ...) -> None: ...
    @overload
    def credential_source(self, name: str, *, replace: bool = ...) -> Callable[[_T], _T]: ...
    def credential_source(
        self, name: str, target: Any = _NO_TARGET, *, replace: bool = False
    ) -> Callable[[_T], _T] | None:
        """Register a credential source under ``name``."""
        return self._add("credential_source", name, target, replace)

    @overload
    def routing_strategy(self, name: str, target: Any, *, replace: bool = ...) -> None: ...
    @overload
    def routing_strategy(self, name: str, *, replace: bool = ...) -> Callable[[_T], _T]: ...
    def routing_strategy(
        self, name: str, target: Any = _NO_TARGET, *, replace: bool = False
    ) -> Callable[[_T], _T] | None:
        """Register a routing strategy under ``name``."""
        return self._add("routing_strategy", name, target, replace)

    @overload
    def mcp_client(self, name: str, target: Any, *, replace: bool = ...) -> None: ...
    @overload
    def mcp_client(self, name: str, *, replace: bool = ...) -> Callable[[_T], _T]: ...
    def mcp_client(
        self, name: str, target: Any = _NO_TARGET, *, replace: bool = False
    ) -> Callable[[_T], _T] | None:
        """Register an MCP client implementation under ``name`` (the ``impl`` of a server)."""
        return self._add("mcp_client", name, target, replace)

    @overload
    def tokenizer(self, name: str, target: Any, *, replace: bool = ...) -> None: ...
    @overload
    def tokenizer(self, name: str, *, replace: bool = ...) -> Callable[[_T], _T]: ...
    def tokenizer(
        self, name: str, target: Any = _NO_TARGET, *, replace: bool = False
    ) -> Callable[[_T], _T] | None:
        """Register a tokenizer under ``name`` (the name a ``ModelProfile`` refers to)."""
        return self._add("tokenizer", name, target, replace)

    @overload
    def template_filter(self, name: str, target: Any, *, replace: bool = ...) -> None: ...
    @overload
    def template_filter(self, name: str, *, replace: bool = ...) -> Callable[[_T], _T]: ...
    def template_filter(
        self, name: str, target: Any = _NO_TARGET, *, replace: bool = False
    ) -> Callable[[_T], _T] | None:
        """Register a template filter in the default set under ``name``."""
        return self._add("template_filter", name, target, replace)

    @overload
    def agent(self, name: str, target: Any, *, replace: bool = ...) -> None: ...
    @overload
    def agent(self, name: str, *, replace: bool = ...) -> Callable[[_T], _T]: ...
    def agent(
        self, name: str, target: Any = _NO_TARGET, *, replace: bool = False
    ) -> Callable[[_T], _T] | None:
        """Register an agent type under ``name``."""
        return self._add("agent", name, target, replace)

    @overload
    def toolkit(
        self, name: str, target: Any, *, tools: Sequence[Any] | None = ..., replace: bool = ...
    ) -> None: ...
    @overload
    def toolkit(
        self, name: str, *, tools: Sequence[Any] | None = ..., replace: bool = ...
    ) -> Callable[[_T], _T]: ...
    def toolkit(
        self,
        name: str,
        target: Any = _NO_TARGET,
        *,
        tools: Sequence[Any] | None = None,
        replace: bool = False,
    ) -> Callable[[_T], _T] | None:
        """Register a toolkit under ``name``: a named set of tools that an agent takes apart from its own (Requirement 62.5).

        ``tools`` is a list of capabilities (functions written with ``@capability``, outside the class) that join the toolkit when it is
        built, each as ``<name>.<function name>``. Three shapes:

        * name and target: registers at once (a class, a factory, a function that returns a ``CapabilityRegistry``, or a text);
        * name only: the decorator that registers the class or function it is put on and returns it unchanged;
        * name and ``tools`` and no target: the toolkit is registered at once as the list of tools, so it works with no class
          (``plugins.toolkit("text", tools=[slugify])``), and the returned decorator, when it is put on a class
          (``@plugins.toolkit("jira", tools=[slugify])``), gives that class to the same registration.

        Raises:
            ConfigurationError: ``tools`` is not a list of capabilities, the name is registered already (without ``replace=True``), or in
                the decorator form the registration was replaced between the call and the decorator.
        """
        if target is not _NO_TARGET:
            self._write("toolkit", name, target, replace, None, None, tools)
            return None
        if tools is None:
            return self._add("toolkit", name, target, replace)
        self._write("toolkit", name, TOOLSET, replace, None, None, tools)
        held = self.registrar.toolkit_tools(name)

        def decorator(obj: _T) -> _T:
            self.registrar._upgrade_toolkit(name, TOOLSET, held, obj)
            return obj

        return decorator

    # -- what the registrar answers, forwarded ----------------------------------------------------------------

    def names(self, kind: str, function: ProviderFunction | None = None) -> list[str]:
        """The names registered for ``kind``, sorted. Nothing is imported. For ``provider``, ``function=`` keeps the names of that function."""
        if function is None:
            return self.registrar.names(kind)
        return self.registrar.names(kind, function)

    def has(self, kind: str, name: str, function: ProviderFunction | None = None) -> bool:
        """Whether ``name`` is registered for ``kind``. Nothing is imported."""
        if function is None:
            return self.registrar.has(kind, name)
        return self.registrar.has(kind, name, function)

    def get(self, kind: str, name: str, function: ProviderFunction | None = None) -> Any:
        """The target registered for ``name``; a ``"module:attribute"`` text is imported now, the first time it is asked for.

        For ``provider``, ``function=`` says which function when the name has two; it may be left out when it has one.
        """
        if function is None:
            return self.registrar.get(kind, name)
        return self.registrar.get(kind, name, function)

    def get_profile(self, provider: str) -> Any | None:
        """The profile registered with the provider ``provider``, or ``None`` when it has none."""
        return self.registrar.get_profile(provider)

    def profile(
        self,
        provider: str,
        models: Mapping[str, Mapping[str, Any] | ModelProfile] | None = None,
        **fields: Any,
    ) -> None:
        """Merge a change into the profile of an existing provider and change nothing else (Requirement 59.11).

        Only what is given changes: a model entry is changed field by field, a model that is not there is added, and the prices, the
        endpoint and the other models stay as they are. To change the tokenizer of one model of a provider that already exists:

            >>> from skye.base.profile import ModelProfile, ProviderProfile
            >>> plugins = Plugins(registrar=Registrar())
            >>> plugins.provider("acme", "acme.models:Chat", function="model", profile=ProviderProfile(
            ...     "acme", models={"acme-1": ModelProfile(prompt_price=1.0, completion_price=2.0)}))
            >>> plugins.profile("acme", models={"acme-1": ModelProfile(tokenizer="words")})
            >>> plugins.get_profile("acme").models["acme-1"].prompt_price
            1.0

        See ``Registrar.profile`` for what a ``ModelProfile`` and a mapping of fields change, and for the errors.
        """
        self.registrar.profile(provider, models, **fields)

    def unregister(self, kind: str, name: str, function: ProviderFunction | None = None) -> bool:
        """Remove ``name`` from ``kind``; ``True`` when it was registered. For the owners' views and for a test that cleans up after itself."""
        if function is None:
            return self.registrar.unregister(kind, name)
        return self.registrar.unregister(kind, name, function)

    def default_set(self, kind: str) -> dict[str, Any]:
        """The names of ``kind`` mapped to what they resolve to: the default set that every new instance of a registry starts with."""
        return self.registrar.default_set(kind)

    # -- internals --------------------------------------------------------------------------------------------

    def _add(
        self,
        kind: str,
        name: str,
        target: Any,
        replace: bool,
        *,
        profile: Any | None = None,
        function: str | None = None,
    ) -> Callable[[_T], _T] | None:
        """Register now when there is a target; otherwise return the decorator that registers what it decorates and returns it unchanged."""
        if target is not _NO_TARGET:
            self._write(kind, name, target, replace, profile, function)
            return None

        def decorator(obj: _T) -> _T:
            self._write(kind, name, obj, replace, profile, function)
            return obj

        return decorator

    def _write(
        self,
        kind: str,
        name: str,
        target: Any,
        replace: bool,
        profile: Any | None,
        function: str | None = None,
        tools: Sequence[Any] | None = None,
    ) -> None:
        """One call to the method of the registrar that is named as the kind, read at the moment of the write."""
        method = getattr(self.registrar, kind)
        options: dict[str, Any] = {"replace": replace}
        if profile is not None:
            options["profile"] = profile
        if function is not None:
            options["function"] = function
        if tools is not None:
            options["tools"] = tools
        method(name, target, **options)
