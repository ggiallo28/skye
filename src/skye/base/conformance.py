# Requirement 58.4
"""The runner that every ``check_<kind>`` function shares.

A check function lists its checks as ``(name, callable)`` pairs and hands them to
:func:`run_checks`, which runs them in order, awaits the ones
that return an awaitable, and returns the names of the checks that passed. The first check that
fails stops the run with an ``AssertionError``
that names the kind, the object and the check (``skye.store.check_backend`` raises the same type).

Raises: ``AssertionError`` naming the first failed check; the original error is the ``__cause__``
when the check raised one.
Missing: an empty list of checks returns an empty list.
Concurrency: the checks run one after the other in the task that awaits :func:`run_checks`.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from typing import Any

Check = tuple[str, Callable[[], Any]]


def label(target: Any) -> str:
    """The name of ``target`` for a message: its ``__name__``, else the name of its class."""
    return getattr(target, "__name__", None) or type(target).__name__


def require(condition: object, why: str) -> None:
    """Fail the running check with ``why`` unless ``condition`` is true."""
    if not condition:
        raise AssertionError(why)


async def run_checks(kind: str, target: Any, checks: Sequence[Check]) -> list[str]:
    """Run ``checks`` in order; return the names that passed, or raise on the first that fails."""
    passed: list[str] = []
    for name, check in checks:
        try:
            result = check()
            if inspect.isawaitable(result):
                await result
        except Exception as error:
            raise AssertionError(
                f"{kind} {label(target)!r}: the check {name!r} failed: {error}"
            ) from error
        passed.append(name)
    return passed
