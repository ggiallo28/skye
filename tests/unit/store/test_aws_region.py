"""DynamoDB and the Data API read the region through the profile rule (task 6.6, O63 part 2 option A)."""

from __future__ import annotations

import asyncio
import sys
from typing import Any

import pytest

from skye.store.plugins.dynamodb.backend import DynamoDBBackend
from skye.store.plugins.postgres.backend import DataApiExecutor


@pytest.fixture(autouse=True)
def no_region_in_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)


class Boto3:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def resource(self, service: str, **kwargs: Any) -> Any:
        self.calls.append((service, kwargs))
        from tests.unit.store.fakes import FakeDynamoResource

        return FakeDynamoResource()

    def client(self, service: str, **kwargs: Any) -> Any:
        self.calls.append((service, kwargs))
        return object()


def test_dynamodb_passes_the_region_it_finds_and_nothing_when_it_finds_none(
    monkeypatch: pytest.MonkeyPatch,
):
    boto3 = Boto3()
    monkeypatch.setitem(sys.modules, "boto3", boto3)
    asyncio.run(DynamoDBBackend("t").connect())  # none: the boto3 chain is the last step
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    asyncio.run(DynamoDBBackend("t").connect())
    monkeypatch.setenv("AWS_REGION", "eu-west-3")
    asyncio.run(DynamoDBBackend("t").connect())
    asyncio.run(DynamoDBBackend("t", "us-west-2").connect())
    assert [kwargs for _, kwargs in boto3.calls] == [
        {},
        {"region_name": "ap-south-1"},
        {"region_name": "eu-west-3"},
        {"region_name": "us-west-2"},
    ]


def test_the_data_api_follows_the_same_rule(monkeypatch: pytest.MonkeyPatch):
    boto3 = Boto3()
    monkeypatch.setitem(sys.modules, "boto3", boto3)

    class Rds:
        def execute_statement(self, **kwargs: Any) -> dict[str, Any]:
            return {"records": []}

    boto3.client = lambda service, **kwargs: boto3.calls.append((service, kwargs)) or Rds()  # type: ignore[method-assign]
    asyncio.run(DataApiExecutor("arn", "secret", None, None).run("x", "select 1", {}))
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    asyncio.run(DataApiExecutor("arn", "secret", None, None).run("x", "select 1", {}))
    assert [kwargs for _, kwargs in boto3.calls] == [{}, {"region_name": "eu-west-1"}]
