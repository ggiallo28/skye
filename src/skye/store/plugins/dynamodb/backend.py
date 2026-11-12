"""DynamoDB backend through ``boto3`` (preinstalled in AWS Lambda; extra ``aws`` elsewhere, decision
D99).

The table has a string partition key ``pk``; the expiry is the number attribute ``ttl`` (seconds
since the epoch), which you can
enable as the table's TTL attribute so DynamoDB deletes expired items. DynamoDB deletes them late
(within days), so this backend also
checks the expiry on every read: an expired item is absent at once (D95). ``boto3`` is synchronous,
so every call runs in a worker
thread (``asyncio.to_thread``). There is no default region: it comes from the argument or from the
usual AWS configuration (in
Lambda, ``AWS_REGION``).

``keys`` runs a ``Scan`` with a ``begins_with`` filter: it reads the whole table and is meant for
small tables or maintenance, not a hot
path.

Example:
    >>> from skye.store import DynamoDBBackend
    >>> store = DynamoDBBackend("skye-state")  # nothing is called until the first operation

Raises: ``ValidationError`` for an invalid key, value or time to live; ``MissingExtraError`` (extra
    ``aws``) when ``boto3`` is absent;
    ``ProviderError`` naming the operation when a call fails.
Missing: an absent or expired item reads as ``None``.
Concurrency: ``increment`` is one ``UpdateItem`` with ``ADD``, atomic across processes.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

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
    is_expired,
    provider_errors,
    remaining_of,
)

_KEY = "pk"
_TTL = "ttl"


def _to_dynamo(value: Any) -> Any:
    """JSON values to DynamoDB values: a ``float`` becomes a ``Decimal`` (boto3 rejects floats)."""
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _to_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_dynamo(v) for v in value]
    return value


def _from_dynamo(value: Any) -> Any:
    """DynamoDB values back to JSON: a whole ``Decimal`` becomes ``int``, any other ``float``."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _from_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_from_dynamo(v) for v in value]
    return value


