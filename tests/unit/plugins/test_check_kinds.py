"""The ``check_<kind>`` functions of the nine kinds (Requirements 58.4, D111): each passes a good
fake and names the check a bad one fails."""

from __future__ import annotations

import pytest

from skye.agents.conformance import check_agent
from skye.auth.conformance import check_credential_source
from skye.base.conformance import run_checks
from skye.base.plugins import Registrar
from skye.models.conformance import check_provider, check_tokenizer
from skye.prompts.conformance import check_template_filter
from skye.router.conformance import check_routing_strategy
from skye.router.routing_strategies import RouterStrategy, with_context
from skye.store.conformance import check_backend
from skye.tools import Toolkit, capability
from skye.tools.conformance import check_mcp_client, check_toolkit


async def failing(coro, check: str) -> str:
    with pytest.raises(AssertionError) as caught:
        await coro
    message = str(caught.value)
    assert f"the check {check!r} failed" in message
    return message


async def test_run_checks_stops_at_the_first_failure_and_keeps_the_cause():
    ran: list[str] = []

    def bad() -> None:
        raise ValueError("boom")

    with pytest.raises(AssertionError, match="the check 'b' failed: boom") as caught:
        await run_checks(
            "thing",
            object,
            [("a", lambda: ran.append("a")), ("b", bad), ("c", lambda: ran.append("c"))],
        )
    assert ran == ["a"]
    assert isinstance(caught.value.__cause__, ValueError)


async def test_run_checks_awaits_what_a_check_returns():
    async def slow() -> None:
        raise ValueError("late")

    with pytest.raises(AssertionError, match="late"):
        await run_checks("thing", object, [("a", slow)])
    assert await run_checks("thing", object, []) == []


# provider


class FakeModel:
    async def acomplete(self, *a, **k): ...
    async def astream(self, *a, **k): ...
    def get_model_info(self):
        return {"provider": "fake"}


class FakeEmbedding:
    async def aencode(self, text): ...
    async def aencode_batch(self, texts): ...
    def get_vector_dimension(self):
        return 4


class FakeDecision:
    async def decide(self, prompt, options):
        from skye.base.interfaces.decision import DecisionResult

        if not options:
            raise ValueError("no options")
        return DecisionResult(options[0], {o: 1 / len(options) for o in options})


async def test_a_provider_of_each_function_passes_by_shape_and_built():
    assert await check_provider(FakeModel) == ["function", "acomplete", "astream"]
    assert await check_provider(FakeModel, config={}) == [
        "function",
        "acomplete",
        "astream",
        "builds",
        "object",
    ]
    assert "get_vector_dimension" in await check_provider(FakeEmbedding, config={})
    assert await check_provider(FakeDecision, config={}) == [
        "function",
        "decide",
        "builds",
        "object",
    ]


async def test_a_provider_names_the_check_it_fails():
    await failing(check_provider(object), "function")
    await failing(check_provider(FakeModel, function="embedding"), "aencode")

    class TwoFunctions(FakeModel, FakeDecision): ...

    await failing(check_provider(TwoFunctions), "function")
    assert "acomplete" in await check_provider(TwoFunctions, function="model")

    class BadInfo(FakeModel):
        def get_model_info(self):
            return []

    await failing(check_provider(BadInfo, config={}), "object")

    class ZeroDimension(FakeEmbedding):
        def get_vector_dimension(self):
            return 0

    await failing(check_provider(ZeroDimension, config={}), "object")


async def test_a_decision_must_follow_the_rule_of_requirement_9_8():
    class Greedy(FakeDecision):
        async def decide(self, prompt, options):
            from skye.base.interfaces.decision import DecisionResult

            return DecisionResult(options[0], {o: 1.0 for o in options})

    await failing(check_provider(Greedy, config={}), "object")

    class NoError(FakeDecision):
        async def decide(self, prompt, options):
            from skye.base.interfaces.decision import DecisionResult

            return DecisionResult("a", {"a": 1.0})

    message = await failing(check_provider(NoError, config={}), "object")
    assert "empty" in message or "not one of" in message


async def test_a_provider_with_a_name_needs_a_profile():
    registrar = Registrar()
    await failing(check_provider(FakeModel, name="acme", registrar=registrar), "profile")


# tokenizer


async def test_a_tokenizer_is_an_object_or_a_factory():
    class Words:
        def encode(self, text):
            return text.split()

    assert await check_tokenizer(Words()) == ["resolves", "encodes", "empty", "repeatable"]
    assert await check_tokenizer(lambda model: Words(), "gpt") == [
        "resolves",
        "encodes",
        "empty",
        "repeatable",
    ]
    await failing(check_tokenizer(lambda model: object()), "resolves")

    class Raises:
        def encode(self, text):
            if not text:
                raise ValueError("empty")
            return [1]

    await failing(check_tokenizer(Raises()), "empty")


# credential source


