# decision D100
"""PostgreSQL backend with three optional drivers, chosen in order.

1. The **RDS Data API** through ``boto3`` when ``cluster_arn`` and ``secret_arn`` are given: HTTP
   calls, no connection to manage, IAM
   authorization, nothing to install in Lambda (extra ``aws`` elsewhere). Aurora only.
2. **pg8000** when installed (extra ``postgres``): pure Python, any PostgreSQL; synchronous, so it
   runs in a worker thread.
3. **asyncpg** when installed (extra ``postgres-asyncpg``): compiled, the fastest.

``driver="data-api" | "pg8000" | "asyncpg"`` forces one. The table (created on first use) is
``key TEXT PRIMARY KEY, data JSONB, expires_at DOUBLE PRECISION`` (seconds since the epoch). Every
statement is written once with
``:name`` parameters, so no value is ever put into the SQL text, and the table name is checked as an
identifier.

Example:
    >>> from skye.store import PostgreSQLBackend
    >>> store = PostgreSQLBackend("postgresql://app@db.example.com/app")  # doctest: +SKIP
    >>> aurora = PostgreSQLBackend(
    ...     cluster_arn="arn:aws:rds:...", secret_arn="arn:aws:secretsmanager:...", database="app"
    ... )

Raises: ``ValidationError`` for an invalid key, value, time to live or table name;
    ``MissingExtraError`` when no driver is available;
    ``ProviderError`` naming the operation when a statement fails. The connection string is never
    put in an error or a log.
Missing: an absent or expired row reads as ``None``.
Concurrency: ``increment`` is one ``INSERT ... ON CONFLICT DO UPDATE ... RETURNING``, atomic across
    processes; the pg8000 and
    asyncpg drivers use one connection per backend, guarded by a lock.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import re
from typing import Any, Literal, Protocol
from urllib.parse import unquote, urlsplit

from skye.base.exceptions import MissingExtraError, ValidationError
from skye.base.interfaces.storage import (
    ExpiryStore,
    ScanStore,
    StorageBackend,
    check_key,
    check_ttl,
)
from skye.base.lazy_import import missing_extra
from skye.base.regions import region_for
from skye.store._common import (
    Clock,
    check_data,
    check_items,
    check_limit,
    count_of,
    default_clock,
    expiry_of,
    like_prefix,
    provider_errors,
    remaining_of,
)

Driver = Literal["data-api", "pg8000", "asyncpg"]
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}(\.[A-Za-z_][A-Za-z0-9_]{0,62})?$")
#: A quoted SQL string (left as it is) or a ``:name`` parameter outside one.
_PARAM = re.compile(r"'(?:[^']|'')*'|(?<![:\w]):([A-Za-z_]\w*)")


def statements(table: str) -> dict[str, str]:
    """The SQL of every operation for ``table``.

    Parameters are ``:name`` and there is no ``::`` cast, which pg8000 and the Data API
    would read as a parameter.
    """
    live = "(expires_at IS NULL OR expires_at > :now)"
    return {
        "create": (
            f"CREATE TABLE IF NOT EXISTS {table} "
            "(key TEXT PRIMARY KEY, data JSONB NOT NULL, expires_at DOUBLE PRECISION)"
        ),
        "get": f"SELECT CAST(data AS TEXT) AS data FROM {table} WHERE key = :key AND {live}",
        "set": (
            f"INSERT INTO {table} (key, data, expires_at) "
            "VALUES (:key, CAST(:data AS JSONB), :exp) "
            "ON CONFLICT (key) DO UPDATE SET data = EXCLUDED.data, expires_at = EXCLUDED.expires_at"
        ),
        "delete": f"DELETE FROM {table} WHERE key = :key RETURNING {live} AS live",
        "increment": (
            f"INSERT INTO {table} AS s (key, data, expires_at) "
            "VALUES (:key, jsonb_build_object('count', CAST(:amount AS BIGINT)), :exp) "
            "ON CONFLICT (key) DO UPDATE SET data = jsonb_build_object('count', "
            "CASE WHEN s.expires_at IS NOT NULL AND s.expires_at <= :now THEN 0 "
            "ELSE COALESCE(CAST(s.data->>'count' AS BIGINT), 0) END + CAST(:amount AS BIGINT)), "
            "expires_at = EXCLUDED.expires_at "
            "RETURNING CAST(data->>'count' AS BIGINT) AS count"
        ),
        "expiry": f"SELECT expires_at FROM {table} WHERE key = :key AND {live}",
        "keys": (
            f"SELECT key FROM {table} WHERE key LIKE :pattern ESCAPE '\\' AND {live} ORDER BY key"
        ),
    }


class _Executor(Protocol):
    """One driver: run a named statement with ``:name`` parameters and return the rows as dicts."""

    async def run(self, name: str, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]: ...

    async def close(self) -> None: ...


class DataApiExecutor:
    """The RDS Data API through ``boto3`` (``rds-data``); results come back as JSON records."""

    def __init__(
        self,
        cluster_arn: str,
        secret_arn: str,
        database: str | None,
        region_name: str | None,
        client: Any = None,
    ) -> None:
        """Remember the ARNs; the client is created on first use."""
        self._cluster_arn = cluster_arn
        self._secret_arn = secret_arn
        self._database = database
        self._region_name = region_name
        self._client = client

    @staticmethod
    def parameter(name: str, value: Any) -> dict[str, Any]:
        """A Data API parameter for one Python value."""
        if value is None:
            return {"name": name, "value": {"isNull": True}}
        if isinstance(value, bool):
            return {"name": name, "value": {"booleanValue": value}}
        if isinstance(value, int):
            return {"name": name, "value": {"longValue": value}}
        if isinstance(value, float):
            return {"name": name, "value": {"doubleValue": value}}
        return {"name": name, "value": {"stringValue": str(value)}}

    async def run(self, name: str, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        """``ExecuteStatement`` in a worker thread."""
        if self._client is None:
            boto3 = missing_extra("boto3", extra="aws")
            region = region_for("bedrock", self._region_name, required=False)
            kwargs = {"region_name": region} if region else {}
            self._client = boto3.client("rds-data", **kwargs)
        request: dict[str, Any] = {
            "resourceArn": self._cluster_arn,
            "secretArn": self._secret_arn,
            "sql": sql,
            "parameters": [self.parameter(k, v) for k, v in params.items()],
            "formatRecordsAs": "JSON",
        }
        if self._database:
            request["database"] = self._database
        response = await asyncio.to_thread(self._client.execute_statement, **request)
        records = response.get("formattedRecords")
        return list(json.loads(records)) if records else []

    async def close(self) -> None:
        """Nothing to release: the Data API has no connection."""


def connection_arguments(dsn: str) -> dict[str, Any]:
    """The keyword arguments of ``pg8000.native.Connection`` for a ``postgresql://`` URL."""
    parts = urlsplit(dsn)
    if parts.scheme not in ("postgres", "postgresql"):
        raise ValidationError(
            "a PostgreSQL connection string starts with postgresql:// or postgres://",
            "connection_string",
            parts.scheme,
        )
    arguments: dict[str, Any] = {
        "user": unquote(parts.username or "postgres"),
        "host": parts.hostname or "localhost",
    }
    if parts.port:
        arguments["port"] = parts.port
    if parts.password is not None:
        arguments["password"] = unquote(parts.password)
    database = parts.path.lstrip("/")
    if database:
        arguments["database"] = unquote(database)
    query = dict(item.split("=", 1) for item in parts.query.split("&") if "=" in item)
    if query.get("sslmode") in ("require", "verify-ca", "verify-full"):
        arguments["ssl_context"] = True
    return arguments


