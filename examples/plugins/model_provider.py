"""Add a model provider.

A provider that speaks the OpenAI chat-completions format needs no class of its own: you give
`plugins.provider` the name, the `OpenAICompatibleProvider` that Skye ships, and a profile.

The profile declares, once, everything that is specific to the provider:

* `api_key_variables`: the environment variables that the key is read from, in order.
* `default_api_base`: the endpoint used when none is given.
* `models`: the models it has, with their prices in USD per million tokens, so that cost and token
  counting need nothing else.

`skye.provider("acme")` builds the client, as it builds the built-in providers.

Tip: a provider with a class of its own uses the decorator, `@plugins.provider("acme", profile=...)`
on top of the class. Skye tells that it is a model provider from the method the class has
(`generate`); the same name can also have an embedding class or a decision class, and the profile is
the one of the name.

To ship it as a package, give the module an entry point, as `pyproject.toml` in this folder does:
Skye imports the module the first time it meets a name it does not know, and `import skye` never
does.
"""

import skye
from skye.models import OpenAICompatibleProvider
from skye.plugins import ModelProfile, ProviderProfile

plugins = skye.Plugins()

plugins.provider(
    "acme",
    OpenAICompatibleProvider,
    profile=ProviderProfile(
        "acme",
        api_key_variables=("ACME_API_KEY",),
        default_api_base="https://api.acme.example/v1",
        models={
            "acme-small": ModelProfile(prompt_price=0.10, completion_price=0.40),
            "acme-large": ModelProfile(prompt_price=2.00, completion_price=8.00),
        },
    ),
)


def main() -> None:
    client = skye.provider(
        "acme", api_key="not-a-real-key"
    )  # without api_key, ACME_API_KEY is read
    print("provider:", type(client).__name__)


if __name__ == "__main__":
    main()
