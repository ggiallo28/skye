# plugins:5.1, D110, task 6.3, task 6.1
"""The built-in plugin of ``models``: one folder per provider, registered by text with its profile
(and 5.5).

``register(registrar)`` is the same call a third-party plugin makes. It registers the tokenizer that
the profiles name, then calls the ``register`` of
each folder of ``IMPLEMENTATIONS``. A folder is a provider (``openai``, ``anthropic``, ...) with its
code (``provider.py``, ``embeddings.py``, ...), its
data (``profile.toml``) and one ``__init__.py`` that is the only door to it. Each class is a
``"module:attribute"`` text, so registering imports no
adapter; the class is imported when its name is first looked up. The profiles are data: updating a
price or adding a model edits a ``profile.toml`` and
no code. ``profiles()`` gives every profile of every folder by provider name; ``PROFILES`` is the
same, read on first access.

The profiles are the one home of what is specific to a provider: the prices, the tokenizer, the
endpoint and the variables that hold the key
(``api_key_variables``, read through ``skye.base.api_keys``; removed the tables that ``auth`` and
the router held). The prefixes of
``TokenCounter`` are read from the profiles too; ``tests/unit/plugins/test_builtin_profiles.py``
keeps frozen copies of the old
tables and fails when a profile drifts from them.

Raises: ``ConfigurationError`` from the registrar when a built-in name is already registered (a
plugin that wants to replace one passes ``replace=True``),
    and from a folder for a profile file that is missing or has an unknown key.
Missing: a provider with no model in its profile (an embedding-only provider) simply has no prices;
that is not an error.
Concurrency: ``register`` is called once at start-up, from one thread; the profiles are immutable.
"""

from __future__ import annotations

import functools
import importlib
from typing import Any

from skye.base.profile import ProviderProfile

#: The provider folders of this package, in registration order (D110).
IMPLEMENTATIONS: tuple[str, ...] = (
    "openai",
    "anthropic",
    "bedrock",
    "azure",
    "google",
    "cohere",
    "typesafe",
)


def _folder(name: str) -> Any:
    return importlib.import_module(f"{__name__}.{name}")


@functools.cache
def profiles() -> dict[str, ProviderProfile]:
    """Every profile of every provider folder, by provider name, read from the ``profile.toml``
    files."""
    found: dict[str, ProviderProfile] = {}
    for name in IMPLEMENTATIONS:
        found.update(_folder(name).profiles())
    return found


def __getattr__(name: str) -> Any:
    if name == "PROFILES":
        return profiles()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def register(registrar: Any) -> None:
    """Register the built-in model, embedding and decision providers, by text, each with its
    profile."""
    # The tokenizer that the profiles of the gpt-, o1- and o3- models name; a factory taking the
    # model name (plugins:6.2)
    registrar.tokenizer("tiktoken", "skye.models.token_counter:tiktoken_tokenizer")
    for name in IMPLEMENTATIONS:
        _folder(name).register(registrar)
