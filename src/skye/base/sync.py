# Requirement 56.13, decision D111
"""Run async code from sync code: ``run_sync`` and ``iterate_sync``.

A plugin author writes only the async method of a Port (``acomplete``, ``astream``, ``aencode``,
``invoke``). Skye derives the sync
method with these two functions, so no plugin keeps a second code path for the sync caller.

- ``run_sync(coroutine)`` runs a coroutine to completion and returns its result. With no event loop
  running it uses ``asyncio.run``. When a
  loop is already running (a notebook, a server) it runs the coroutine on its own loop in one worker
  thread and waits for it.
- ``iterate_sync(source)`` iterates an async iterable, usually an async generator, from sync code.
  One thread runs a loop of its own and
  pulls the items, so it also works inside a running loop. At most ``buffer`` items wait for the
  caller, plus the one the producer holds,
  so a slow caller never lets the producer run ahead.

Raises: whatever the coroutine or the async iterable raises, in the caller, at the point where it
happened (``iterate_sync`` hands over the
    items before the error first). ``ValidationError`` when ``buffer`` is below 1.
Missing: ``iterate_sync`` opens nothing until the first item is asked for; an iterator that is never
used never starts the generator. A
    generator that ignores its cancellation keeps its thread for as long as it runs; ``close`` waits
    for it at most ``_JOIN_SECONDS``.
Concurrency: each call uses its own loop and its own thread, so calls from many threads or tasks do
not share state. The caller blocks
    while it waits: from a running loop, prefer the async method.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import queue
import threading
from collections.abc import AsyncIterable, Coroutine, Iterator
from typing import Any, TypeVar

from skye.base.exceptions import ValidationError

_T = TypeVar("_T")

#: How long ``close`` waits for the thread of a stream to end.
_JOIN_SECONDS = 5.0

_ITEM, _ERROR, _DONE = "item", "error", "done"


def run_sync(coroutine: Coroutine[Any, Any, _T]) -> _T:
    """Run ``coroutine`` to completion from sync code, inside or outside a running event loop.

    Inside a running loop the coroutine runs on its own loop in one worker thread, which is joined
    before returning.

    Raises:
        Exception: Whatever the coroutine raises.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coroutine).result()


def iterate_sync(source: AsyncIterable[_T], *, buffer: int = 1) -> Iterator[_T]:
    """Iterate ``source`` from sync code, one item at a time.

    Args:
        source: An async iterable, usually an async generator.
        buffer: How many items may wait for the caller (1 or more).

    Returns:
        A sync iterator. Closing it, or letting it be collected, cancels the producer, closes the
        generator with ``aclose`` and ends the
        thread.

    Raises:
        ValidationError: ``buffer`` is below 1.
    """
    if buffer < 1:
        raise ValidationError("buffer must be 1 or more", field="buffer", value=buffer)
    return _iterate(source, buffer)


def _iterate(source: AsyncIterable[_T], buffer: int) -> Iterator[_T]:
    loop = asyncio.new_event_loop()
    out: queue.SimpleQueue[tuple[str, Any]] = queue.SimpleQueue()
    slots = asyncio.Semaphore(
        buffer
    )  # bound to the loop of the thread at its first use (Python 3.10 and later)
    task = loop.create_task(_pump(source, out, slots))
    thread = threading.Thread(
        target=_run_loop, args=(loop, task, source), name="skye-iterate-sync", daemon=True
    )
    thread.start()
    try:
        while True:
            kind, value = out.get()
            if kind == _ITEM:
                _release(loop, slots)
                yield value
            elif kind == _ERROR:
                raise value
            else:
                return
    finally:
        _stop(loop, task)
        thread.join(timeout=_JOIN_SECONDS)


async def _pump(
    source: AsyncIterable[_T], out: queue.SimpleQueue[tuple[str, Any]], slots: asyncio.Semaphore
) -> None:
    """Move the items to the caller, never more than the semaphore allows; an error goes to the
    caller as a message."""
    try:
        async for item in source:
            await slots.acquire()
            out.put((_ITEM, item))
        out.put((_DONE, None))
    except Exception as error:  # a cancellation is a BaseException and goes on
        out.put((_ERROR, error))


def _run_loop(
    loop: asyncio.AbstractEventLoop, task: asyncio.Task[None], source: AsyncIterable[Any]
) -> None:
    asyncio.set_event_loop(loop)
    try:
        try:
            loop.run_until_complete(task)
        except asyncio.CancelledError:
            pass
        finally:
            loop.run_until_complete(_aclose(source))
            loop.run_until_complete(loop.shutdown_asyncgens())
    finally:
        loop.close()


async def _aclose(source: AsyncIterable[Any]) -> None:
    close = getattr(source, "aclose", None)
    if close is not None:
        await close()


def _release(loop: asyncio.AbstractEventLoop, slots: asyncio.Semaphore) -> None:
    try:
        loop.call_soon_threadsafe(slots.release)
    except RuntimeError:  # the loop is closed: the producer has ended
        pass


def _stop(loop: asyncio.AbstractEventLoop, task: asyncio.Task[None]) -> None:
    try:
        loop.call_soon_threadsafe(task.cancel)
    except RuntimeError:  # the loop is closed: the producer has ended
        pass


__all__ = ["iterate_sync", "run_sync"]
