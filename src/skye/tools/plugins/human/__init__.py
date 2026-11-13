# D110
"""The built-in toolkit ``human`` (plugin of ``tools``): ask a person or escalate to one.

Only this ``__init__.py`` is imported from outside; its names resolve lazily; ``register`` adds the
toolkit by text.

Raises: ``ConfigurationError`` from ``register`` when the name is already registered.
Missing: a missing inner file breaks only the name that lives in it.
Concurrency: ``register`` runs once at start-up; a name resolves once.
"""

from __future__ import annotations

from typing import Any

from skye.base.lazy_import import lazy_names

_LAZY = {
    "HumanToolkit": "toolkit",
    "HumanChannel": "toolkit",
    "EscalationMessage": "toolkit",
}
__all__ = [*_LAZY, "register"]
__getattr__ = lazy_names(__name__, _LAZY)


def register(registrar: Any) -> None:
    """Register the toolkit under its name, by text."""
    registrar.toolkit("human", f"{__name__}:HumanToolkit")
