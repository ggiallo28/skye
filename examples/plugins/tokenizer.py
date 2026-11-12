"""Add a tokenizer.

What it is for: a model reads text as tokens, and Skye counts them to estimate the cost of a call
and to check that a prompt fits in the context of the model. For the known providers Skye knows how
to count. For a model with its own vocabulary it does not, so you tell it how.

A tokenizer is a function with the decorator `@plugins.tokenizer("name")`. It receives the `model`
and returns an object with `encode(text)`, which gives the list of tokens of a text. Then you say
which models use it, in their profile: `ModelProfile(tokenizer="name")`.

Here the model is one of a provider that already exists: `plugins.profile(provider, models=...)`
changes only its tokenizer. The prices, the endpoint and the other models stay as they are. For a
provider of your own, see `tokenizer_provider.py`.
"""

import skye
from skye.models import TokenCounter
from skye.plugins import ModelProfile

plugins = skye.Plugins()


@plugins.tokenizer("words")
def words(model: str):
    """A token is a word."""

    class Words:
        def encode(self, text: str) -> list[str]:
            return text.split()

    return Words()


# `gpt-4o` of the provider `openai` counts words, and nothing else changes.
plugins.profile("openai", models={"gpt-4o": ModelProfile(tokenizer="words")})


def fits(prompt: str, model: str, limit: int) -> bool:
    """What a count is for: check that a prompt stays within a limit of tokens."""
    return TokenCounter.count_tokens(prompt, model) <= limit


def main() -> None:
    text = "one two three four"
    print("gpt-4o:", TokenCounter.count_tokens(text, "gpt-4o"))  # 4 words, 4 tokens
    print("gpt-4o-mini:", TokenCounter.count_tokens(text, "gpt-4o-mini"))  # not changed
    print("fits in 4 tokens:", fits(text, "gpt-4o", 4))


if __name__ == "__main__":
    main()
