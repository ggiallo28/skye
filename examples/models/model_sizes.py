"""Name a model by its size, not by its id (planned interface, decision D121).

The problem. A model id belongs to one provider and ages fast. Written in the calls, it has to be
found and changed all over the program the day the provider or the model changes. Kept out of the
code, it turns into one environment variable for every place that calls a model: the one that
classifies, the one that summarizes, the one that writes.

What you know when you write a call is how much the task needs: a small, fast model to classify a
ticket, a large one to draft a contract. A size says exactly that, and the library knows which
model it is on each provider, so the provider is chosen in one place and no call changes::

    client = skye.provider("openai", models=Size.LARGE)
    client = skye.provider("anthropic", models=Size.LARGE)          # the only line that changes
    client = skye.provider("bedrock/anthropic", models=Size.LARGE)  # the same family, on AWS

    client.complete(ticket, model=Size.SMALL)    # a simple task
    client.complete(contract, model=Size.XLARGE)  # a hard one

A text is still a literal model id, for the day you want one exact model. ``models=`` is the size
for every method; ``language_model=``, ``embedding_model=`` and ``decision_model=`` set one kind.
``resolve`` needs no key and no network; the calls need a key and print the error without one.
"""

import skye
from skye import Size, UserMessage
from skye.exceptions import ConfigurationError, ProviderError

PROVIDERS = (
    "openai",
    "anthropic",
    "bedrock/anthropic",
    "bedrock/openai",
    "bedrock/amazon",
    "google",
)
QUESTION = [UserMessage(content="Name the capital of France in one word.")]


def show_sizes() -> None:
    """The same size on every provider: only the first argument changes."""
    for name in PROVIDERS:
        client = skye.provider(name, models=Size.LARGE, region="eu-west-1", place="eu")
        row = client.resolve(Size.LARGE)
        print(f"{name:18} LARGE -> {row.model} (since {row.since})")

    # A platform with several families needs the family for a size, and says which ones it has
    try:
        skye.provider("bedrock", models=Size.LARGE, region="eu-west-1").resolve(Size.LARGE)
    except ConfigurationError as error:
        print("Expected:", error.message)


def show_defaults() -> None:
    """One size for every kind, one for a single kind, and the model of a single call."""
    client = skye.provider("openai", models=Size.LARGE, embedding_model=Size.SMALL)
    print("language :", client.resolve(Size.LARGE).model)
    print("embedding:", client.resolve(Size.SMALL, kind="embedding").model)
    try:
        client.complete(QUESTION)  # the LARGE language model
        client.complete(QUESTION, model=Size.SMALL)  # another size, for this call
        client.complete(QUESTION, model="gpt-6.1-sol")  # a literal id: the table is not read
        client.encode("cold starts on Lambda")  # the SMALL embedding model
    except (ConfigurationError, ProviderError) as error:
        print("Expected without a key:", error.message)


def main() -> None:
    show_sizes()
    show_defaults()


if __name__ == "__main__":
    main()
