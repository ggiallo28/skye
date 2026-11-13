# Requirement 56.13
"""Use a blocking stdlib transport from async code: ``aiterate_blocking``.

The built-in providers talk over ``urllib``, which blocks. Their async transport hands the blocking
call to a worker thread
(``await asyncio.to_thread(...)`` for one answer, this module for a stream) so the event loop is
never blocked and the adapter
keeps one code path, the async one.

``aiterate_blocking(make_iterator)`` runs a blocking iterator in one worker thread and yields its
items in the caller's loop. The
iterator is made in that thread, so a ``ProviderError`` raised when the request opens reaches the
caller as it is.

Raises: whatever the iterator raises, in the caller, at the point where it happened.
Missing: nothing starts until the first item is asked for.
Concurrency: one thread for each stream. When the caller stops early the thread stops at the next
item, the iterator is closed in it
    and the generator waits for the thread before it ends, so nothing outlives the call.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncGenerator, Callable, Iterator
from typing import Any, TypeVar

_T = TypeVar("_T")


async def aiterate_blocking(make_iterator: Callable[[], Iterator[_T]]) -> AsyncGenerator[_T, None]:
    """Yield the items of the blocking iterator ``make_iterator()`` without blocking the event
    loop."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[bool, Any]] = asyncio.Queue()
    stop = threading.Event()

    def produce() -> None:
        chunks: Iterator[_T] | None = None
        try:
            chunks = make_iterator()
            for chunk in chunks:
                if stop.is_set():
                    break
                loop.call_soon_threadsafe(queue.put_nowait, (False, chunk))
        except BaseException as error:  # handed to the caller, raised there
            loop.call_soon_threadsafe(queue.put_nowait, (True, error))
            return
        finally:
            close = getattr(chunks, "close", None)
            if close is not None:
                close()
        loop.call_soon_threadsafe(queue.put_nowait, (True, None))

    producer = loop.run_in_executor(None, produce)
    try:
        while True:
            done, item = await queue.get()
            if done:
                if item is not None:
                    raise item
                return
            yield item
    finally:
        stop.set()
        await producer


__all__ = ["aiterate_blocking"]
