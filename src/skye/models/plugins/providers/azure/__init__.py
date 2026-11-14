# D110
"""Azure OpenAI (plugin of ``models``): the language model of Azure OpenAI.

This ``__init__.py`` is the only module that code outside the folder imports. Its public names
resolve lazily from the files of the folder, so importing
the folder imports no inner file and no vendor library; ``register`` adds what the folder offers to
a registrar, by ``"module:attribute"`` text.

Raises: ``ConfigurationError`` from ``register`` when the profile file is missing or invalid, or
when a name is already registered (replacing one is the
    caller's ``replace=True``, never this folder's).
Missing: a missing inner file breaks only the name that lives in it (an ``ImportError`` on first
access, turned into a ``ConfigurationError`` by the registrar).
Concurrency: ``register`` is called once at start-up from one thread; a name resolves once and is
the same object afterwards.
"""

from __future__ import annotations

import functools
from typing import Any

from skye.base.lazy_import import lazy_names
from skye.base.profile import ProviderProfile
from skye.models.utilities.vendor import read_profile

_LAZY = {
    "AzureOpenAIProvider": "provider",
}
__all__ = [*_LAZY, "profiles", "register"]
__getattr__ = lazy_names(__name__, _LAZY)

_PROFILE_FILES = ("profile.toml",)


@functools.cache
def profiles() -> dict[str, ProviderProfile]:
    """The profile files of this folder by provider name: read once, the same objects afterwards (a
    model and an embedding provider of one name share one)."""
    found = [read_profile(__name__, filename) for filename in _PROFILE_FILES]
    return {profile.name: profile for profile in found}


def register(registrar: Any) -> None:
    """Register what this folder offers, each class by text."""
    registrar.provider(
        "azure", f"{__name__}:AzureOpenAIProvider", profile=profiles()["azure"], function="model"
    )
