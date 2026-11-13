# decisions D95, D98
"""What every backend of ``store`` shares: the clock, the expiry rule and the error wrapping.

Standard library only. Never logs or puts in an error message a stored value, a URL with a password
or a credential.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from skye.base.exceptions import ProviderError, SkyeError, ValidationError
from skye.base.interfaces.storage import check_key, check_ttl

#: A function that returns the current time in seconds since the epoch; tests pass a fake one.
Clock = Callable[[], float]


# D95
def expiry_of(ttl: int | None, clock: Clock) -> float | None:
    """The absolute expiry of a value written now with ``ttl`` (validated), or ``None``."""
    checked = check_ttl(ttl)
    return None if checked is None else clock() + checked


def is_expired(expiry: float | None, clock: Clock) -> bool:
    """``True`` when ``expiry`` is set and not in the future."""
    return expiry is not None and expiry <= clock()


def remaining_of(expiry: float | None, clock: Clock) -> int | None:
    """The whole seconds left before ``expiry``, rounded up (at least 1), or ``None`` for no expiry or an expired one."""
    if expiry is None or is_expired(expiry, clock):
        return None
    return max(1, math.ceil(expiry - clock()))


def count_of(value: dict[str, Any] | None) -> int:
    """The count held by a stored counter value ``{"count": n}``, ``0`` for no value (an absent or expired key)."""
    return 0 if not value else int(value.get("count", 0))


def check_data(data: object) -> dict[str, Any]:
    """Return ``data`` when it is a ``dict``; raise ``ValidationError`` otherwise."""
    if not isinstance(data, dict):
        raise ValidationError(
            f"a stored value must be a dict, got {type(data).__name__}", "data", type(data).__name__
        )
    return data


def check_items(data: object) -> dict[str, dict[str, Any]]:
    """Validate every key and value of a ``set_multiple`` argument before anything is written."""
    if not isinstance(data, dict):
        raise ValidationError(
            f"set_multiple takes a dict of key to value, got {type(data).__name__}",
            "data",
            type(data).__name__,
        )
    for key, value in data.items():
        check_key(key)
        check_data(value)
    return data


def check_limit(limit: object) -> int | None:
    """Return ``limit`` when it is ``None`` or a non-negative ``int``."""
    if limit is None:
        return None
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise ValidationError(
            f"limit must be None or a non-negative integer, got {limit!r}", "limit", limit
        )
    return limit


def like_prefix(prefix: str) -> str:
    """A SQL ``LIKE`` pattern for keys starting with ``prefix`` (``\\`` escapes ``%`` and ``_``)."""
    escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return escaped + "%"


@contextmanager
def provider_errors(backend: str, operation: str) -> Iterator[None]:
    """Turn a client error into ``ProviderError`` naming the backend and the operation.

    A Skye error passes through unchanged.
    """
    try:
        yield
    except SkyeError:
        raise
    except Exception as error:  # a client error of any library
        raise ProviderError(
            f"{backend}: {operation} failed ({type(error).__name__})",
            provider=backend,
            operation=operation,
        ) from error


def default_clock() -> float:
    """``time.time``, named so a backend can store it as its default clock."""
    return time.time()


__all__ = [
    "Clock",
    "check_data",
    "check_items",
    "check_limit",
    "default_clock",
    "expiry_of",
    "is_expired",
    "like_prefix",
    "provider_errors",
    "remaining_of",
]
