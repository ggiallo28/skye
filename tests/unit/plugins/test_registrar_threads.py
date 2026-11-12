"""A registration is safe from any thread, and a read takes no lock (Requirement 56.6, task 14.2 of the plugins spec).

A write takes a lock and publishes a new copy of the table of its kind; a read uses a table that is never changed after it is published.
These tests start threads together with a barrier, so the registrations really race, and they never depend on how long something takes:
a thread that must wait is held by an event.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

import pytest

from skye.base.exceptions import ConfigurationError
from skye.base.plugins import KINDS, Plugins, Registrar
from skye.base.profile import ProviderProfile

THREADS = 16
WAIT = 10  # seconds a test waits for a thread before it fails; a pass takes milliseconds


def run_together(jobs: list[Callable[[], Any]]) -> tuple[list[Any], list[BaseException | None]]:
    """Run the jobs in threads that start at once; return their results and errors, in the order of the jobs."""
    barrier = threading.Barrier(len(jobs))
    results: list[Any] = [None] * len(jobs)
    errors: list[BaseException | None] = [None] * len(jobs)

    def work(index: int) -> None:
        barrier.wait(WAIT)
        try:
            results[index] = jobs[index]()
        except BaseException as exc:  # noqa: BLE001 - the test reports it
            errors[index] = exc

    threads = [threading.Thread(target=work, args=(i,)) for i in range(len(jobs))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(WAIT)
    assert not any(thread.is_alive() for thread in threads), "a thread did not finish"
    return results, errors


def test_distinct_names_from_many_threads_are_all_registered_in_every_kind():
    registrar = Registrar()

    def register_everywhere(index: int) -> Callable[[], None]:
        def job() -> None:
            for kind in KINDS:
                # a provider whose object says nothing needs the function
                options = {"function": "model"} if kind == "provider" else {}
                getattr(registrar, kind)(f"{kind}-{index}", object(), **options)

        return job

    _, errors = run_together([register_everywhere(i) for i in range(THREADS)])

    assert errors == [None] * THREADS
    for kind in KINDS:
        assert registrar.names(kind) == sorted(f"{kind}-{i}" for i in range(THREADS))


def test_one_name_raced_by_many_threads_has_one_winner_and_the_others_raise():
    registrar = Registrar()
    targets = [object() for _ in range(THREADS)]

    _, errors = run_together([lambda t=t: registrar.agent("same", t) for t in targets])

    winners = [i for i, error in enumerate(errors) if error is None]
    assert len(winners) == 1
    assert all(isinstance(e, ConfigurationError) for e in errors if e is not None)
    assert registrar.get("agent", "same") is targets[winners[0]]
    assert registrar.names("agent") == ["same"]


def test_replace_from_many_threads_leaves_one_entry_and_no_error():
    registrar = Registrar()
    registrar.agent("same", object())
    targets = [object() for _ in range(THREADS)]

    _, errors = run_together(
        [lambda t=t: registrar.agent("same", t, replace=True) for t in targets]
    )

    assert errors == [None] * THREADS
    assert registrar.names("agent") == ["same"]
    assert any(registrar.get("agent", "same") is t for t in targets)


def test_different_profiles_for_one_provider_have_one_winner():
    registrar = Registrar()
    profiles = [
        ProviderProfile("acme", default_api_base=f"https://{i}.example") for i in range(THREADS)
    ]

    _, errors = run_together(
        [lambda p=p: registrar.provider("acme", object(), profile=p, function="model") for p in profiles]
    )

    winners = [i for i, error in enumerate(errors) if error is None]
    assert len(winners) == 1
    assert registrar.get_profile("acme") == profiles[winners[0]]
    assert registrar.names("provider", "model") == ["acme"]


def test_a_reader_sees_a_table_that_only_grows_while_threads_register():
    registrar = Registrar()
    total = THREADS * 25
    done = threading.Event()
    seen: list[list[str]] = []

    def read() -> None:
        while not done.is_set():
            seen.append(registrar.names("tokenizer"))
        seen.append(registrar.names("tokenizer"))

    reader = threading.Thread(target=read)
    reader.start()

    def write(index: int) -> Callable[[], None]:
        def job() -> None:
            for n in range(25):
                registrar.tokenizer(f"t-{index}-{n}", object())

        return job

    _, errors = run_together([write(i) for i in range(THREADS)])
    done.set()
    reader.join(WAIT)

    assert not reader.is_alive()
    assert errors == [None] * THREADS
    sizes = [len(names) for names in seen]
    assert sizes == sorted(sizes), "a reader saw the table shrink"
    assert all(names == sorted(set(names)) for names in seen), (
        "a reader saw a duplicate or an unsorted list"
    )
    assert sizes[-1] == total


def test_a_registration_from_a_function_a_method_and_a_thread_is_found_at_once_by_another_thread():
    registrar = Registrar()
    plugins = Plugins(registrar=registrar)
    registered = threading.Event()
    found: list[bool] = []

    def from_a_function() -> None:
        @plugins.agent("from-function")
        class FromFunction:  # noqa: B903
            pass

    class App:
        def start(self) -> None:
            @plugins.agent("from-method")
            class FromMethod:  # noqa: B903
                pass

    def from_a_thread() -> None:
        from_a_function()
        App().start()
        registered.set()

    def observe() -> None:
        assert registered.wait(WAIT)
        found.append(
            registrar.has("agent", "from-function") and registrar.has("agent", "from-method")
        )
        found.append(isinstance(registrar.get("agent", "from-method"), type))

    run_together([from_a_thread, observe])

    assert found == [True, True]
    assert registrar.names("agent") == ["from-function", "from-method"]


def test_a_read_does_not_take_the_write_lock_and_a_write_does():
    registrar = Registrar()
    registrar.agent("a", object())
    reads_done = threading.Event()
    write_done = threading.Event()

    def reads() -> None:
        registrar.names("agent")
        registrar.has("agent", "a")
        registrar.get("agent", "a")
        registrar.get_profile("acme")
        registrar.default_set("template_filter")
        reads_done.set()

    def write() -> None:
        registrar.agent("b", object())
        write_done.set()

    with registrar._write_lock:
        reader = threading.Thread(target=reads)
        writer = threading.Thread(target=write)
        reader.start()
        writer.start()
        assert reads_done.wait(WAIT), "a read waited for the write lock"
        assert not write_done.wait(0.2), "a write went through while the lock was held"
    assert write_done.wait(WAIT)
    reader.join(WAIT)
    writer.join(WAIT)
    assert registrar.names("agent") == ["a", "b"]


class Gate:
    """Events that the slow built-in and the slow scan use to hold a thread in the middle of the loading."""

    started = threading.Event()
    release = threading.Event()
    calls = 0


def slow_builtin(registrar: Registrar) -> None:
    registrar.agent("first", object())
    Gate.started.set()
    assert Gate.release.wait(WAIT)
    registrar.agent("second", object())


def slow_discover(registrar: Registrar) -> None:
    Gate.calls += 1
    Gate.started.set()
    assert Gate.release.wait(WAIT)
    registrar.agent("late", object())


@pytest.fixture
def gate():
    Gate.started = threading.Event()
    Gate.release = threading.Event()
    Gate.calls = 0
    yield Gate
    Gate.release.set()


def test_a_thread_waits_for_the_built_ins_that_another_thread_is_loading(gate):
    registrar = Registrar(builtin_plugins=(f"{__name__}:slow_builtin",))
    results: list[list[str]] = []

    first = threading.Thread(target=lambda: results.append(registrar.names("agent")))
    first.start()
    assert gate.started.wait(WAIT)
    others = [
        threading.Thread(target=lambda: results.append(registrar.names("agent"))) for _ in range(4)
    ]
    for thread in others:
        thread.start()
    for thread in others:
        thread.join(0.2)
    assert all(thread.is_alive() for thread in others), "a reader saw half of the built-ins"

    gate.release.set()
    for thread in [first, *others]:
        thread.join(WAIT)

    assert results == [["first", "second"]] * 5


def test_the_scan_runs_once_and_the_threads_that_need_it_wait_for_it(gate, monkeypatch):
    monkeypatch.setattr("skye.base.plugins.DISCOVER", f"{__name__}:slow_discover")
    registrar = Registrar(scan=True)
    found: list[Any] = []
    target = object()
    registrar.agent("early", target)

    jobs = [
        threading.Thread(
            target=lambda: found.append(
                registrar.has("agent", "late") or registrar.get("agent", "late")
            )
        )
        for _ in range(8)
    ]
    for thread in jobs:
        thread.start()
    assert gate.started.wait(WAIT)
    for thread in jobs:
        thread.join(0.1)
    gate.release.set()
    for thread in jobs:
        thread.join(WAIT)

    assert not any(thread.is_alive() for thread in jobs)
    assert len(found) == 8 and all(item is not None for item in found)
    assert gate.calls == 1
    assert registrar.has("agent", "late")


def test_the_handle_adds_no_second_write_path(monkeypatch):
    registrar = Registrar()
    plugins = Plugins(registrar=registrar)
    writes: list[tuple[str, str]] = []
    original = registrar._register

    def counting(kind: str, name: str, *args: Any, **kwargs: Any) -> None:
        writes.append((kind, name))
        original(kind, name, *args, **kwargs)

    monkeypatch.setattr(registrar, "_register", counting)

    plugins.agent("direct", object)

    @plugins.agent("decorated")
    class Decorated:  # noqa: B903
        pass

    assert writes == [("agent", "direct"), ("agent", "decorated")]
    assert not any("lock" in name for name in vars(plugins))
