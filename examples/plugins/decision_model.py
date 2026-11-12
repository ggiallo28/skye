"""Add a decision model.

To add a decision model you use the decorator `@plugins.provider("name")` on top of a class. It is the same decorator as for
a model provider: Skye tells that this is a decision model from the method the class has (`decide`). Its price, if it has
one, goes in the `profile=` of the decorator like that of any provider.

The class has:

* `async decide(prompt, options)`, which receives the question and the finite list of allowed options.
* It returns a `DecisionResult`: the choice, and a probability for every option (each in 0 to 1, summing to 1).
* An empty list of options is a `ValidationError`, and nothing is returned.

`skye.provider("name", provider_type="decision")` builds it, as it builds the built-in `"jev"`.
"""

import asyncio
from collections.abc import Sequence

import skye
from skye import ValidationError
from skye.interfaces import DecisionResult

plugins = skye.Plugins()


@plugins.provider("first-option")
class FirstOptionDecider:
    async def decide(self, prompt: str, options: Sequence[str]) -> DecisionResult:
        if not options:
            raise ValidationError(
                "at least one option is required", field="options", value=list(options)
            )
        lead = 0.7 if len(options) > 1 else 1.0
        rest = (1.0 - lead) / (len(options) - 1) if len(options) > 1 else 0.0
        return DecisionResult(
            choice=options[0],
            probabilities={o: (lead if i == 0 else rest) for i, o in enumerate(options)},
        )


async def main() -> None:
    decider = skye.provider("first-option", provider_type="decision")
    result = await decider.decide("Which route fits?", ["cheap", "strong", "refuse"])
    print("choice:", result.choice, "probabilities:", dict(result.probabilities))


if __name__ == "__main__":
    asyncio.run(main())
