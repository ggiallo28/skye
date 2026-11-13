# Requirement 12, D110, decisions D96, D99, D97, D100, D98
"""Shared store Component: the state backends behind the storage Ports.

Six backends, each in its own folder of ``store/plugins``, with its driver imported only on first
use:
``InMemoryBackend`` (the default), ``FileSystemBackend``, ``DynamoDBBackend`` (boto3; extra
``aws`` outside Lambda),
``RedisBackend`` (extra ``redis``), ``PostgreSQLBackend`` (RDS Data API, then pg8000 with extra
``postgres``, then asyncpg with
extra ``postgres-asyncpg``) and ``DurableFunctionBackend`` (the caller's durable context).
``backend(name, **config)``
builds one by name, ``register_backend`` adds one from outside Skye, and ``check_backend`` (from
``skye.store.conformance``) checks any backend. ``namespaced(store, prefix)`` gives each component its own
namespace over one store (the router takes ``"router"``, and the memory and the agents will take theirs).

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
    "StorageBackend",
    "KeyValueStore",
    "CounterStore",
    "ExpiryStore",
    "ScanStore",
    "InMemoryBackend",
    "FileSystemBackend",
    "DynamoDBBackend",
    "RedisBackend",
    "PostgreSQLBackend",
    "DurableFunctionBackend",
    "backend",
    "register_backend",
    "available_backends",
    "namespaced",
    "check_backend",
    "FakeClock",
]