class DynamoDBBackend(StorageBackend, ScanStore, ExpiryStore):
    """Key-value, counter, scan and expiry in a DynamoDB table.

    Args:
        table_name: The table; its partition key is the string ``pk``.
        region_name: The AWS region; ``None`` reads ``AWS_REGION`` then ``AWS_DEFAULT_REGION`` (the rule of the AWS
            profile) and, when none is set, leaves the choice to ``boto3`` (its own chain: the config file, the instance
            metadata); there is no silent ``us-east-1``.
        resource: A ``boto3`` DynamoDB resource to use instead of creating one (tests pass a fake
            one).
        clock: The time source for expiry; ``time.time`` by default.
    """

    def __init__(
        self,
        table_name: str,
        region_name: str | None = None,
        *,
        resource: Any = None,
        clock: Clock = default_clock,
    ) -> None:
        """Remember the settings; ``boto3`` is imported on first use."""
        self.table_name = check_key(table_name)
        self.region_name = region_name
        self._resource = resource
        self._table: Any = None
        self._clock = clock

    def _get_table(self) -> Any:
        if self._table is None:
            if self._resource is None:
                boto3 = missing_extra("boto3", extra="aws")
                region = region_for("bedrock", self.region_name, required=False)
                kwargs = {"region_name": region} if region else {}
                self._resource = boto3.resource("dynamodb", **kwargs)
            self._table = self._resource.Table(self.table_name)
        return self._table

    async def connect(self) -> None:
        """Create the client and the table handle (no network call)."""
        self._get_table()

    def _item_value(self, item: dict[str, Any] | None) -> dict[str, Any] | None:
        if not item:
            return None
        expiry = item.get(_TTL)
        if is_expired(None if expiry is None else float(expiry), self._clock):
            return None
        return {k: _from_dynamo(v) for k, v in item.items() if k not in (_KEY, _TTL)}

    def _item(self, key: str, data: dict[str, Any], ttl: int | None) -> dict[str, Any]:
        item = {k: _to_dynamo(v) for k, v in data.items()}
        item[_KEY] = key
        expiry = expiry_of(ttl, self._clock)
        if expiry is not None:
            item[_TTL] = int(expiry)
        return item

    async def get(self, key: str) -> dict[str, Any] | None:
        """The item of ``key`` without its ``pk`` and ``ttl``, or ``None``."""
        check_key(key)
        with provider_errors("dynamodb", "get"):
            table = self._get_table()
            response = await asyncio.to_thread(table.get_item, Key={_KEY: key}, ConsistentRead=True)
        return self._item_value(response.get("Item"))

    async def set(self, key: str, data: dict[str, Any], ttl: int | None = None) -> None:
        """Put the item of ``key``."""
        check_key(key)
        check_data(data)
        if _KEY in data or _TTL in data:
            from skye.base.exceptions import ValidationError

            raise ValidationError(
                f"the attributes {_KEY!r} and {_TTL!r} are reserved by DynamoDBBackend",
                "data",
                sorted(data),
            )
        item = self._item(key, data, ttl)
        with provider_errors("dynamodb", "set"):
            table = self._get_table()
            await asyncio.to_thread(table.put_item, Item=item)

    async def delete(self, key: str) -> bool:
        """Delete the item of ``key``; ``True`` when a live item was there."""
        check_key(key)
        with provider_errors("dynamodb", "delete"):
            table = self._get_table()
            response = await asyncio.to_thread(
                table.delete_item, Key={_KEY: key}, ReturnValues="ALL_OLD"
            )
        return self._item_value(response.get("Attributes")) is not None

    async def increment(self, key: str, amount: int = 1, ttl: int | None = None) -> int:
        """``ADD`` to ``count`` in one ``UpdateItem``; an expired counter starts again."""
        check_key(key)
        check_ttl(ttl)
        now = int(self._clock())
        expiry = expiry_of(ttl, self._clock)
        names = {"#c": "count", "#t": _TTL}
        values: dict[str, Any] = {":a": amount, ":now": now}
        update = "ADD #c :a"
        if expiry is None:
            update += " REMOVE #t"
        else:
            update += " SET #t = :t"
            values[":t"] = int(expiry)
        with provider_errors("dynamodb", "increment"):
            table = self._get_table()
            try:
                response = await asyncio.to_thread(
                    table.update_item,
                    Key={_KEY: key},
                    UpdateExpression=update,
                    ConditionExpression="attribute_not_exists(#t) OR #t > :now",
                    ExpressionAttributeNames=names,
                    ExpressionAttributeValues=values,
                    ReturnValues="UPDATED_NEW",
                )
            except Exception as error:
                failed = type(error).__name__ == "ConditionalCheckFailedException"
                if not (failed or "ConditionalCheckFailed" in str(error)):
                    raise
                # The counter had expired but DynamoDB had not deleted it yet: start again.
                await asyncio.to_thread(
                    table.put_item, Item=self._item(key, {"count": amount}, ttl)
                )
                return amount
        return int(response["Attributes"]["count"])

    async def count(self, key: str) -> int:
        """The ``count`` of the item of ``key`` in one consistent ``GetItem``; 0 when it is absent or expired."""
        check_key(key)
        with provider_errors("dynamodb", "count"):
            table = self._get_table()
            response = await asyncio.to_thread(table.get_item, Key={_KEY: key}, ConsistentRead=True)
        return count_of(self._item_value(response.get("Item")))

    async def _live_item(self, key: str, operation: str) -> dict[str, Any] | None:
        """The item of ``key`` from one consistent ``GetItem``, or ``None`` when it is absent or expired."""
        check_key(key)
        with provider_errors("dynamodb", operation):
            table = self._get_table()
            response = await asyncio.to_thread(table.get_item, Key={_KEY: key}, ConsistentRead=True)
        item = response.get("Item")
        return item if self._item_value(item) is not None else None

    async def is_alive(self, key: str) -> bool:
        """One consistent ``GetItem``; ``True`` when the item is present and its ``ttl`` is not past."""
        return await self._live_item(key, "is_alive") is not None

    async def remaining(self, key: str) -> int | None:
        """The seconds left to the ``ttl`` attribute (rounded up), or ``None`` when absent, expired or without ``ttl``."""
        item = await self._live_item(key, "remaining")
        expiry = None if item is None else item.get(_TTL)
        return remaining_of(None if expiry is None else float(expiry), self._clock)

    async def get_multiple(self, keys: list[str]) -> dict[str, dict[str, Any] | None]:
        """``BatchGetItem`` in groups of 100, retrying unprocessed keys; every key is returned."""
        for key in keys:
            check_key(key)
        result: dict[str, dict[str, Any] | None] = {key: None for key in keys}
        unique = list(dict.fromkeys(keys))
        with provider_errors("dynamodb", "get_multiple"):
            self._get_table()
            for start in range(0, len(unique), 100):
                request: dict[str, Any] = {
                    self.table_name: {
                        "Keys": [{_KEY: k} for k in unique[start : start + 100]],
                        "ConsistentRead": True,
                    }
                }
                while request:
                    response = await asyncio.to_thread(
                        self._resource.batch_get_item, RequestItems=request
                    )
                    for item in response.get("Responses", {}).get(self.table_name, []):
                        result[item[_KEY]] = self._item_value(item)
                    request = response.get("UnprocessedKeys") or {}
        return result

    async def set_multiple(self, data: dict[str, dict[str, Any]], ttl: int | None = None) -> None:
        """Write every item with a batch writer; nothing is sent when one item is invalid."""
        check_items(data)
        check_ttl(ttl)
        items = [self._item(key, value, ttl) for key, value in data.items()]

        def write() -> None:
            with self._get_table().batch_writer() as batch:
                for item in items:
                    batch.put_item(Item=item)

        with provider_errors("dynamodb", "set_multiple"):
            await asyncio.to_thread(write)

    async def keys(self, prefix: str = "", limit: int | None = None) -> list[str]:
        """A ``Scan`` of the keys that start with ``prefix`` (reads the whole table), sorted."""
        check_limit(limit)

        def scan() -> list[str]:
            table = self._get_table()
            kwargs: dict[str, Any] = {
                "ProjectionExpression": "#k, #t",
                "ExpressionAttributeNames": {"#k": _KEY, "#t": _TTL},
            }
            if prefix:
                kwargs["FilterExpression"] = "begins_with(#k, :p)"
                kwargs["ExpressionAttributeValues"] = {":p": prefix}
            found = []
            while True:
                response = table.scan(**kwargs)
                for item in response.get("Items", []):
                    expiry = item.get(_TTL)
                    if not is_expired(None if expiry is None else float(expiry), self._clock):
                        found.append(item[_KEY])
                last = response.get("LastEvaluatedKey")
                if not last:
                    return sorted(found)
                kwargs["ExclusiveStartKey"] = last

        with provider_errors("dynamodb", "keys"):
            found = await asyncio.to_thread(scan)
        return found if limit is None else found[:limit]


__all__ = ["DynamoDBBackend"]
