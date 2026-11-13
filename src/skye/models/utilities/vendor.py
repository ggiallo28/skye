# D110
"""What every provider folder of ``models/plugins`` shares: the lazy names of its ``__init__.py``
and the reading of its ``profile.toml``.

A provider folder is a small package whose ``__init__.py`` is the only door to it. ``lazy_names``
(in ``skye.base.lazy_import``, shared by every
component) builds the module ``__getattr__`` that resolves the public names of the folder from its
inner files only when they are first asked for;
this module has ``read_profile``, which reads a ``profile.toml`` of the folder with
``importlib.resources`` (it works from a wheel and from a zip) and builds
the ``ProviderProfile`` with ``profile_from_mapping`` of ``base``.

Raises: ``ConfigurationError`` from ``read_profile`` for a missing or malformed file (the folder and
the file are named, the cause is kept) and for a key the
    format does not know; ``AttributeError`` from the lazy ``__getattr__`` for a name the folder
    does not offer.
Missing: a missing inner file breaks only the name that lives in it: the ``ImportError`` is raised
on first access, and the registrar turns it into a
    ``ConfigurationError`` naming the kind and the name.
Concurrency: stateless apart from the cached names; safe from many threads (a name resolves to the
same object every time).
"""

from __future__ import annotations

import tomllib
from importlib import resources

from skye.base.exceptions import ConfigurationError
from skye.base.profile import ProviderProfile, profile_from_mapping


def read_profile(package: str, filename: str = "profile.toml") -> ProviderProfile:
    """The ``ProviderProfile`` in ``filename`` of the folder ``package``."""
    where = f"{package}/{filename}"
    try:
        text = resources.files(package).joinpath(filename).read_text(encoding="utf-8")
        data = tomllib.loads(text)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigurationError(
            f"the profile file {where} is missing or cannot be read: {exc}",
            {"package": package, "file": filename},
        ) from exc
    return profile_from_mapping(data, where)
