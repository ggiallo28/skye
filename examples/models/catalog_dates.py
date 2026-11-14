"""Which model a size means, and when it changes (planned interface, decision D121).

The size table has dated rows. A size means the row with the latest date on or before the catalog
date, so an upgrade of the library never changes the model that answers unless the date moves.
There are two dates and neither touches the other::

    client = skye.provider(
        "openai",
        models=Size.LARGE,
        catalog="2027-06-01",            # the language and the decision rows
        embedding_catalog="2026-11-14",  # the embedding rows
    )

With no date the default of this version is used: it moves at a minor version for the language
model and only at a major version for the embeddings, because a new embedding model gives vectors
that an index already stored cannot use. When an index is stored, write ``embedding_catalog``.

Nothing here needs a key or a network: the table and the model catalog ship with the library.
"""

import skye
from skye import Size
from skye.exceptions import ConfigurationError


def main() -> None:
    # The same size at two dates: the second one sees the rows added in between
    for date in ("2026-11-14", "latest"):
        client = skye.provider("anthropic", models=Size.LARGE, catalog=date)
        row = client.resolve(Size.LARGE)
        print(f"catalog={date:10} LARGE -> {row.model} (since {row.since})")

    # The table starts on a date: an earlier one is an error that names it
    try:
        skye.provider("anthropic", catalog="2020-01-01").resolve(Size.LARGE)
    except ConfigurationError as error:
        print("Expected:", error.message)

    # The embeddings follow their own date; moving catalog= does not move them
    client = skye.provider(
        "openai", models=Size.LARGE, catalog="latest", embedding_catalog="2026-11-14"
    )
    row = client.resolve(Size.LARGE, kind="embedding")
    print("embedding LARGE ->", row.model, f"(since {row.since})")

    # What the catalog knows about a model: its limits and, for an embedding model, the vector size
    info = client.info(row.model)
    print("vector size :", info.vector_size)
    info = client.info(Size.LARGE)
    print("max output  :", info.max_output_tokens)
    print("reasoning   :", [level.name for level in info.reasoning_levels])

    # One text gives one vector, a list gives a list of vectors with one request (it needs a key)
    try:
        vector = client.encode("cold starts on Lambda")
        vectors = client.encode(["serverless functions start fast", "a recipe for bread"])
        print(len(vector), "numbers;", len(vectors), "vectors")
    except ConfigurationError as error:
        print("Expected without a key:", error.message)


if __name__ == "__main__":
    main()
