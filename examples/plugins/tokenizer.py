"""Add a tokenizer.

What it is for: a model reads text as tokens, and Skye counts them to estimate the cost of a call
and to check that a prompt fits in the context of the model. For the known providers Skye knows how
to count. For a model with its own vocabulary it does not, so you tell it how.

A tokenizer is a function with the decorator `@plugins.tokenizer("name")`. It receives the `model`
and returns an object with `encode(text)`, which gives the list of tokens of a text. Then you say
which models use it, in their profile: `ModelProfile(tokenizer="name")`. Two cases:

1. A model of a provider that already exists: you change only its tokenizer, with
   `plugins.profile(provider, models={model: ModelProfile(tokenizer=...)})`. The prices, the endpoint
   and the other models of that provider stay as they are.
2. A provider of your own: the profile that registers it names the tokenizer of its models.

`TokenCounter.count_tokens(text, model)` finds the tokenizer in the profile of the model and counts
the list that `encode` returns. A model whose profile names none gets the estimate.

Tip: a tokenizer that wraps `tiktoken` or a `tokenizers` model is written the same way; the
library you wrap is yours to import.
"""

import skye
from skye.models import OpenAICompatibleProvider, TokenCounter
from skye.plugins import ModelProfile, ProviderProfile

plugins = skye.Plugins()


@plugins.tokenizer("words")
def words(model: str):
    """A token is a word."""

    class Words:
        def encode(self, text: str) -> list[str]:
            return text.split()

    return Words()


@plugins.tokenizer("chunks")
def chunks(model: str):
    """A token is a piece of four characters: a rough rule that fits many vocabularies."""

    class Chunks:
        def encode(self, text: str) -> list[str]:
            return [text[i : i + 4] for i in range(0, len(text), 4)]

    return Chunks()


# 1. An existing model: `gpt-4o` of the provider `openai` counts words, and nothing else changes.
plugins.profile("openai", models={"gpt-4o": ModelProfile(tokenizer="words")})

# 2. A provider of your own: its models say which tokenizer they use. `acme-large` names none.
plugins.provider(
    "acme",
    OpenAICompatibleProvider,
    profile=ProviderProfile(
        "acme",
        api_key_variables=("ACME_API_KEY",),
        default_api_base="https://api.acme.example/v1",
        models={
            "acme-small": ModelProfile(tokenizer="chunks"),
            "acme-large": ModelProfile(prompt_price=2.00, completion_price=8.00),
        },
    ),
)


def fits(prompt: str, model: str, limit: int) -> bool:
    """What a count is for: check that a prompt stays within a limit of tokens."""
    return TokenCounter.count_tokens(prompt, model) <= limit


def main() -> None:
    text = "one two three four"  # 4 words, 18 characters

    # 1. The existing model uses `words`: 4 tokens. Another model of `openai` is not changed.
    print("gpt-4o:", TokenCounter.count_tokens(text, "gpt-4o"))
    print("gpt-4o-mini:", TokenCounter.count_tokens(text, "gpt-4o-mini"), "(the usual count)")

    # 2. The new provider: `acme-small` uses `chunks` (18 characters make 5 pieces), and
    #    `acme-large`, which names none, gets the estimate.
    print("acme-small:", TokenCounter.count_tokens(text, "acme-small"))
    print("acme-large:", TokenCounter.count_tokens(text, "acme-large"), "(the estimate)")

    print("fits in 4 tokens:", fits(text, "gpt-4o", 4))


if __name__ == "__main__":
    main()
