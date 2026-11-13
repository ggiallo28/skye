"""Use an agent.

An agent is built with `skye.agent(name, **options)`, the same call for yours (see `agent_type.py`)
and for the one that ships with Skye, `REACT` (the name `"react"`), which runs the loop: the model
answers, asks for a tool, reads the result and goes on until it has an answer.

It takes what it can use in three separate options:

* `tools=[...]`: your own tools, the functions you wrote with `@capability`.
* `toolkits=[...]`: sets of tools that Skye builds by name, `skye.toolkit("openapi", ...)`.
* `skills=[...]`: the path of a `SKILL.md`. The agent reads it when it needs it, and for that it
  adds the toolkit `files` by itself, limited to the folder of the skill.

`return_direct=True` on a tool makes its result the answer of the agent: the model is not asked
again after that call. It is for a result that is already the text to give back.

The loop itself ships with the agents spec, so this builds the agent and shows what it holds
without running it: no key and no network.
"""

from pathlib import Path

import skye
from skye.agents import REACT
from skye.tools import capability

SKILL = Path(__file__).parent / "skills" / "refund-policy" / "SKILL.md"
ACME = {  # the OpenAPI document of one API, here inline; `spec=` also takes a path or an address
    "openapi": "3.0.0",
    "servers": [{"url": "https://api.acme.example"}],
    "paths": {"/orders/{id}": {"get": {"operationId": "get_order", "summary": "Read an order"}}},
}


@capability
def order_status(order_id: str) -> str:
    """Say the status of an order."""
    return "shipped"


@capability(name="billing_refund", return_direct=True)
def refund(order_id: str) -> str:
    """Refund an order and confirm it to the customer."""
    return f"Order {order_id} refunded."


def main() -> None:
    agent = skye.agent(
        REACT,
        model="gpt-4o-mini",
        tools=[order_status, refund],
        toolkits=[skye.toolkit("openapi", spec=ACME)],
        skills=[str(SKILL)],
    )
    print("tools:", [tool.get_schema().name for tool in agent.options["tools"]])
    print("toolkits:", [type(toolkit).__name__ for toolkit in agent.options["toolkits"]])
    print("added for the skill:", [type(toolkit).__name__ for toolkit in agent.skill_toolkits])
    # Running it, `await agent.invoke("Refund order 42")`: the model calls `billing_refund` and,
    # with return_direct, the confirmation it returns is the answer.


if __name__ == "__main__":
    main()
