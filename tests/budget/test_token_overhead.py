"""The tokens Skye adds to what the caller wrote, when it calls a model (report only for now).

The request is built and never sent, and the text it carries is counted with the standard-library
estimate of `TokenCounter` (no tokenizer to download), so the figures are the same on every machine.
The overhead is the text of the wire messages minus the text the caller gave, in tokens. Skye's own
prompt templates are not measured: they are text the caller chose to use.

Two paths are measured, the direct call to a model and the call through an agent. The agent loop is
not written yet (`3-runtime-agents`), so its row says that and is not a figure.

The limits are `[tokens]` in budgets.toml. While `enforce = false` a figure above its limit is
reported in the job summary and never fails the build; set it to `true` when the limits are agreed.
The figures also go to the file named by SKYE_BUDGET_REPORT.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from skye.base.completion import CompleteRequest
from skye.base.messages import SystemMessage, UserMessage
from skye.models import TokenCounter
from skye.tools import capability

try:
    from skye.models import OpenAICompatibleProvider
    from skye.models.utilities.capability_choice import emulated_request
except ImportError:  # the layout before decision D110: remove this branch when it lands
    from skye.models.llm.openai_compatible import OpenAICompatibleProvider
    from skye.models.transport.capability_choice import emulated_request
from tests.budget.measure import load_budgets, report

MODEL = "gpt-4o-mini"
PROMPT = "Summarize the following text in three bullet points: " + "lorem ipsum dolor " * 20
SYSTEM = "You are terse."


def tokens(text: str) -> int:
    """The estimate of the library, the same on every machine."""
    return TokenCounter.count_tokens(text, "skye-overhead-probe")


def wire_text_tokens(body: dict[str, Any]) -> int:
    total = 0
    for message in body["messages"]:
        content = message["content"]
        if isinstance(content, list):
            content = " ".join(part.get("text", "") for part in content)
        total += tokens(content)
    return total


@capability
def refund(order_id: str) -> str:
    """Refund an order."""
    return "ok"


def _provider() -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(model=MODEL, api_key="not-a-real-key")


def _request(*messages: Any, **options: Any) -> CompleteRequest:
    return CompleteRequest(model=MODEL, messages=list(messages), **options)


def direct_plain() -> int:
    body = _provider()._transform_request(_request(UserMessage(content=PROMPT)))
    return wire_text_tokens(body) - tokens(PROMPT)


def direct_system_and_user() -> int:
    body = _provider()._transform_request(
        _request(SystemMessage(content=SYSTEM), UserMessage(content=PROMPT))
    )
    return wire_text_tokens(body) - tokens(SYSTEM) - tokens(PROMPT)


def direct_forced_choice_emulated() -> int:
    request = _request(
        UserMessage(content=PROMPT), capabilities=[refund], capability_choice="refund"
    )
    emulated, _ = emulated_request(request)
    return wire_text_tokens(_provider()._transform_request(emulated)) - tokens(PROMPT)


SCENARIOS = {
    "direct_plain": direct_plain,
    "direct_system_and_user": direct_system_and_user,
    "direct_forced_choice_emulated": direct_forced_choice_emulated,
}


def test_token_overhead_is_reported():
    budget = load_budgets()["tokens"]
    enforce = bool(budget.get("enforce", False))
    report("| token overhead | now | max | status |")
    report("|---|---|---|---|")
    over = []
    for name, measure in SCENARIOS.items():
        now, limit = measure(), budget[name]["max"]
        assert now >= 0, f"{name}: the request carries less text than the caller gave"
        status = "ok" if now <= limit else "over the limit" + ("" if enforce else " (not enforced)")
        report(f"| {name} | {now} | {limit} | {status} |")
        if now > limit:
            over.append(f"{name}: {now} > {limit}")
    report("| agent loop | not written yet | - | pending (3-runtime-agents) |")
    if enforce:
        assert not over, "token overhead above its limit: " + "; ".join(over)


def test_information_rows_are_measurable():
    """Sent but written by the caller, so not an overhead: the tool schema, for the report."""
    body = _provider()._transform_request(
        _request(UserMessage(content=PROMPT), capabilities=[refund])
    )
    assert tokens(json.dumps(body["tools"])) > 0


def test_agent_loop_is_not_measurable_yet():
    from skye.agents import REACT, create_agent

    agent = create_agent(REACT)
    with pytest.raises(NotImplementedError):
        asyncio.run(agent.invoke("hello"))
