"""Unit tests for ``run_sync`` and ``iterate_sync`` (Requirement 56.13, decision D111)."""

import asyncio
import gc
import threading
import time

import pytest

from skye.base.exceptions import ValidationError
from skye.base.sync import iterate_sync, run_sync

THREAD_NAME = "skye-iterate-sync"


def _stream_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == THREAD_NAME and t.is_alive()]


async def _numbers(count: int):
    for number in range(count):
        yield number


class TestRunSync:
    def test_returns_the_result_with_no_loop(self):
        async def value() -> int:
            return 7

        assert run_sync(value()) == 7

    def test_runs_on_another_thread_inside_a_running_loop(self):
        async def where() -> int:
            return threading.get_ident()

        async def outer() -> tuple[int, int]:
            return threading.get_ident(), run_sync(where())

        outer_id, inner_id = asyncio.run(outer())
        assert inner_id != outer_id

    def test_raises_what_the_coroutine_raises(self):
        async def fail() -> None:
            raise KeyError("boom")

        with pytest.raises(KeyError):
            run_sync(fail())

    def test_raises_inside_a_running_loop_too(self):
        async def fail() -> None:
            raise KeyError("boom")

        async def outer() -> None:
            run_sync(fail())

        with pytest.raises(KeyError):
            asyncio.run(outer())


class TestIterateSync:
    def test_gives_the_items_in_order(self):
        assert list(iterate_sync(_numbers(20))) == list(range(20))

    def test_works_with_an_async_iterable_that_is_not_a_generator(self):
        class Source:
            def __aiter__(self):
                return _numbers(3).__aiter__()

        assert list(iterate_sync(Source())) == [0, 1, 2]

    def test_works_inside_a_running_loop(self):
        async def outer() -> list[int]:
            return list(iterate_sync(_numbers(5)))

        assert asyncio.run(outer()) == [0, 1, 2, 3, 4]

    def test_an_error_in_the_middle_comes_after_the_items_before_it(self):
        closed: list[bool] = []

        async def broken():
            try:
                yield 1
                yield 2
                raise RuntimeError("stream failed")
            finally:
                closed.append(True)

        seen: list[int] = []
        with pytest.raises(RuntimeError, match="stream failed"):
            for item in iterate_sync(broken()):
                seen.append(item)
        assert seen == [1, 2]
        assert closed == [True]
        assert _stream_threads() == []

    def test_an_early_stop_closes_the_generator_and_ends_the_thread(self):
        closed: list[bool] = []

        async def endless():
            try:
                number = 0
                while True:
                    yield number
                    number += 1
            finally:
                closed.append(True)

        iterator = iterate_sync(endless())
        assert next(iterator) == 0
        assert next(iterator) == 1
        iterator.close()
        assert closed == [True]
        assert _stream_threads() == []

    def test_dropping_the_iterator_closes_the_generator(self):
        closed: list[bool] = []

        async def endless():
            try:
                while True:
                    yield 1
            finally:
                closed.append(True)

        iterator = iterate_sync(endless())
        next(iterator)
        del iterator
        gc.collect()
        assert closed == [True]
        assert _stream_threads() == []

    def test_a_break_in_a_for_loop_ends_it(self):
        async def endless():
            while True:
                yield 1

        for _ in iterate_sync(endless()):
            break
        gc.collect()
        assert _stream_threads() == []

    def test_a_slow_caller_does_not_let_the_producer_run_ahead(self):
        produced: list[int] = []

        async def counting():
            number = 0
            while True:
                produced.append(number)
                yield number
                number += 1

        iterator = iterate_sync(counting(), buffer=2)
        assert next(iterator) == 0
        time.sleep(0.3)
        # one taken, two waiting, one in the hands of the producer
        assert len(produced) <= 1 + 2 + 1
        assert len(produced) >= 2
        iterator.close()

    def test_nothing_starts_until_the_first_item_is_asked_for(self):
        started: list[bool] = []

        async def source():
            started.append(True)
            yield 1

        iterator = iterate_sync(source())
        time.sleep(0.05)
        assert started == []
        assert _stream_threads() == []
        assert list(iterator) == [1]

    def test_no_thread_is_left_after_a_full_run(self):
        assert list(iterate_sync(_numbers(3))) == [0, 1, 2]
        assert _stream_threads() == []

    def test_a_buffer_below_one_is_refused(self):
        with pytest.raises(ValidationError):
            iterate_sync(_numbers(1), buffer=0)

    def test_an_empty_stream_ends_at_once(self):
        assert list(iterate_sync(_numbers(0))) == []
