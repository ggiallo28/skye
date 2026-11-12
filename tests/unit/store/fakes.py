"""Offline fakes of the clients the store backends drive: a boto3 DynamoDB resource, a redis.asyncio
client, a SQL executor.

Each fake implements only the calls the backend makes, with the semantics of the real service as
documented, so the conformance suite
runs offline (store task 2.3). The SQL itself is not executed here: ``FakeSqlExecutor`` implements
each named statement in Python and
checks that every parameter appears in the SQL text. The SQL is unverified against a real PostgreSQL
server.
"""

# ruff: noqa: N803 - the fakes keep boto3's argument names (Key, Item, RequestItems)
from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable
from contextlib import contextmanager
from decimal import Decimal
from typing import Any

from skye.store.plugins.redis.backend import INCREMENT_SCRIPT


class ConditionalCheckFailedException(Exception):  # noqa: N818 - the name boto3 uses
    """The name boto3 gives the error of a failed ``ConditionExpression``."""


def _dynamo_value(value: Any) -> Any:
    if isinstance(value, float):
        raise TypeError("Float types are not supported. Use Decimal types instead.")
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, dict):
        return {k: _dynamo_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_dynamo_value(v) for v in value]
    return value


class FakeTable:
    """``boto3.resource('dynamodb').Table(name)`` for the calls of ``DynamoDBBackend``."""

    def __init__(self, page_size: int = 2) -> None:
        self.items: dict[str, dict[str, Any]] = {}
        self.page_size = page_size

    def get_item(
        self, Key: dict[str, str], ConsistentRead: bool = False
    ) -> dict[str, Any]:  # noqa: N803
        item = self.items.get(Key["pk"])
        return {"Item": dict(item)} if item else {}

    def put_item(self, Item: dict[str, Any]) -> dict[str, Any]:  # noqa: N803
        self.items[Item["pk"]] = _dynamo_value(dict(Item))
        return {}

    def delete_item(
        self, Key: dict[str, str], ReturnValues: str = "NONE"
    ) -> dict[str, Any]:  # noqa: N803
        old = self.items.pop(Key["pk"], None)
        return {"Attributes": old} if old and ReturnValues == "ALL_OLD" else {}

    def update_item(self, **request: Any) -> dict[str, Any]:
        key = request["Key"]["pk"]
        names, values = request["ExpressionAttributeNames"], request["ExpressionAttributeValues"]
        item = self.items.get(key)
        assert request["ConditionExpression"] == "attribute_not_exists(#t) OR #t > :now"
        if item is not None and names["#t"] in item and not item[names["#t"]] > values[":now"]:
            raise ConditionalCheckFailedException("The conditional request failed")
        item = dict(item or {"pk": key})
        match = re.fullmatch(r"ADD #c :a (SET #t = :t|REMOVE #t)", request["UpdateExpression"])
        assert match, request["UpdateExpression"]
        item[names["#c"]] = Decimal(item.get(names["#c"], 0)) + Decimal(values[":a"])
        if match.group(1).startswith("SET"):
            item[names["#t"]] = Decimal(values[":t"])
        else:
            item.pop(names["#t"], None)
        self.items[key] = item
        return {"Attributes": {names["#c"]: item[names["#c"]]}}

    def scan(self, **request: Any) -> dict[str, Any]:
        keys = sorted(self.items)
        if "FilterExpression" in request:
            assert request["FilterExpression"] == "begins_with(#k, :p)"
            keys = [k for k in keys if k.startswith(request["ExpressionAttributeValues"][":p"])]
        start = request.get("ExclusiveStartKey")
        if start:
            keys = [k for k in keys if k > start["pk"]]
        page = keys[: self.page_size]
        out: dict[str, Any] = {
            "Items": [
                {k: v for k, v in self.items[key].items() if k in ("pk", "ttl")} for key in page
            ]
        }
        if len(keys) > self.page_size:
            out["LastEvaluatedKey"] = {"pk": page[-1]}
        return out

    @contextmanager
    def batch_writer(self) -> Any:
        yield self


