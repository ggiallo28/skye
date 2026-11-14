"""One client for the language, the embedding and the decision model (planned, decision D121).

The problem. An application almost always needs the three kinds: a model that writes, one that
embeds for retrieval, one that decides. One provider seldom has all three (Anthropic has no
embeddings), and on a platform such as Bedrock or Vertex AI they come from different families:
Claude writes, an Amazon model embeds. Without this you build three clients, repeat the region
and the dates on each, and pass three objects around the program.

``skye.providers`` takes one provider for each kind and returns one client::

    client = skye.providers(language="anthropic", embedding="bedrock/amazon", decision="jev")

Each of the three takes a name, or a client built with ``skye.provider`` when that provider needs
something of its own; none is required. What they share is written once (``ProviderDefaults``: the
size, the two catalog dates, the region); the value on a client wins, and a key is never shared.
Each kind has one fixed provider: choosing among several at each call is the work of the router.
"""

import asyncio

import skye
from skye import ProviderDefaults, Reasoning, Size, UserMessage
from skye.exceptions import ConfigurationError, ProviderError

QUESTION = [UserMessage(content="Does this contract renew by itself? Answer in one sentence.")]

DEFAULTS: ProviderDefaults = {
    "region": "eu-west-1",  # reaches the two Bedrock providers; jev has no region and ignores it
    "place": "eu",  # the geography prefix of the model ids on Bedrock
    "models": Size.LARGE,  # every provider that names no size of its own
    "catalog": "2026-11-14",  # the language and the decision rows
    "embedding_catalog": "2026-11-14",  # the embedding rows: write it when an index is stored
}


def build():
    """Anthropic on Bedrock for the language, Amazon for the embeddings, Jev to decide."""
    return skye.providers(
        language="bedrock/anthropic",
        embedding=skye.provider("bedrock/amazon", models=Size.SMALL),  # its own size wins
        decision="jev",
        **DEFAULTS,
    )


async def main() -> None:
    client = build()
    for kind, provider in client.assignments.items():
        print(f"{kind:9} -> {provider}")

    try:
        response = client.complete(QUESTION, reasoning=Reasoning.HIGH)
        print(response.provider, response.model)

        vector = client.encode("termination clause")
        print(len(vector), "numbers")

        decision = await client.decide(
            "Does the contract renew by itself?", options=["yes", "no", "unclear"]
        )
        print(decision.choice)
    except (ConfigurationError, ProviderError) as error:
        print("Expected without a key:", error.message)

    # Two kinds are enough: a decision provider is optional, like the other two
    two = skye.providers(language="openai", embedding="cohere", models=Size.LARGE)
    print(two.assignments)  # language and embedding; calling two.decide(...) would raise

    # Keys come from the environment (OPENAI_API_KEY, COHERE_API_KEY). To pass one by hand, write
    # it on the client of its provider: a key is never a common default.
    by_hand = skye.providers(
        language=skye.provider("openai", api_key="sk-example"),
        embedding=skye.provider("cohere", api_key="co-example"),
        models=Size.LARGE,
    )
    print(by_hand.assignments)


if __name__ == "__main__":
    asyncio.run(main())
