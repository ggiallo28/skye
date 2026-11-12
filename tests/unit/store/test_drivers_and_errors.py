"""PostgreSQL driver chain (D100), factory and registry (D98), missing extras (D99), errors."""

from __future__ import annotations

import asyncio
import sys
from typing import Any

import pytest

from skye.base.exceptions import (
    ConfigurationError,
    MissingExtraError,
    ProviderError,
    ValidationError,
)
from skye.store import (
    DynamoDBBackend,
    InMemoryBackend,
    PostgreSQLBackend,
    RedisBackend,
    available_backends,
    backend,
    register_backend,
)
from skye.base.plugins import Registrar
from skye.store import plugins as store_plugin
from skye.store import factory as factory_module
from skye.store.plugins.postgres import backend as postgres
from skye.store.plugins.redis import backend as redis_module
from skye.store.plugins.postgres.backend import (
    AsyncpgExecutor,
    DataApiExecutor,
    Pg8000Executor,
    choose_driver,
    connection_arguments,
    positional,
    statements,
)

# --- PostgreSQL driver chain
# -------------------------------------------------------------------------------------------------


def test_data_api_comes_first_when_the_arns_are_given(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(postgres.importlib.util, "find_spec", lambda name: object())
    assert choose_driver("postgresql://h/db", "arn:cluster", "arn:secret") == "data-api"


@pytest.mark.parametrize(
    ("installed", "expected"),
    [({"pg8000", "asyncpg"}, "pg8000"), ({"asyncpg"}, "asyncpg"), ({"pg8000"}, "pg8000")],
)
def test_pg8000_then_asyncpg(
    monkeypatch: pytest.MonkeyPatch, installed: set[str], expected: str
) -> None:
    monkeypatch.setattr(
        postgres.importlib.util, "find_spec", lambda name: object() if name in installed else None
    )
    assert choose_driver("postgresql://h/db", None, None) == expected


def test_no_driver_names_the_extras(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(postgres.importlib.util, "find_spec", lambda name: None)
    with pytest.raises(MissingExtraError) as caught:
        choose_driver("postgresql://h/db", None, None)
    assert caught.value.extra == "postgres"
    assert "postgres-asyncpg" in "".join(caught.value.__notes__) and "Data API" in "".join(
        caught.value.__notes__
    )


def test_backend_needs_a_dsn_or_the_arns() -> None:
    with pytest.raises(ValidationError):
        PostgreSQLBackend()
    with pytest.raises(ValidationError):
        PostgreSQLBackend("postgresql://h/db", "bad name; drop table x")


def test_forced_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    assert PostgreSQLBackend("postgresql://h/db", driver="asyncpg").driver == "asyncpg"
    assert (
        PostgreSQLBackend(cluster_arn="a", secret_arn="s", driver="data-api").driver == "data-api"
    )
    with pytest.raises(ValidationError):
        PostgreSQLBackend("postgresql://h/db", driver="data-api")


def test_statements_use_named_parameters_and_no_double_colon_casts() -> None:
    for name, sql in statements("app.state").items():
        assert "::" not in sql, name
        assert "app.state" in sql, name


def test_positional_numbers_each_name_once() -> None:
    sql, values = positional(
        "SELECT :a, :b, :a, ':x' FROM t WHERE c LIKE :p ESCAPE '\\'", {"a": 1, "b": 2, "p": "z%"}
    )
    assert sql == "SELECT $1, $2, $1, ':x' FROM t WHERE c LIKE $3 ESCAPE '\\'"
    assert values == [1, 2, "z%"]


def test_connection_arguments() -> None:
    args = connection_arguments(
        "postgresql://us%40er:p%3Ass@db.example.com:6543/app?sslmode=require"
    )
    assert args == {
        "user": "us@er",
        "password": "p:ss",
        "host": "db.example.com",
        "port": 6543,
        "database": "app",
        "ssl_context": True,
    }
    with pytest.raises(ValidationError):
        connection_arguments("mysql://h/db")


class RecordingDataApi:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def execute_statement(self, **request: Any) -> dict[str, Any]:
        self.requests.append(request)
        return {"formattedRecords": '[{"count": 3}]'}


def test_data_api_executor_types_the_parameters() -> None:
    client = RecordingDataApi()
    executor = DataApiExecutor("arn:c", "arn:s", "app", None, client=client)
    rows = asyncio.run(executor.run("x", "SQL", {"k": "a", "n": 2, "f": 1.5, "z": None, "b": True}))
    assert rows == [{"count": 3}]
    request = client.requests[0]
    assert (
        request["resourceArn"] == "arn:c"
        and request["database"] == "app"
        and request["formatRecordsAs"] == "JSON"
    )
    assert request["parameters"] == [
        {"name": "k", "value": {"stringValue": "a"}},
        {"name": "n", "value": {"longValue": 2}},
        {"name": "f", "value": {"doubleValue": 1.5}},
        {"name": "z", "value": {"isNull": True}},
        {"name": "b", "value": {"booleanValue": True}},
    ]


class FakePg8000:
    class Connection:
        instances: list[Any] = []

        def __init__(self, **kwargs: Any) -> None:
            self.kwargs, self.calls, self.closed = kwargs, [], False
            self.columns: list[dict[str, str]] = []
            FakePg8000.Connection.instances.append(self)

        def run(self, sql: str, **params: Any) -> list[list[Any]]:
            self.calls.append((sql, params))
            self.columns = [{"name": "count"}]
            return [[7]]

        def close(self) -> None:
            self.closed = True


def test_pg8000_executor_passes_named_parameters_and_maps_columns() -> None:
    executor = Pg8000Executor("postgresql://u@h/db", module=FakePg8000)
    assert asyncio.run(executor.run("x", "SELECT :a", {"a": 1})) == [{"count": 7}]
    connection = FakePg8000.Connection.instances[-1]
    assert connection.kwargs == {"user": "u", "host": "h", "database": "db"}
    assert connection.calls == [("SELECT :a", {"a": 1})]
    asyncio.run(executor.close())
    assert connection.closed


class FakeAsyncpg:
    def __init__(self) -> None:
        self.fetches: list[tuple[str, tuple[Any, ...]]] = []

    async def connect(self, dsn: str) -> Any:
        outer = self

        class Connection:
            async def fetch(self, sql: str, *values: Any) -> list[dict[str, Any]]:
                outer.fetches.append((sql, values))
                return [{"key": "a"}]

            async def close(self) -> None:
                pass

        return Connection()


def test_asyncpg_executor_uses_positional_parameters() -> None:
    module = FakeAsyncpg()
    executor = AsyncpgExecutor("postgresql://u@h/db", module=module)
    assert asyncio.run(executor.run("x", "SELECT :a, :b", {"a": 1, "b": "x"})) == [{"key": "a"}]
    assert module.fetches == [("SELECT $1, $2", (1, "x"))]


# --- Factory and registry


def test_backend_by_name() -> None:
    assert isinstance(backend("memory"), InMemoryBackend)
    assert isinstance(backend("dynamodb", table_name="t"), DynamoDBBackend)
    assert set(available_backends()) >= {
        "memory",
        "file",
        "dynamodb",
        "redis",
        "postgres",
        "durable_function",
    }
    with pytest.raises(ConfigurationError, match="known: "):
        backend("nope")


def test_register_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    # Work on a private registrar so that replacing "memory" below does not leak into the default one.
    private = Registrar()
    store_plugin.register(private)
    monkeypatch.setattr(factory_module, "_registrar", lambda: private)
    register_backend("mine", lambda **config: InMemoryBackend())
    assert isinstance(backend("mine"), InMemoryBackend)
    with pytest.raises(ConfigurationError, match="already registered"):
        register_backend("mine", InMemoryBackend)
    with pytest.raises(ConfigurationError, match="already registered"):
        register_backend("memory", InMemoryBackend)
    register_backend("memory", lambda **config: "replaced", replace=True)  # type: ignore[arg-type, return-value]
    assert backend("memory") == "replaced"


# --- Missing extras and wrapped errors
# ---------------------------------------------------------------------------------------


def test_missing_boto3_names_the_aws_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "boto3", None)
    with pytest.raises(MissingExtraError) as caught:
        asyncio.run(DynamoDBBackend("t").get("k"))
    assert caught.value.extra == "aws"


def test_missing_redis_and_valkey_names_the_valkey_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("redis", "redis.asyncio", "valkey", "valkey.asyncio"):
        monkeypatch.setitem(sys.modules, name, None)
    with pytest.raises(MissingExtraError) as caught:
        asyncio.run(RedisBackend("redis://:secret@h:6379/0").get("k"))
    assert caught.value.extra == "valkey"
    assert "skyeai[redis]" in "".join(caught.value.__notes__)


def _fake_driver(created: list[str], name: str) -> Any:
    class Module:
        @staticmethod
        def from_url(url: str) -> Any:
            created.append(name)
            from tests.unit.store.fakes import FakeRedis

            return FakeRedis(lambda: 0.0)

    return Module


@pytest.mark.parametrize(
    ("installed", "forced", "expected"),
    [
        ({"valkey", "redis"}, None, "valkey"),
        ({"redis"}, None, "redis"),
        ({"valkey"}, None, "valkey"),
        ({"valkey", "redis"}, "redis", "redis"),
    ],
)
def test_valkey_then_redis(
    monkeypatch: pytest.MonkeyPatch, installed: set[str], forced: Any, expected: str
) -> None:
    created: list[str] = []
    for name in ("valkey", "redis"):
        if name in installed:
            monkeypatch.setitem(sys.modules, name, _fake_driver(created, name))
            monkeypatch.setitem(sys.modules, f"{name}.asyncio", _fake_driver(created, name))
        else:
            monkeypatch.setitem(sys.modules, name, None)
            monkeypatch.setitem(sys.modules, f"{name}.asyncio", None)
    real_find_spec = redis_module.importlib.util.find_spec
    monkeypatch.setattr(
        redis_module.importlib.util,
        "find_spec",
        lambda name: (
            object()
            if name in installed
            else real_find_spec(name) if name not in ("valkey", "redis") else None
        ),
    )
    store = RedisBackend("redis://h:6379/0", driver=forced)
    asyncio.run(store.set("k", {"v": 1}))
    assert created == [expected] and store.driver == expected


def test_valkey_is_a_second_name_for_the_redis_backend() -> None:
    assert type(backend("valkey", redis_url="redis://h:6379/0")) is RedisBackend


class Broken:
    def __getattr__(self, name: str) -> Any:
        async def fail(*args: Any, **kwargs: Any) -> Any:
            raise ConnectionError("redis://:hunter2@h refused")

        return fail


def test_client_errors_become_provider_errors_without_secrets() -> None:
    with pytest.raises(ProviderError) as caught:
        asyncio.run(RedisBackend(client=Broken()).get("k"))
    assert "redis: get failed (ConnectionError)" in str(caught.value)
    assert "hunter2" not in str(caught.value)
    assert isinstance(caught.value.__cause__, ConnectionError)


def test_count_errors_name_the_operation_without_secrets() -> None:
    with pytest.raises(ProviderError) as caught:
        asyncio.run(RedisBackend(client=Broken()).count("k"))
    assert "redis: count failed (ConnectionError)" in str(caught.value)
    assert "hunter2" not in str(caught.value)


def test_count_validates_the_key_before_any_call() -> None:
    from skye.base.exceptions import ValidationError

    with pytest.raises(ValidationError):
        asyncio.run(RedisBackend(client=Broken()).count(""))


def test_dynamodb_rejects_its_reserved_attributes() -> None:
    from tests.unit.store.fakes import FakeDynamoResource

    store = DynamoDBBackend("t", resource=FakeDynamoResource())
    with pytest.raises(ValidationError):
        asyncio.run(store.set("k", {"pk": "x"}))


def test_dynamodb_has_no_default_region(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    class Boto3:
        @staticmethod
        def resource(service: str, **kwargs: Any) -> Any:
            calls.append(kwargs)
            from tests.unit.store.fakes import FakeDynamoResource

            return FakeDynamoResource()

    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.setitem(sys.modules, "boto3", Boto3)
    asyncio.run(DynamoDBBackend("t").connect())
    asyncio.run(DynamoDBBackend("t", "eu-west-1").connect())
    assert calls == [{}, {"region_name": "eu-west-1"}]
