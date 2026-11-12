"""Thin lazy-import helper over stdlib ``importlib``.

Attempts the import at first use and maps absence of an optional dependency to
``MissingExtraError``, which names the Extra to install. Stdlib-only.
"""

import importlib
import sys
from collections.abc import Callable, Mapping
from types import ModuleType
from typing import Any

from skye.base.exceptions import MissingExtraError


def missing_extra(module: str, extra: str, package: str | None = None) -> ModuleType:
    """Import ``module`` or raise ``MissingExtraError`` naming ``extra``."""
    try:
        return importlib.import_module(module)
    except ImportError as e:  # includes ModuleNotFoundError
        raise MissingExtraError(extra=extra, missing=module, package=package) from e


def lazy_names(package: str, names: Mapping[str, str]) -> Callable[[str], Any]:
    """The module ``__getattr__`` of a plugin folder (D110): ``names`` maps a public name to the inner module of ``package`` that defines it.

    A name is resolved from its inner file only when it is first asked for and is then kept as an attribute of the package, so importing the
    folder imports no inner file and no vendor library. A name the folder does not offer is an ``AttributeError``; a missing inner file is an
    ``ImportError`` on that name alone.
    """

    def __getattr__(name: str) -> Any:
        module = names.get(name)
        if module is None:
            raise AttributeError(f"module {package!r} has no attribute {name!r}")
        value = getattr(importlib.import_module(f"{package}.{module}"), name)
        setattr(sys.modules[package], name, value)  # resolved once
        return value

    return __getattr__


__all__ = ["lazy_names", "missing_extra"]
