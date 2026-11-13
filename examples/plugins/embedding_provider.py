"""Add an embedding provider.

To add an embedding provider you use the decorator `@plugins.provider("name")` on top of a class. It
is the same decorator as for a model provider: Skye tells which kind of provider the class is from
the methods it has (here `aencode`, so it is an embedding provider).

The class writes two `async` methods and the size of a vector, the `VectorEncoderInterface` Port:

* `aencode(text)` and `aencode_batch(texts)`, which return one vector, or one vector per text.
* `get_vector_dimension()`, the size of a vector.

Skye gives the class `encode` and `encode_batch`, the sync forms, built from the two you wrote.

`skye.provider("name", provider_type="embedding")` builds it, as it builds the built-in embedding
providers.

Tip: when the provider has a key variable, an endpoint or models with their own vector sizes, pass
`profile=` to the decorator, as `model_provider.py` does: the size of the vectors of a model is
`info={"vector_dimension": 1536}` in its `ModelProfile`.
"""

import hashlib

import skye
from skye.interfaces import VectorEncoderInterface

plugins = skye.Plugins()


@plugins.provider("hash-embed")
class HashEmbedder(VectorEncoderInterface):
    dimension = 8

    def __init__(self, **config: object) -> None:
        self.config = config

    def _vector(self, text: str) -> list[float]:
        return [byte / 255 for byte in hashlib.sha256(text.encode()).digest()[: self.dimension]]

    async def aencode(self, text: str) -> list[float]:
        return self._vector(text)

    async def aencode_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def get_vector_dimension(self) -> int:
        return self.dimension


def main() -> None:
    embedder = skye.provider("hash-embed", provider_type="embedding")
    vector = embedder.encode("hello")
    first = [round(v, 2) for v in vector[:3]]
    print(f"dimension {embedder.get_vector_dimension()}, first values {first}")
    print("same text, same vector:", embedder.encode("hello") == vector)


if __name__ == "__main__":
    main()
