# O80
"""The ``skyea2a`` engine (plugin of ``tools``): an A2A client on the standard library, as
``skyemcp`` is for MCP. SKELETON: nothing is implemented.

This folder is not registered and no kind exists for it yet (is open); the door names the class so
the folder has the same shape as the others.

Raises: ``NotImplementedError`` from every method of the class.
Missing: the folder is not in ``IMPLEMENTATIONS``.
Concurrency: not applicable.
"""

from __future__ import annotations

from skye.base.lazy_import import lazy_names

_LAZY = {"SkyeA2AClient": "client"}
__all__ = list(_LAZY)
__getattr__ = lazy_names(__name__, _LAZY)
