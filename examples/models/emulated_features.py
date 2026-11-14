"""What a model cannot do is emulated, not refused (planned interface, decision D121).

Changing the model must not break a call that used a feature the new model lacks:

- capabilities on a model with no native capability calling are described in the prompt, and the
  JSON of the answer is read back as a capability call in the usual shape;
- a structured output on a model with no native one goes the same way;
- an image, a document or an audio that the model cannot read is replaced by a line of text that
  says so, so the model answers that it cannot see it instead of ignoring it.

The response lists each of these in ``adjustments``, and ``strict=True`` turns them into errors.
The small Amazon model on Bedrock reads text only, which makes it a good example.

The calls need AWS credentials; without them the example prints the error and goes on.
"""

import base64
from dataclasses import dataclass

import skye
from skye import Size, UserMessage
from skye.exceptions import ConfigurationError, ProviderError
from skye.tools import capability


@capability
def get_weather(city: str) -> str:
    """The weather in a city."""
    return f"Sunny in {city}"


@dataclass
class Answer:
    city: str
    country: str


def tiny_png() -> str:
    """A 1x1 PNG as a data URL, so the example needs no image file."""
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
    )
    return "data:image/png;base64," + base64.b64encode(png).decode()


def main() -> None:
    client = skye.provider("bedrock/amazon", models=Size.SMALL, region="eu-west-1")
    info = client.info(Size.SMALL)
    print(info.model, "reads images:", info.accepts("image"))

    try:
        # The image is replaced by a line of text; the model says it cannot see it
        seen = client.complete([UserMessage(content="What is in this image?", images=[tiny_png()])])
        print(seen.content)
        print("   fitted:", seen.adjustments)

        # Capabilities: native where the model has them, through the prompt where it does not
        asked = client.complete(
            [UserMessage(content="What is the weather in Rome?")], capabilities=[get_weather]
        )
        for call in asked.capability_calls:
            print("capability call:", call.name, call.arguments)
        print("   fitted:", asked.adjustments)

        # A structured output: native, then function calling, then the same emulation
        answer = client.complete(
            [UserMessage(content="Where is the Colosseum?")], response_schema=Answer
        )
        print(answer.structured_output)
    except (ConfigurationError, ProviderError) as error:
        print("Expected without credentials:", error.message)


if __name__ == "__main__":
    main()
