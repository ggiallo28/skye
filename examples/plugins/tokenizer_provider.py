"""A tokenizer for the models of a provider of your own.

The same tokenizer as in `tokenizer.py`, now named in the profile that registers the provider: each
model says which tokenizer it uses, and a model that names none gets the estimate.
"""

import skye
from skye.models import OpenAICompatibleProvider, TokenCounter
from skye.plugins import ModelProfile, ProviderProfile

plugins = skye.Plugins()


@plugins.tokenizer("chunks")
def chunks(model: str):
    """A token is a piece of four characters: a rough rule that fits many vocabularies."""

    class Chunks:
        def encode(self, text: str) -> list[str]:
            return [text[i : i + 4] for i in range(0, len(text), 4)]

    return Chunks()


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


def main() -> None:
    text = "one two three four"  # 18 characters
    print("acme-small:", TokenCounter.count_tokens(text, "acme-small"))  # 5 pieces
    print("acme-large:", TokenCounter.count_tokens(text, "acme-large"))  # no tokenizer: estimate


if __name__ == "__main__":
    main()