class Pg8000Executor:
    """``pg8000.native``: one connection, used from a worker thread under a lock."""

    def __init__(self, dsn: str, module: Any = None) -> None:
        """Remember the connection string; the connection opens on first use."""
        self._dsn = dsn
        self._module = module
        self._connection: Any = None
        self._lock = asyncio.Lock()

    def _run(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        if self._connection is None:
            module = self._module or missing_extra(
                "pg8000.native", extra="postgres", package="pg8000"
            )
            self._connection = module.Connection(**connection_arguments(self._dsn))
        rows = self._connection.run(sql, **params) or []
        names = [column["name"] for column in (self._connection.columns or [])]
        return [dict(zip(names, row, strict=False)) for row in rows]

    async def run(self, name: str, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Run the statement in a worker thread."""
        async with self._lock:
            return await asyncio.to_thread(self._run, sql, params)

    async def close(self) -> None:
        """Close the connection."""
        if self._connection is not None:
            await asyncio.to_thread(self._connection.close)
            self._connection = None


def positional(sql: str, params: dict[str, Any]) -> tuple[str, list[Any]]:
    """``:name`` parameters to asyncpg's ``$1``, ``$2``; a name used twice keeps one number."""
    order: list[str] = []

    def number(match: re.Match[str]) -> str:
        name = match.group(1)
        if name is None:  # a quoted string
            return match.group(0)
        if name not in order:
            order.append(name)
        return f"${order.index(name) + 1}"

    return _PARAM.sub(number, sql), [params[name] for name in order]


class AsyncpgExecutor:
    """``asyncpg``: one connection, guarded by a lock."""

    def __init__(self, dsn: str, module: Any = None) -> None:
        """Remember the connection string; the connection opens on first use."""
        self._dsn = dsn
        self._module = module
        self._connection: Any = None
        self._lock = asyncio.Lock()

    async def run(self, name: str, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Run the statement on the connection."""
        async with self._lock:
            if self._connection is None:
                module = self._module or missing_extra("asyncpg", extra="postgres-asyncpg")
                self._connection = await module.connect(self._dsn)
            text, values = positional(sql, params)
            rows = await self._connection.fetch(text, *values)
            return [dict(row) for row in rows]

    async def close(self) -> None:
        """Close the connection."""
        if self._connection is not None:
            await self._connection.close()
            self._connection = None


# D100
def choose_driver(dsn: str | None, cluster_arn: str | None, secret_arn: str | None) -> Driver:
    """The first available driver, or ``MissingExtraError`` naming the extras."""
    if cluster_arn and secret_arn:
        return "data-api"
    if dsn is None:
        raise ValidationError(
            "PostgreSQLBackend needs a connection string, "
            "or cluster_arn and secret_arn for the Data API",
            "connection_string",
            None,
        )
    if importlib.util.find_spec("pg8000") is not None:
        return "pg8000"
    if importlib.util.find_spec("asyncpg") is not None:
        return "asyncpg"
    error = MissingExtraError(extra="postgres", missing="pg8000")
    error.add_note(
        "Or the faster compiled driver: pip install skyeai[postgres-asyncpg]; "
        "or pass cluster_arn and secret_arn to use the "
        "RDS Data API (nothing to install in AWS Lambda)."
    )
    raise error


# D100
class PostgreSQLBackend(StorageBackend, ScanStore, ExpiryStore):
    """Key-value, counter, scan and expiry in a PostgreSQL table.

    Args:
        connection_string: A ``postgresql://`` URL, for pg8000 and asyncpg.
        table_name: The table (``name`` or ``schema.name``), created on first use.
        cluster_arn: The Aurora cluster ARN, for the Data API.
        secret_arn: The Secrets Manager ARN of the database credentials, for the Data API.
        database: The database name, for the Data API.
        region_name: The AWS region of the Data API; ``None`` reads ``AWS_REGION`` then
            ``AWS_DEFAULT_REGION`` and, when none is set, leaves the choice to ``boto3``.
        driver: Force a driver instead of the usual order.
        executor: A driver object to use instead of building one (tests pass a fake one).
        clock: The time source for expiry; ``time.time`` by default.
    """

    def __init__(
        self,
        connection_string: str | None = None,
        table_name: str = "skye_storage",
        *,
        cluster_arn: str | None = None,
        secret_arn: str | None = None,
        database: str | None = None,
        region_name: str | None = None,
        driver: Driver | None = None,
        executor: _Executor | None = None,
        clock: Clock = default_clock,
    ) -> None:
        """Check the settings and choose the driver; nothing connects until the first operation."""
        if not _IDENTIFIER.match(table_name):
            raise ValidationError(
                f"table_name must be a SQL identifier (name or schema.name), got {table_name!r}",
                "table_name",
                table_name,
            )
        self.table_name = table_name
        self._sql = statements(table_name)
        self._clock = clock
        self._ready = False
        self.driver: Driver | None
        if executor is not None:
            self.driver = driver
            self._executor: _Executor = executor
            return
        self.driver = driver or choose_driver(connection_string, cluster_arn, secret_arn)
        if self.driver == "data-api":
            if not (cluster_arn and secret_arn):
                raise ValidationError(
                    "the Data API driver needs cluster_arn and secret_arn", "cluster_arn", None
                )
            self._executor = DataApiExecutor(cluster_arn, secret_arn, database, region_name)
        elif connection_string is None:
            raise ValidationError(
                f"the {self.driver} driver needs a connection string", "connection_string", None
            )
        elif self.driver == "pg8000":
            self._executor = Pg8000Executor(connection_string)
        else:
            self._executor = AsyncpgExecutor(connection_string)

    async def _run(self, name: str, operation: str, **params: Any) -> list[dict[str, Any]]:
        with provider_errors("postgres", operation):
            if not self._ready:
                await self._executor.run("create", self._sql["create"], {})
                self._ready = True
            return await self._executor.run(name, self._sql[name], params)

    async def connect(self) -> None:
        """Open the connection and create the table if needed."""
        await self._run("keys", "connect", pattern="", now=self._clock())

    async def close(self) -> None:
        """Close the connection of the driver."""
        await self._executor.close()

    async def get(self, key: str) -> dict[str, Any] | None:
        """The value of ``key``, or ``None``."""
        return _row_value(await self._run("get", "get", key=check_key(key), now=self._clock()))

    async def count(self, key: str) -> int:
        """The count of ``key``, 0 when it is absent or expired: the ``get`` statement already
        leaves out an expired row."""
        rows = await self._run("get", "count", key=check_key(key), now=self._clock())
        return count_of(_row_value(rows))

    async def is_alive(self, key: str) -> bool:
        """``True`` when ``key`` has a row that has not expired: the ``expiry`` statement leaves out
        an expired one."""
        rows = await self._run("expiry", "is_alive", key=check_key(key), now=self._clock())
        return bool(rows)

    async def remaining(self, key: str) -> int | None:
        """The seconds left to ``expires_at`` (rounded up), or ``None`` when there is no live row or
        no expiry."""
        rows = await self._run("expiry", "remaining", key=check_key(key), now=self._clock())
        if not rows or rows[0]["expires_at"] is None:
            return None
        return remaining_of(float(rows[0]["expires_at"]), self._clock)

    async def set(self, key: str, data: dict[str, Any], ttl: int | None = None) -> None:
        """Insert or replace the row of ``key``."""
        payload = json.dumps(check_data(data))
        await self._run(
            "set", "set", key=check_key(key), data=payload, exp=expiry_of(ttl, self._clock)
        )

    async def delete(self, key: str) -> bool:
        """Delete the row of ``key``; ``True`` when it was live."""
        rows = await self._run("delete", "delete", key=check_key(key), now=self._clock())
        return bool(rows and rows[0].get("live"))

    async def increment(self, key: str, amount: int = 1, ttl: int | None = None) -> int:
        """One upsert that adds ``amount`` and returns the count; an expired counter restarts."""
        check_key(key)
        check_ttl(ttl)
        rows = await self._run(
            "increment",
            "increment",
            key=key,
            amount=amount,
            exp=expiry_of(ttl, self._clock),
            now=self._clock(),
        )
        return int(rows[0]["count"])

    async def set_multiple(self, data: dict[str, dict[str, Any]], ttl: int | None = None) -> None:
        """Write every item, one statement each; nothing is written when one item is invalid."""
        check_items(data)
        check_ttl(ttl)
        for key, value in data.items():
            await self.set(key, value, ttl)

    async def keys(self, prefix: str = "", limit: int | None = None) -> list[str]:
        """The live keys that start with ``prefix``, sorted."""
        check_limit(limit)
        rows = await self._run("keys", "keys", pattern=like_prefix(prefix), now=self._clock())
        found = [row["key"] for row in rows]
        return found if limit is None else found[:limit]


def _row_value(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The JSON object of the first row of a ``get`` statement, or ``None`` when there is no live
    row."""
    if not rows:
        return None
    data = rows[0]["data"]
    value = json.loads(data) if isinstance(data, str) else data
    return value if isinstance(value, dict) else None


__all__ = [
    "AsyncpgExecutor",
    "DataApiExecutor",
    "Pg8000Executor",
    "PostgreSQLBackend",
    "choose_driver",
    "statements",
]
