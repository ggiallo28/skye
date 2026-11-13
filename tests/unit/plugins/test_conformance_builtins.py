"""Every built-in registration of every kind passes its ``check_<kind>`` function (task 10.2,
Requirement 58.5).

The cases are read from the default registrar, so a new built-in is covered without touching this
file; it must be given a config in ``CONFIGS``
(or an entry in ``KNOWN_UNCHECKED`` with the reason) or
``test_every_built_in_has_a_config_or_a_reason`` fails and names it. Nothing is skipped
silently: an entry of ``KNOWN_UNCHECKED`` is run and must still fail offline, so the test fails when
the entry is no longer needed.
"""

from __future__ import annotations

import itertools
from pathlib import Path
from typing import Any

import pytest

from skye.agents.conformance import check_agent
from skye.auth.cache import TokenCache
from skye.auth.conformance import check_credential_source
from skye.base.plugins import KINDS, get_registrar
from skye.models.conformance import check_provider, check_tokenizer
from skye.prompts.conformance import check_template_filter
from skye.router.conformance import check_routing_strategy
from skye.store.conformance import check_backend
from skye.tools.conformance import check_mcp_client, check_toolkit
from tests.unit.store.fakes import FakeDynamoResource, FakeRedis, FakeSqlExecutor

registrar = get_registrar()
PROVIDER_FUNCTIONS = ("model", "embedding", "decision")
KEY = {"api_key": "not-a-real-key"}


class _Context:
    """A durable context: ``get_state`` and ``set_state``."""

    def __init__(self) -> None:
        self.state: dict[str, object] = {}

    def get_state(self, name: str) -> object:
        return self.state.get(name)

    def set_state(self, name: str, value: object) -> None:
        self.state[name] = value


class _Authenticator:
    """The smallest authenticator a secret source accepts."""

    def apply(
        self, method: str, url: str, headers: dict[str, str], body: bytes | None = None
    ) -> dict[str, str]:
        return {**headers, "Authorization": "Bearer not-a-real-token"}


class _Cache(TokenCache):
    """A token cache that never fetches: the OAuth sources ask it for a token instead of calling
    their server."""

    def get(self, key: str, fetch: Any) -> str:
        return "not-a-real-token"


def _entries() -> list[tuple[str, str, str | None]]:
    """``(kind, name, function)`` of everything the default registrar holds, in a stable order."""
    entries: list[tuple[str, str, str | None]] = []
    for kind in KINDS:
        if kind == "provider":
            entries += [
                (kind, name, function)
                for function in PROVIDER_FUNCTIONS
                for name in registrar.names(kind, function)  # type: ignore[arg-type]
            ]
        else:
            entries += [(kind, name, None) for name in registrar.names(kind)]
    return entries


ENTRIES = _entries()

# : What a built-in needs to be built offline, by ``(kind, name)``: keyword options, or for a
# backend a function ``(tmp_path, clock) -> object``.
CONFIGS: dict[tuple[str, str], dict[str, Any]] = {
    ("credential_source", "anthropic"): KEY,
    ("credential_source", "cohere"): KEY,
    ("credential_source", "openai"): KEY,
    ("credential_source", "aws"): {
        "region": "us-east-1",
        "service": "bedrock",
        "access_key": "AKIDEXAMPLE",
        "secret_key": "not-a-real-secret",
    },
    ("credential_source", "azure"): {"credentials": "not-a-real-key"},
    ("credential_source", "google"): {"credentials": "not-a-real-token"},
    ("credential_source", "bedrock"): {"region": "us-east-1", **KEY},
    ("credential_source", "aws-secrets-manager"): {
        "region": "us-east-1",
        "authenticator": _Authenticator(),
    },
    ("credential_source", "aws-ssm"): {"region": "us-east-1", "authenticator": _Authenticator()},
    ("credential_source", "azure-key-vault"): {
        "vault_url": "https://vault.example",
        "authenticator": _Authenticator(),
    },
    ("credential_source", "google-secret-manager"): {
        "project": "p",
        "authenticator": _Authenticator(),
    },
    ("credential_source", "client-credentials"): {
        "token_url": "https://auth.example/token",
        "client_id": "id",
        "client_secret": "secret",
        "cache": _Cache(),
    },
    ("credential_source", "token-exchange"): {
        "token_url": "https://auth.example/token",
        "subject_token": "subject",
        "cache": _Cache(),
    },
    ("toolkit", "files"): {"root": "."},
    ("toolkit", "human"): {"channel": "console"},
    ("toolkit", "openapi"): {
        "spec": {
            "openapi": "3.0.0",
            "info": {"title": "t", "version": "1"},
            "paths": {"/ping": {"get": {"operationId": "ping", "responses": {}}}},
        },
        "base_url": "https://api.example",
    },
    ("toolkit", "shell"): {"allow": ["echo"]},
    ("agent", "react"): {},
}

