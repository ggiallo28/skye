"""Who retries a provider call, and how long it waits (decision D104).

Only a transient failure is retried: :class:`RateLimitError` (429), :class:`ServerError` (5xx)
and :class:`ProviderTimeoutError` (a timeout or a dropped connection). A 4xx (bad request,
authentication, content policy) is raised at once: retrying cannot fix it. The wait doubles
after each attempt (exponential backoff, clamped), and the server's ``Retry-After`` replaces it
when the error carries one.

The retry is written in the standard library (no third-party dependency); the sleep is
injectable so tests do not wait.
"""

import asyncio
import functools
import inspect
import logging
import random
import time
from collections.abc import Callable
from typing import Any, TypeVar

from skye.base.exceptions import (
    ProviderError,
    ProviderTimeoutError,
    RateLimitError,
    ServerError,
)

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])
T = TypeVar("T")

#: The errors a client retries on its own (D104).
RETRYABLE_ERRORS: tuple[type[ProviderError], ...] = (
    RateLimitError,
    ServerError,
    ProviderTimeoutError,
)

#: Retries a client makes after the first attempt when ``max_retries`` is not given.
DEFAULT_MAX_RETRIES = 3

#: The longest wait a ``Retry-After`` header can ask for (seconds); a longer one is clamped.
MAX_RETRY_AFTER = 60.0


def is_retryable(error: BaseException) -> bool:
    """Whether a client retries ``error`` by itself: a rate limit, a server error or a timeout."""
    return isinstance(error, RETRYABLE_ERRORS)


def _wait_seconds(
    attempt: int, multiplier: float, min_wait: float, max_wait: float, jitter: float
) -> float:
    """Seconds to wait after the failed attempt ``attempt`` (1-based), in [min_wait, max_wait]."""
    delay: float = multiplier * (2 ** (attempt - 1))
    delay = max(min_wait, min(delay, max_wait))
    if jitter > 0:
        delay += random.uniform(0, jitter)
    return delay


def retry_wait(
    error: BaseException,
    attempt: int,
    *,
    base_wait: float = 1.0,
    max_wait: float = 20.0,
    jitter: float = 0.0,
) -> float:
    """Seconds to wait before retrying after the failed attempt number ``attempt`` (1-based).

    The server's ``Retry-After`` (``error.retry_after``) wins, up to :data:`MAX_RETRY_AFTER`;
    otherwise ``base_wait`` doubles with each attempt, up to ``max_wait``.
    """
    retry_after = getattr(error, "retry_after", None)
    if retry_after is not None:
        return float(min(max(retry_after, 0.0), MAX_RETRY_AFTER))
    return _wait_seconds(attempt, base_wait, 0.0, max_wait, jitter)


def call_with_retry(
    call: Callable[[], T],
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    sleep: Callable[[float], Any] = time.sleep,
    base_wait: float = 1.0,
    max_wait: float = 20.0,
    name: str = "provider call",
) -> T:
    """Run ``call``, retrying a transient failure up to ``max_retries`` times.

    Args:
        call: The call to make, with no arguments.
        max_retries: Retries after the first attempt; ``0`` turns retries off.
        sleep: How to wait (``time.sleep``; a test passes a function that records the wait).
        base_wait: The first backoff wait in seconds.
        max_wait: The longest backoff wait in seconds.
        name: What is called, for the log.

    Returns:
        What ``call`` returns.

    Raises:
        ProviderError: The error of the last attempt, unchanged, or a non-retryable error at once.
    """
    attempt = 1
    while True:
        try:
            return call()
        except ProviderError as error:
            if not is_retryable(error) or attempt > max_retries:
                raise
            wait = retry_wait(error, attempt, base_wait=base_wait, max_wait=max_wait)
            logger.info(
                "Retrying a transient provider failure",
                extra={
                    "call": name,
                    "attempt": attempt,
                    "wait_seconds": wait,
                    "error_class": type(error).__name__,
                },
            )
            sleep(wait)
            attempt += 1


def with_retry(
    max_retries: int = 3,
    min_wait: float = 4,
    max_wait: float = 10,
    multiplier: float = 1,
    jitter: float = 0,
) -> Callable[[F], F]:
    """Decorator for adding retry logic to a function that calls a provider.

    Retries only the transient errors of :data:`RETRYABLE_ERRORS`; any other exception (a 4xx
    ``ProviderError`` included) propagates at once. The wait is exponential (with optional jitter),
    or the error's ``retry_after`` when it has one. When every attempt fails, the last error is
    re-raised unchanged. Works on plain functions and on coroutine functions (the async wrapper
    sleeps with ``asyncio.sleep``).

    Args:
        max_retries: Maximum number of attempts, the first included (default: 3)
        min_wait: Minimum wait time in seconds (default: 4)
        max_wait: Maximum wait time in seconds (default: 10)
        multiplier: Exponential backoff multiplier (default: 1)
        jitter: Upper bound in seconds of a random delay added to each wait (default: 0)

    Returns:
        Decorated function with retry logic

    Example:
        >>> @with_retry(max_retries=3)
        ... def call_provider(request):
        ...     return request
    """

    def wait_for(error: ProviderError, attempt: int) -> float:
        if error.retry_after is not None:
            return float(min(max(error.retry_after, 0.0), MAX_RETRY_AFTER))
        return _wait_seconds(attempt, multiplier, min_wait, max_wait, jitter)

    def decorator(func: F) -> F:
        def exhausted(error: ProviderError) -> None:
            logger.error(
                "Max retries exceeded",
                extra={
                    "call": func.__name__,
                    "max_retries": max_retries,
                    "error_class": type(error).__name__,
                },
            )

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                attempt = 1
                while True:
                    try:
                        return await func(*args, **kwargs)
                    except ProviderError as error:
                        if not is_retryable(error):
                            raise
                        if attempt >= max_retries:
                            exhausted(error)
                            raise
                        await asyncio.sleep(wait_for(error, attempt))
                        attempt += 1

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            attempt = 1
            while True:
                try:
                    return func(*args, **kwargs)
                except ProviderError as error:
                    if not is_retryable(error):
                        raise
                    if attempt >= max_retries:
                        exhausted(error)
                        raise
                    time.sleep(wait_for(error, attempt))
                    attempt += 1

        return wrapper  # type: ignore[return-value]

    return decorator


__all__ = [
    "DEFAULT_MAX_RETRIES",
    "MAX_RETRY_AFTER",
    "RETRYABLE_ERRORS",
    "call_with_retry",
    "is_retryable",
    "retry_wait",
    "with_retry",
]