class FakeDynamoResource:
    """``boto3.resource('dynamodb')``: one table; ``batch_get_item`` defers one key once."""

    def __init__(self) -> None:
        self.table = FakeTable()
        self.deferred_once = False

    def Table(self, name: str) -> FakeTable:  # noqa: N802
        self.name = name
        return self.table

    def batch_get_item(self, RequestItems: dict[str, Any]) -> dict[str, Any]:  # noqa: N803
        ((name, request),) = RequestItems.items()
        keys = [k["pk"] for k in request["Keys"]]
        unprocessed = []
        if not self.deferred_once and len(keys) > 1:
            self.deferred_once = True
            unprocessed, keys = keys[-1:], keys[:-1]
        found = [dict(self.table.items[k]) for k in keys if k in self.table.items]
        out: dict[str, Any] = {"Responses": {name: found}}
        if unprocessed:
            out["UnprocessedKeys"] = {name: {"Keys": [{"pk": k} for k in unprocessed]}}
        return out


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Redis glob (``*``, ``?``, backslash escapes) to a regular expression."""
    out, i = [], 0
    while i < len(pattern):
        char = pattern[i]
        if char == "\\" and i + 1 < len(pattern):
            out.append(re.escape(pattern[i + 1]))
            i += 2
            continue
        out.append(".*" if char == "*" else "." if char == "?" else re.escape(char))
        i += 1
    return re.compile("".join(out) + r"\Z", re.S)


class FakePipeline:
    def __init__(self, client: FakeRedis) -> None:
        self.client, self.calls = client, []

    def set(self, name: str, value: str, ex: int | None = None) -> None:
        self.calls.append((name, value, ex))

    async def execute(self) -> list[bool]:
        for name, value, ex in self.calls:
            await self.client.set(name, value, ex=ex)
        return [True] * len(self.calls)


class FakeRedis:
    """``redis.asyncio`` client: expiry on a clock, ``EVAL`` of the increment script, ``SCAN``."""

    def __init__(self, clock: Callable[[], float]) -> None:
        self.clock = clock
        self.data: dict[str, tuple[str, float | None]] = {}
        self.closed = False

    def _live(self, name: str) -> str | None:
        entry = self.data.get(name)
        if entry is None:
            return None
        if entry[1] is not None and entry[1] <= self.clock():
            del self.data[name]
            return None
        return entry[0]

    async def get(self, name: str) -> bytes | None:
        value = self._live(name)
        return None if value is None else value.encode()

    async def set(self, name: str, value: str, ex: int | None = None) -> bool:
        if ex is not None and ex <= 0:
            raise ValueError("invalid expire time in 'set' command")
        self.data[name] = (value, None if ex is None else self.clock() + ex)
        return True

    async def exists(self, name: str) -> int:
        return int(self._live(name) is not None)

    async def pttl(self, name: str) -> int:
        """Milliseconds left, -2 for a missing key and -1 for a key with no expiry, as the server answers."""
        if self._live(name) is None:
            return -2
        expiry = self.data[name][1]
        return -1 if expiry is None else int((expiry - self.clock()) * 1000)

    async def delete(self, name: str) -> int:
        present = self._live(name) is not None
        self.data.pop(name, None)
        return int(present)

    async def mget(self, names: list[str]) -> list[bytes | None]:
        return [await self.get(n) for n in names]

    def pipeline(self) -> FakePipeline:
        return FakePipeline(self)

    async def eval(self, script: str, numkeys: int, *args: Any) -> int:
        import json

        assert script == INCREMENT_SCRIPT and numkeys == 1
        name, amount, expiry = args
        current = self._live(name)
        count = 0
        if current is not None:
            try:
                decoded = json.loads(current)
                if isinstance(decoded, dict) and isinstance(decoded.get("count"), (int, float)):
                    count = int(decoded["count"])
            except ValueError:
                pass
        count += int(amount)
        self.data[name] = (
            json.dumps({"count": count}),
            self.clock() + int(expiry) if int(expiry) > 0 else None,
        )
        return count

    async def scan_iter(self, match: str) -> AsyncIterator[bytes]:
        regex = _glob_to_regex(match)
        for name in list(self.data):
            if regex.match(name) and self._live(name) is not None:
                yield name.encode()

    async def aclose(self) -> None:
        self.closed = True


def _like_to_regex(pattern: str) -> re.Pattern[str]:
    out, i = [], 0
    while i < len(pattern):
        char = pattern[i]
        if char == "\\" and i + 1 < len(pattern):
            out.append(re.escape(pattern[i + 1]))
            i += 2
            continue
        out.append(".*" if char == "%" else "." if char == "_" else re.escape(char))
        i += 1
    return re.compile("".join(out) + r"\Z", re.S)


class FakeSqlExecutor:
    """Each named statement of ``skye.store.plugins.postgres.backend.statements``, in Python over a ``dict``."""

    def __init__(self) -> None:
        self.rows: dict[str, tuple[str, float | None]] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.created = 0
        self.closed = False

    async def run(self, name: str, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        import json

        for param in params:
            assert f":{param}" in sql, f"parameter {param} is not in the SQL of {name}"
        for value in params.values():
            if isinstance(value, str) and len(value) > 3:
                assert value not in sql, f"a value was put into the SQL text of {name}"
        self.calls.append((name, params))

        def live(key: str) -> bool:
            row = self.rows.get(key)
            return row is not None and (row[1] is None or row[1] > params["now"])

        if name == "create":
            self.created += 1
            return []
        if name == "get":
            return [{"data": self.rows[params["key"]][0]}] if live(params["key"]) else []
        if name == "set":
            self.rows[params["key"]] = (params["data"], params["exp"])
            return []
        if name == "delete":
            was = live(params["key"]) if params["key"] in self.rows else None
            self.rows.pop(params["key"], None)
            return [] if was is None else [{"live": was}]
        if name == "increment":
            key = params["key"]
            row = self.rows.get(key)
            count = 0
            if row is not None and (row[1] is None or row[1] > params["now"]):
                count = int(json.loads(row[0]).get("count", 0))
            count += params["amount"]
            self.rows[key] = (json.dumps({"count": count}), params["exp"])
            return [{"count": count}]
        if name == "expiry":
            return [{"expires_at": self.rows[params["key"]][1]}] if live(params["key"]) else []
        if name == "keys":
            regex = _like_to_regex(params["pattern"])
            return [{"key": k} for k in sorted(self.rows) if regex.match(k) and live(k)]
        raise AssertionError(f"unknown statement {name}")

    async def close(self) -> None:
        self.closed = True
