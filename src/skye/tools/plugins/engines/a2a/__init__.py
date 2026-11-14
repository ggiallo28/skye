# O80
"""The ``a2a`` engine (plugin of ``tools``): an A2A client on the official SDK, imported only when a
client is built. SKELETON: nothing is implemented.

This folder is not registered and no kind exists for it yet (is open); the door names the class so
the folder has the same shape as the others.

Raises: ``NotImplementedError`` from every method of the class.
Missing: the folder is not in ``IMPLEMENTATIONS``.
Concurrency: not applicable.
"""

from __future__ import annotations

from skye.base.lazy_import import lazy_names

_LAZY = {"A2AClient": "client"}
__all__ = list(_LAZY)
__getattr__ = lazy_names(__name__, _LAZY)
