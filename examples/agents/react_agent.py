"""Wire a ReAct agent with a model and capabilities (proposed-interface, guarded).

This shows the intended wiring shape
built from the real ``agents`` registry, but it does NOT run an agent loop: the
``ReActAgent`` that ships today is a placeholder whose ``invoke`` raises
``NotImplementedError``. The ReAct loop arrives with the future agents spec.

What is real here: ``skye.agent(REACT, ...)`` returns a ``Runnable`` built by the
registered agent type, and the model/capabilities wiring shape below is the intended
public API. We guard-return before calling ``.invoke`` so the script stays green.
"""

import asyncio

import skye
from skye.agents import REACT
from skye.interfaces import Runnable


async def main() -> None:
    # The intended wiring: hand the agent a model Runnable and its capabilities.
    # A real model would be `client = skye.provider("openai", api_key=...)`; here we
    # pass the options shape only, because the ReAct loop is not implemented yet.
    agent = skye.agent(
        REACT,
        model="gpt-4",
        capabilities=["search", "calculator"],
        max_steps=6,
    )
    assert isinstance(agent, Runnable)  # the placeholder already satisfies the Port

    print("ReAct agent constructed with the intended model/capabilities wiring.")
    print("The ReAct reasoning loop ships with the future agents spec; not invoking it here.")
    # Intentionally not awaiting agent.invoke(...): the placeholder raises by design.
    return


if __name__ == "__main__":
    asyncio.run(main())