async def test_a_credential_source_is_an_authenticator_or_a_secret_source():
    class Token:
        def apply(self, method, url, headers, body=b""):
            return {**headers, "Authorization": "Bearer x"}

    class Secrets:
        def get(self, name):
            return "x"

    assert await check_credential_source(Token) == ["builds", "shape", "apply"]
    assert await check_credential_source(Secrets) == ["builds", "shape", "apply"]
    await failing(check_credential_source(object), "shape")

    class Mutates(Token):
        def apply(self, method, url, headers, body=b""):
            headers["Authorization"] = "x"
            return headers

    await failing(check_credential_source(Mutates), "apply")

    class Drops(Token):
        def apply(self, method, url, headers, body=b""):
            return {"Authorization": "x"}

    await failing(check_credential_source(Drops), "apply")
    await failing(check_credential_source(lambda **c: 1 / 0), "builds")


# routing strategy


async def test_a_routing_strategy_of_each_form_passes():
    class Last(RouterStrategy):
        def select(self, context):
            return context.models[-1]

    assert await check_routing_strategy(lambda ids: ids[0]) == [
        "one_model",
        "picks_a_model",
        "repeatable_calls",
        "alias",
    ]
    assert len(await check_routing_strategy(Last)) == 4
    assert len(await check_routing_strategy(with_context(lambda context: context.models[0]))) == 4
    assert len(await check_routing_strategy(lambda ids: ids[0], models=["x", "y"])) == 4


async def test_a_routing_strategy_names_the_check_it_fails():
    await failing(check_routing_strategy(lambda ids: "not-a-model"), "one_model")
    calls = iter(range(100))
    await failing(
        check_routing_strategy(lambda ids: ids[0] if next(calls) < 2 else "gone"),
        "repeatable_calls",
    )


# mcp client


class FakeClient:
    def __init__(self, target, *, headers=None, timeout=30.0):
        self.target = target

    async def list_tools(self): ...
    async def call_tool(self, name, arguments=None): ...
    async def list_prompts(self): ...
    async def get_prompt(self, name, arguments=None): ...
    async def list_resources(self): ...
    async def read_resource(self, uri): ...
    async def close(self): ...


async def test_an_mcp_client_is_built_and_looked_at_never_connected():
    assert await check_mcp_client(FakeClient) == ["builds", "interface", "closes"]

    class Sync(FakeClient):
        def list_tools(self):
            return []

    message = await failing(check_mcp_client(Sync), "interface")
    assert "list_tools" in message
    await failing(check_mcp_client(lambda target, headers=None, timeout=1.0: 1 / 0), "builds")


# toolkit


class ClockToolkit(Toolkit):
    @capability
    def now(self) -> str:
        """The time."""
        return "12:00"


async def test_a_toolkit_lists_unique_described_prefixed_schemas_and_runs_nothing():
    assert await check_toolkit(ClockToolkit) == ["builds", "provider", "schemas", "closes"]
    await failing(check_toolkit(lambda: object()), "provider")

    class Empty(Toolkit): ...

    assert "schemas" in await check_toolkit(Empty)

    class Noisy(Toolkit):
        ran = False

        @capability
        def act(self) -> str:
            """Has an effect."""
            type(self).ran = True
            return "x"

    await check_toolkit(Noisy)
    assert Noisy.ran is False


async def test_a_toolkit_with_a_badly_named_tool_fails_schemas():
    from types import SimpleNamespace

    def schemas_of(*items):
        class Odd(ClockToolkit):
            async def list_schemas(self, operation=None):
                return [SimpleNamespace(name=name, description=text) for name, text in items]

        return Odd

    await failing(
        check_toolkit(schemas_of(("other_now", "d"))), "schemas"
    )  # not the prefix of the toolkit
    await failing(
        check_toolkit(schemas_of(("odd_a", "d"), ("odd_a", "d"))), "schemas"
    )  # one name twice
    await failing(check_toolkit(schemas_of(("odd_a", " "))), "schemas")  # no description
    assert "schemas" in await check_toolkit(schemas_of(("odd_a", "d")))


# template filter


async def test_a_template_filter_renders_the_way_the_engine_does():
    assert await check_template_filter(lambda value: str(value)[::-1]) == [
        "callable",
        "accepts_a_value",
        "renders",
        "repeatable",
    ]
    await failing(check_template_filter("not callable"), "callable")
    await failing(check_template_filter(lambda value, other: value), "accepts_a_value")
    counter = iter(range(100))
    await failing(check_template_filter(lambda value: next(counter)), "renders")


# agent


async def test_an_agent_is_built_and_answers_when_given_an_input():
    class Echo:
        def __init__(self, **options):
            self.options = options

        async def invoke(self, input):
            return input

    assert await check_agent(Echo) == ["builds", "runnable"]
    assert await check_agent(Echo, input="hi", model="fake") == ["builds", "runnable", "invokes"]
    await failing(check_agent(lambda **o: object()), "runnable")

    class Broken(Echo):
        async def invoke(self, input):
            raise RuntimeError("no model")

    await failing(check_agent(Broken, input="hi"), "invokes")


# the store keeps its own


async def test_check_backend_still_raises_the_same_type():
    with pytest.raises(AssertionError):
        await check_backend(lambda clock: object())