# : Built-ins that cannot be checked offline with a config: the reason. Each is run with no config
# and must still fail.
KNOWN_UNCHECKED: dict[tuple[str, str], str] = {}


def _backend_makers(tmp_path: Path) -> dict[str, Any]:
    folders = itertools.count()
    backends = {name: registrar.get("backend", name) for name in registrar.names("backend")}
    return {
        "memory": lambda clock: backends["memory"](clock=clock),
        "file": lambda clock: backends["file"](str(tmp_path / str(next(folders))), clock=clock),
        "dynamodb": lambda clock: backends["dynamodb"](
            "t", resource=FakeDynamoResource(), clock=clock
        ),
        "redis": lambda clock: backends["redis"](client=FakeRedis(clock)),
        "valkey": lambda clock: backends["valkey"](client=FakeRedis(clock)),
        "postgres": lambda clock: backends["postgres"](executor=FakeSqlExecutor(), clock=clock),
        "durable_function": lambda clock: backends["durable_function"](_Context(), clock=clock),
    }


async def _run(kind: str, name: str, function: str | None, tmp_path: Path) -> list[str] | None:
    """Run the check of ``kind`` on the registered ``name`` and return what passed."""
    target = registrar.get(kind, name, function) if function else registrar.get(kind, name)  # type: ignore[arg-type]
    config = dict(CONFIGS.get((kind, name), {}))
    if kind == "provider":
        return await check_provider(target, name=name, function=function, registrar=registrar)
    if kind == "backend":
        return await check_backend(_backend_makers(tmp_path)[name])
    if kind == "credential_source":
        return await check_credential_source(target, **config)
    if kind == "routing_strategy":
        return await check_routing_strategy(target)
    if kind == "mcp_client":
        return await check_mcp_client(target, **config)
    if kind == "tokenizer":
        return await check_tokenizer(target, "gpt-4o")
    if kind == "template_filter":
        return await check_template_filter(target)
    if kind == "agent":
        return await check_agent(target, **config)
    if kind == "toolkit":
        if name == "files":
            config = {"root": str(tmp_path)}
        return await check_toolkit(target, **config)
    raise AssertionError(f"no check function is wired for the kind {kind!r}")


def _id(entry: tuple[str, str, str | None]) -> str:
    kind, name, function = entry
    return f"{kind}:{name}" + (f":{function}" if function else "")


CHECKED = [e for e in ENTRIES if (e[0], e[1]) not in KNOWN_UNCHECKED]


def test_every_kind_is_wired_and_the_registrar_is_not_empty():
    assert len(KINDS) == 9
    assert {kind for kind, _, _ in ENTRIES} >= {
        "provider",
        "backend",
        "credential_source",
        "routing_strategy",
        "mcp_client",
        "tokenizer",
        "toolkit",
        "agent",
    }


def test_every_built_in_has_a_config_or_a_reason():
    needs = {("credential_source", n) for n in registrar.names("credential_source")} | {
        ("toolkit", n) for n in registrar.names("toolkit")
    }
    missing = sorted(needs - set(CONFIGS) - set(KNOWN_UNCHECKED))
    assert (
        not missing
    ), f"built-ins with no offline config in CONFIGS and no reason in KNOWN_UNCHECKED: {missing}"
    makers = set(_backend_makers(Path(".")))
    unwired = sorted(set(registrar.names("backend")) - makers)
    assert not unwired, f"backends with no offline maker in _backend_makers: {unwired}"
    stale = sorted(set(CONFIGS) - {(k, n) for k, n, _ in ENTRIES})
    assert not stale, f"CONFIGS names a built-in that is no longer registered: {stale}"


@pytest.mark.parametrize("entry", CHECKED, ids=_id)
async def test_a_built_in_passes_its_check(entry, tmp_path):
    kind, name, function = entry
    passed = await _run(kind, name, function, tmp_path)
    assert passed, f"the check of {kind} {name!r} ran nothing"


async def test_an_unchecked_built_in_is_still_not_checkable_offline(tmp_path):
    """Each entry of ``KNOWN_UNCHECKED`` is run with no config and must fail, so an entry that is no
    longer needed is found (it is empty today)."""
    for kind, name in sorted(KNOWN_UNCHECKED):
        function = next((f for k, n, f in ENTRIES if (k, n) == (kind, name)), None)
        with pytest.raises(
            Exception
        ):  # noqa: B017, PT011 - any failure shows the entry is still needed
            await _run(kind, name, function, tmp_path)
