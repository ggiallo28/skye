"""Add a routing strategy.

To add a routing strategy you use the decorator `@plugins.routing_strategy("name")` on top of a
function.

The function receives:

* The ids of the models that can answer, as a list of strings.
* It returns the one to use.

The name is valid wherever the name of a built-in strategy is: the `strategy` of a router and of a
`.skye` file.

Tip: a strategy that needs numbers (latency, cost, a quota) asks the router for them; this one only
looks at the names.
"""

import skye
from skye.router import ModelRouter, ModelTarget, RouteConfig

plugins = skye.Plugins()


@plugins.routing_strategy("shortest-name")
def shortest_name(available_models: list[str]) -> str:
    return min(available_models, key=len)


def main() -> None:
    # The strategy by itself: a function from the ids of the models to the one to use.
    strategy = skye.routing_strategy("shortest-name")
    print("chosen:", strategy(["gpt-4o-mini", "o3", "claude-sonnet-5-5"]))

    # In a router: write the name where you would write a built-in strategy ("round_robin", ...).
    # The route "chat" sends each request to the target the strategy chooses, so "o3" here.
    router = ModelRouter(
        routes=[
            RouteConfig(
                alias="chat",
                targets=[
                    ModelTarget(model="gpt-4o-mini", provider="openai", api_key="not-a-real-key"),
                    ModelTarget(model="o3", provider="openai", api_key="not-a-real-key"),
                ],
                strategy="shortest-name",
            )
        ]
    )
    # Needs a real key and the network:
    # router.complete(messages=[UserMessage("Hello!")], model="chat")
    route = router.get_route("chat")
    print("route:", route.strategy if route else None)

    # The same name in a .skye file or in a router configuration dict:
    #   {"routes": [{"alias": "chat", "targets": [...], "strategy": "shortest-name"}]}


if __name__ == "__main__":
    main()
