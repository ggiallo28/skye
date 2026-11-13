"""For each kind the word of the decorator is the word of the builder (task 16.3).

Requirements 56.11 and 62.9 of steering. One table, ``ROWS``, has a row for each kind of the
registrar: a factory of a fake, and the builder of the
kind when it has one. The same tests run over every row, so a new kind needs one row. A kind with no
builder (``tokenizer`` and ``template_filter``,
which are used by name in a profile and in a template) is checked with ``plugins.get``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest

import skye
from skye.base.plugins import KINDS
from tests.unit.plugins.registrar_state import restored_default_registrar


@pytest.fixture
def plugins():
    """The default handle, with the default registrar put back as it was after the test."""
    with restored_default_registrar():
        yield skye.Plugins()


# -- the fakes: each factory gives a new object, so a test can register two
# ----------------------------------------------------------


def _model_provider() -> Any:
    class FakeModelProvider:
        def __init__(self, **config: Any) -> None:
            self.config = config

        async def acomplete(self, request: Any) -> Any:  # the method that makes it a model provider
            return request

    return FakeModelProvider


def _backend() -> Any:
    class FakeBackend:
        def __init__(self, **config: Any) -> None:
            self.config = config

    return FakeBackend


def _credential_source() -> Any:
    class FakeSource:
        def __init__(self, **config: Any) -> None:
            self.config = config

    return FakeSource


def _agent() -> Any:
    class FakeAgent:
        def __init__(self, **options: Any) -> None:
            self.options = options

        async def invoke(self, input: Any) -> Any:
            return input

    return FakeAgent


def _mcp_client() -> Any:
    class FakeMCP:
        def __init__(
            self, target: Any, *, headers: dict[str, str] | None = None, timeout: float = 30.0
        ) -> None:
            self.target = target

    return FakeMCP


def _routing_strategy() -> Any:
    def fake_strategy(models: list[str]) -> str:
        return models[0]

    return fake_strategy


def _tokenizer() -> Any:
    def fake_tokenizer(model: str) -> Any:
        class Words:
            def encode(self, text: str) -> list[str]:
                return text.split()

        return Words()

    return fake_tokenizer


def _template_filter() -> Any:
    def fake_filter(value: Any) -> str:
        return str(value).upper()

    return fake_filter


def _toolkit() -> Any:
    from skye.tools import capability
    from skye.tools.toolkit import Toolkit

    class FakeToolkit(Toolkit):
        @capability
        def ping(self) -> str:
            """Answer pong."""
            return "pong"

    return FakeToolkit


# -- the table
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Row:
    """What a kind needs for the tests: ``make`` gives a fake; ``build`` builds it by name
    (``None``: the kind has no builder)."""

    word: str  # the word of the decorator (a method of ``skye.Plugins``)
    make: Callable[[], Any]
    build: Callable[[str], Any] | None = None
    built_is_the_fake: bool = False  # the builder returns the registered object itself (a strategy)


ROWS: dict[str, Row] = {
    "provider": Row("provider", _model_provider, lambda name: skye.provider(name, api_key="k")),
    "backend": Row("backend", _backend, lambda name: skye.backend(name, path="x")),
    "credential_source": Row(
        "credential_source",
        _credential_source,
        lambda name: skye.credential_source(name, token="t"),
    ),
    "agent": Row("agent", _agent, lambda name: skye.agent(name)),
    "mcp_client": Row(
        "mcp_client", _mcp_client, lambda name: skye.mcp_client("http://x/mcp", impl=name)
    ),
    "routing_strategy": Row(
        "routing_strategy",
        _routing_strategy,
        lambda name: skye.routing_strategy(name),
        built_is_the_fake=True,
    ),
    "tokenizer": Row("tokenizer", _tokenizer),
    "template_filter": Row("template_filter", _template_filter),
    "toolkit": Row("toolkit", _toolkit, lambda name: skye.toolkit(name)),
}

WITH_BUILDER = [kind for kind, row in ROWS.items() if row.build is not None]
BY_NAME_ONLY = [kind for kind, row in ROWS.items() if row.build is None]


def _check_built(row: Row, built: Any, fake: Any) -> None:
    if row.built_is_the_fake:
        assert built is fake
    else:
        assert isinstance(built, fake)


# -- the table is complete
# --------------------------------------------------------------------------------------------------


def test_the_table_has_a_row_for_every_kind_of_the_registrar():
    assert set(ROWS) == set(KINDS)


def test_the_word_of_each_row_is_a_method_of_the_handle():
    for kind, row in ROWS.items():
        assert row.word == kind  # the word of the decorator is the name of the kind
        assert callable(getattr(skye.Plugins, row.word))


# -- the word of the decorator is the word of the builder
# ----------------------------------------------------------------------------


@pytest.mark.parametrize("kind", WITH_BUILDER)
def test_the_builder_has_the_word_of_the_decorator(kind):
    row = ROWS[kind]
    builder = getattr(skye, row.word)
    assert callable(builder)
    assert builder.__name__ == row.word
    assert row.word in skye.__all__


# -- what a decorator or a direct call registers is found by the builder and by `names`
# -----------------------------------------------


@pytest.mark.parametrize("kind", WITH_BUILDER)
def test_a_decorator_registers_what_the_builder_builds_and_names_lists_it(plugins, kind):
    row = ROWS[kind]
    fake = row.make()
    name = f"w2b-{kind}-decorated"
    decorated = getattr(plugins, row.word)(name)(fake)
    assert decorated is fake  # the decorator returns the object unchanged
    assert name in plugins.names(kind)
    assert plugins.get(kind, name) is fake
    _check_built(row, row.build(name), fake)


@pytest.mark.parametrize("kind", WITH_BUILDER)
def test_a_direct_call_registers_what_the_builder_builds_and_names_lists_it(plugins, kind):
    row = ROWS[kind]
    fake = row.make()
    name = f"w2b-{kind}-direct"
    assert getattr(plugins, row.word)(name, fake) is None
    assert name in plugins.names(kind)
    assert plugins.get(kind, name) is fake
    _check_built(row, row.build(name), fake)


# -- a kind with no builder: the registered object comes back by `plugins.get`
# -----------------------------------------------------------


@pytest.mark.parametrize("kind", BY_NAME_ONLY)
def test_a_decorator_registers_what_get_returns_and_names_lists_it(plugins, kind):
    row = ROWS[kind]
    fake = row.make()
    name = f"w2b-{kind}-decorated"
    assert getattr(plugins, row.word)(name)(fake) is fake
    assert name in plugins.names(kind)
    assert plugins.get(kind, name) is fake


@pytest.mark.parametrize("kind", BY_NAME_ONLY)
def test_a_direct_call_registers_what_get_returns_and_names_lists_it(plugins, kind):
    row = ROWS[kind]
    fake = row.make()
    name = f"w2b-{kind}-direct"
    getattr(plugins, row.word)(name, fake)
    assert name in plugins.names(kind)
    assert plugins.get(kind, name) is fake


# -- every kind: the two forms give the same result, and the default registrar is put back
# ------------------------------------------------


@pytest.mark.parametrize("kind", list(ROWS))
def test_the_two_forms_register_the_same_thing(plugins, kind):
    row = ROWS[kind]
    by_call, by_decorator = row.make(), row.make()
    getattr(plugins, row.word)(f"w2b-{kind}-call", by_call)
    getattr(plugins, row.word)(f"w2b-{kind}-deco")(by_decorator)
    assert plugins.get(kind, f"w2b-{kind}-call") is by_call
    assert plugins.get(kind, f"w2b-{kind}-deco") is by_decorator
    assert {f"w2b-{kind}-call", f"w2b-{kind}-deco"} <= set(plugins.names(kind))


@pytest.mark.parametrize("kind", list(ROWS))
def test_what_a_test_registered_is_not_left_in_the_default_registrar(kind):
    name = f"w2b-{kind}-decorated"
    assert name not in skye.Plugins().names(kind)
    assert f"w2b-{kind}-direct" not in skye.Plugins().names(kind)
