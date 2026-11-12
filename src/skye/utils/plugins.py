"""Plugin discovery: the scan of the entry-point group ``skye.plugins`` (plugins:4.1, D111).

An entry point is a module. ``discover(registrar)`` reads ``importlib.metadata.entry_points(group="skye.plugins")`` and loads each entry
point, which imports the module it names (``acme = "acme_skye.plugins"``); the decorators and calls of ``skye.Plugins`` in that module register
when it is imported, so the entry point is a convenience: a program that imports the module itself registers the same way, and a module
imported before the scan is a no-op for the scan (Python imports a module once), so nothing registers twice and the scan finds no duplicate.
There is no ``register(registrar)`` to call on an entry point, no ``use_plugin`` and no ``skye.use``.

The decorators of a module write to the default registrar (``Plugins()`` reads ``get_registrar()`` when it runs). When ``discover`` gets
another registrar (a test), it makes that registrar the default for the length of each import and puts the default back, so the module
registers there. The default registrar is read from ``skye.base.plugins`` as a module variable: ``base`` has no setter for it.

The ``plugins`` key of the configuration file (Requirement 57.5, D91) limits the scan: when it is a list, only the entry points with those names are
loaded, and any other is neither loaded nor imported and is reported as skipped; without the key every entry point loads. The key is read with
``skye.utils.config_files.configured_plugins``, which applies no log level.

One entry point that fails to load (an import error, or an error raised by the module while it registers) is logged once at WARNING, with ``extra``
carrying the entry point, the distribution and the error, and skipped; the scan goes on (Requirement 57.6, D105). What the module registered before it
failed stays registered and is in its report. Each entry point leaves a ``PluginReport`` with the names it added per kind (the difference of
``names(kind)`` before and after the import; a provider that is not a model shows its function, ``acme (embedding)``); ``plugin_reports()`` returns the reports of the last scan, for ``skye plugins`` and for the error of an
unknown name (Requirement 57.7).

This module lives in ``utils`` because reading package metadata is I/O; ``base`` reaches it by the text ``"skye.utils.plugins:discover"``
and imports it at the first lookup that misses (plugins:4.2), so ``import skye`` scans nothing.

Raises: ``ConfigurationError`` from ``discover`` when the configuration file cannot be read or its ``plugins`` is not a list of names (the file is the
    user's to fix, so the lookup that triggered the scan fails with that error); ``discover`` raises nothing for a failing entry point, it reports it.
Missing: an entry point with no installed distribution is reported with ``distribution`` and ``version`` of ``None``; no entry point at all
    gives an empty report; a module imported before the scan reports no names (they were registered when the program imported it).
Concurrency: the scan runs once, from the first lookup that misses, in one thread; the default registrar is swapped for the length of an import only
    when a registrar other than the default is given, which only a test does; ``plugin_reports()`` returns an immutable snapshot.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from importlib import metadata
from typing import Any

import skye.base.plugins as base_plugins
from skye.base.exceptions import ConfigurationError
from skye.base.plugins import KINDS, PROVIDER_FUNCTIONS, Registrar
from skye.utils.config_files import configured_plugins

logger = logging.getLogger(__name__)

#: The entry-point group of the installed plugins (Requirement 57.1).
GROUP = "skye.plugins"


@dataclass(frozen=True)
class PluginReport:
    """What the scan found out about one entry point.

    Attributes:
        name: The entry-point name.
        distribution: The name of the installed distribution that declares it, or ``None``.
        version: The version of that distribution, or ``None``.
        loaded: Whether the entry point loaded and registered without an error.
        error: The error text when ``loaded`` is false, otherwise ``None``.
        registered: The names it added to the registrar, per kind (only the kinds it added to).
        skipped: Whether the ``plugins`` allowlist of the configuration left it out: it was not loaded and not imported
            (``loaded`` is false and ``error`` is ``None``).
    """

    name: str
    distribution: str | None = None
    version: str | None = None
    loaded: bool = True
    error: str | None = None
    registered: dict[str, list[str]] = field(default_factory=dict)
    skipped: bool = False


_reports: tuple[PluginReport, ...] = ()


def plugin_reports() -> tuple[PluginReport, ...]:
    """The reports of the last scan (empty before the first one)."""
    return _reports


#: A name no plugin can have: a lookup of it misses, which is how a registrar is asked to scan the entry points (there is no public call for it).
_PROBE = "\x00skye-plugins-probe"


def scan(registrar: Registrar | None = None) -> tuple[PluginReport, ...]:
    """Make sure ``registrar`` has scanned the entry points and return the reports of the scan (for ``skye plugins``).

    The default registrar scans at the first lookup that misses, so a miss on a name nobody can register asks for the scan; a registrar that
    scanned before is not scanned again, and ``registrar`` made with ``scan=False`` gives no reports. The reports are those of the last scan
    of the process (``plugin_reports()``).

    Args:
        registrar: The registrar to read; the default registrar of the process when omitted.

    Raises:
        ConfigurationError: The configuration file cannot be read or its ``plugins`` is not a list of names (the error of ``discover``).
    """
    source = registrar or base_plugins.get_registrar()
    try:
        source.get("backend", _PROBE)
    except ConfigurationError as exc:
        if (exc.details or {}).get("name") != _PROBE:
            raise
    return plugin_reports()


def _entry_points() -> Iterable[Any]:
    """The entry points of the group; one function so a test can replace the metadata."""
    return metadata.entry_points(group=GROUP)


@contextmanager
def _default_registrar_is(registrar: Registrar) -> Iterator[None]:
    """Make ``registrar`` the one that ``get_registrar()`` returns, for the length of the block, and put the default back.

    The decorators of an imported module read ``get_registrar()`` when they run, so this is how a module registers on a registrar that is not the
    default (a test). With the default itself it does nothing.
    """
    if registrar is base_plugins._default:
        yield
        return
    previous = base_plugins._default
    base_plugins._default = registrar
    try:
        yield
    finally:
        base_plugins._default = previous


def _names(registrar: Registrar, kind: str) -> set[str]:
    """The names of ``kind``. For ``provider`` a name is shown with its function when it is not a model: ``acme`` and ``acme (embedding)``."""
    if kind != "provider":
        return set(registrar.names(kind))
    found: set[str] = set()
    for function in PROVIDER_FUNCTIONS:
        names = registrar.names(kind, function)  # type: ignore[arg-type]
        found.update(names if function == "model" else (f"{name} ({function})" for name in names))
    return found


def _snapshot(registrar: Registrar) -> dict[str, set[str]]:
    return {kind: _names(registrar, kind) for kind in KINDS}


def _added(before: dict[str, set[str]], registrar: Registrar) -> dict[str, list[str]]:
    added = {kind: sorted(_names(registrar, kind) - before[kind]) for kind in KINDS}
    return {kind: names for kind, names in added.items() if names}


def discover(registrar: Registrar, allowlist: Sequence[str] | None = None) -> list[PluginReport]:
    """Load the installed plugins of the group ``skye.plugins`` into ``registrar`` and return one report per entry point.

    Args:
        registrar: Where the plugins register.
        allowlist: The entry-point names that may load. ``None`` reads the ``plugins`` key of the configuration file, and with no file or no key
            every entry point may load. An entry point not listed is not loaded and not imported (it is reported as skipped); a listed name
            that is not installed is not an error.

    A failure to load (the import raises, or the module fails while it registers) is logged once at WARNING and the scan goes on. The reports are
    kept for ``plugin_reports()``.

    Raises:
        ConfigurationError: The configuration file cannot be read or its ``plugins`` is not a list of names.
    """
    global _reports
    if allowlist is None:
        allowlist = configured_plugins()
    allowed = None if allowlist is None else set(allowlist)
    reports: list[PluginReport] = []
    for entry_point in sorted(_entry_points(), key=lambda ep: ep.name):
        dist = getattr(entry_point, "dist", None)
        distribution = dist.metadata["Name"] if dist is not None else None
        version = dist.version if dist is not None else None
        if allowed is not None and entry_point.name not in allowed:
            logger.debug(
                "plugin entry point not in the plugins allowlist",
                extra={"entry_point": entry_point.name},
            )
            reports.append(
                PluginReport(
                    name=entry_point.name,
                    distribution=distribution,
                    version=version,
                    loaded=False,
                    skipped=True,
                )
            )
            continue
        before = _snapshot(registrar)
        error: str | None = None
        try:
            with _default_registrar_is(registrar):
                entry_point.load()  # imports the module: its decorators register
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "plugin entry point skipped",
                extra={
                    "entry_point": entry_point.name,
                    "distribution": distribution,
                    "error": error,
                },
            )
        reports.append(
            PluginReport(
                name=entry_point.name,
                distribution=distribution,
                version=version,
                loaded=error is None,
                error=error,
                registered=_added(before, registrar),
            )
        )
    _reports = tuple(reports)
    return reports
