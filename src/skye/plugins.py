"""Plugins and provider profiles (public path of `skye.base.plugins` and `skye.base.profile`).

``Plugins`` is the object that adds an integration: its methods are decorators (or direct calls)
that register at once, one for each kind
of integration. ``Registrar`` is the table behind it. A provider is declared once, with a
``ProviderProfile`` registered together with its
class. The code lives in ``skye.base``; import from here.
"""

from skye.base.plugins import KINDS, Plugins, Registrar, get_registrar
from skye.base.profile import (
    ModelProfile,
    ProviderProfile,
    RegionRule,
    find_model_profile,
    resolve_region,
)

__all__ = [
    "KINDS",
    "ModelProfile",
    "Plugins",
    "ProviderProfile",
    "RegionRule",
    "Registrar",
    "find_model_profile",
    "get_registrar",
    "resolve_region",
]
