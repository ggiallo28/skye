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

This one needs a key (`OPENAI_API_KEY`) and, for the toolkit, the network.
"""

import asyncio

import skye
from skye.agents import REACT
from skye.tools import capability


@capability
def order_status(order_id: str) -> str:
    """Say the status of an order."""
    return "shipped"


@capability(name="billing.refund", return_direct=True)
def refund(order_id: str) -> str:
    """Refund an order and confirm it to the customer."""
    return f"Order {order_id} refunded."


async def main() -> None:
    agent = skye.agent(
        REACT,
        model="gpt-4o-mini",
        tools=[order_status, refund],
        toolkits=[skye.toolkit("openapi", spec="https://api.acme.example/openapi.json")],
        skills=["examples/plugins/skills/refund-policy/SKILL.md"],
    )

    # The model calls `order_status`, reads "shipped" and writes the answer.
    print(await agent.invoke("Where is order 42?"))

    # The model calls `billing.refund`; with return_direct the confirmation is the answer.
    print(await agent.invoke("Refund order 42"))


if __name__ == "__main__":
    asyncio.run(main())
