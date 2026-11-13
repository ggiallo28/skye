# Requirement 12, D110, decisions D96, D99, D97, D100, D98
"""The state stores: one small interface and six backends behind it.

**The interface.** What a component asks of a store is five Ports. They are defined in
``skye.base.interfaces.storage`` and exported from here, so ``from skye.store import KeyValueStore`` is
enough::

    KeyValueStore    get, set, delete, get_multiple, set_multiple
    CounterStore     increment (atomic), count
    ExpiryStore      is_alive, remaining
    ScanStore        keys(prefix, limit)
    StorageBackend   key-value plus counter, with connect and close: the base class of every backend

A value is a JSON object (``dict``) under a non-empty ``str`` key, with an optional time to live in
seconds. Every method is ``async``. A component asks only for the Port it uses (the router asks for
``CounterStore``), so a backend that lacks one is still usable for the rest.

**The backends.** Each is in its own folder of ``store/plugins`` and imports its driver on first use:
``InMemoryBackend`` (the default), ``FileSystemBackend``, ``DynamoDBBackend`` (boto3), ``RedisBackend``,
``PostgreSQLBackend`` and ``DurableFunctionBackend`` (the caller's durable context; no ``ScanStore``).

**Build, share, check.**
``backend(name, **config)`` builds one by name and ``available_backends()`` lists the names;
``register_backend`` adds one from outside Skye (a plugin does the same with ``skye.Plugins().backend``);
``namespaced(store, prefix)`` gives each component its own keys over one store (the router takes
``"router"``); ``check_backend`` (from ``skye.store.conformance``) runs the offline checks on any
backend, with ``FakeClock`` to move time.

Codename: lake.
"""

from skye.base.interfaces.storage import (
    CounterStore,
    ExpiryStore,
    KeyValueStore,
    ScanStore,
    StorageBackend,
)
from skye.store.conformance import FakeClock, check_backend
from skye.store.plugins.durable_function import DurableFunctionBackend
from skye.store.plugins.dynamodb import DynamoDBBackend
from skye.store.factory import available_backends, backend, register_backend
from skye.store.namespace import namespaced
from skye.store.plugins.file import FileSystemBackend
from skye.store.plugins.memory import InMemoryBackend
from skye.store.plugins.postgres import PostgreSQLBackend
from skye.store.plugins.redis import RedisBackend

__all__ = [
    # the interface
    "StorageBackend",
    "KeyValueStore",
    "CounterStore",
    "ExpiryStore",
    "ScanStore",
    # build, share and check
    "backend",
    "register_backend",
    "available_backends",
    "namespaced",
    "check_backend",
    "FakeClock",
    # the backends
    "InMemoryBackend",
    "FileSystemBackend",
    "DynamoDBBackend",
    "RedisBackend",
    "PostgreSQLBackend",
    "DurableFunctionBackend",
]
