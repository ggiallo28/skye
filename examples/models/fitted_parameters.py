"""The same parameters on every model (planned interface, decision D121).

The problem. Every provider names and bounds its parameters in its own way, and every model
accepts its own subset: a call tuned for one model fails on the next, so changing a size or a
provider would mean touching every call again, and the size would be useless.

The parameters of ``complete`` have one name on every provider and say what you want, for example
how much the model should think (``reasoning=``); the client fits them to the model:

- nearest: ``max_tokens`` above the ceiling of the model becomes the ceiling; a reasoning level the
  model lacks becomes the nearest one it has;
- left out: a parameter the model does not accept (``top_k`` on OpenAI, ``temperature`` on a model
  that always reasons) is not sent;
- the response lists every fit in ``adjustments``.

``temperature`` and ``top_p`` go from 0 to 1 on every provider. ``max_tokens`` counts the visible
text. With ``strict=True`` a fit is an error and nothing is sent. The calls need a key.
"""

import skye
from skye import Reasoning, Size, UserMessage
from skye.exceptions import ConfigurationError, ProviderError, ValidationError

QUESTION = [UserMessage(content="Explain a cold start in two sentences.")]
PARAMETERS = {
    "temperature": 0.5,
    "top_k": 40,
    "seed": 7,
    "max_tokens": 500_000,
    "reasoning": Reasoning.XHIGH,
}


def ask(name: str) -> None:
    """The same call on one more provider: only the name changes."""
    client = skye.provider(name, models=Size.SMALL)
    try:
        response = client.complete(QUESTION, **PARAMETERS)
    except (ConfigurationError, ProviderError) as error:
        print(f"{name}: expected without a key:", error.message)
        return
    print(f"{name}: {response.model} stopped on {response.finish_reason}")
    for fit in response.adjustments:
        print("   fitted:", fit)  # for example: top_k: left out; max_tokens: 500000 -> 128000


def main() -> None:
    for name in ("openai", "anthropic", "google"):
        ask(name)

    # An answer cut at the limit is one call that ends with "length"; continuing is asked for
    client = skye.provider("anthropic", models=Size.SMALL)
    try:
        response = client.complete(QUESTION, max_tokens=20, continue_on_limit=True)
        print("requests made:", response.requests)
    except (ConfigurationError, ProviderError) as error:
        print("Expected without a key:", error.message)

    # In a test you may want the fit to fail instead: nothing is sent
    strict = skye.provider("openai", models=Size.SMALL, strict=True)
    try:
        strict.complete(QUESTION, top_k=40)
    except ValidationError as error:
        print("Expected with strict=True:", error.message)
    except (ConfigurationError, ProviderError) as error:
        print("Expected without a key:", error.message)


if __name__ == "__main__":
    main()
