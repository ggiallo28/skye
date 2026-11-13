---
title: "Embeddings"
status: current
---

# Embeddings

This guide shows you how to turn texts into vectors with an embedding provider, to compare them by meaning, search them or store
them.

## What you need

- Skye installed: `pip install skyeai`. Every embedding provider is built in.
- The credentials of the provider: an API key for OpenAI and Cohere (`api_key=`, or `OPENAI_API_KEY` and `COHERE_API_KEY`), AWS
  credentials and a region for Bedrock, Google credentials for Google (see [Call a provider](call-a-provider.md)).

## Create an embedding client

The same `skye.provider` function creates an embedding client when you pass `provider_type="embedding"` (for `cohere`, which has
only embeddings, it is the default). An embedding client always needs a `model`.

=== "OpenAI"

    ```python
    import skye

    embedder = skye.provider("openai", model="text-embedding-3-small", provider_type="embedding")  # OPENAI_API_KEY
    ```

    Models with a known dimension: `text-embedding-3-small` (1536), `text-embedding-3-large` (3072), `text-embedding-ada-002`
    (1536). `api_base` points the client at an OpenAI-compatible server.

=== "Bedrock"

    ```python
    import skye

    embedder = skye.provider("bedrock", model="amazon.titan-embed-text-v2:0", region="us-east-1", provider_type="embedding")
    ```

    Titan models: `amazon.titan-embed-text-v1` (1536) and `amazon.titan-embed-text-v2:0` (1024). Titan takes one text per request,
    so `encode_batch` sends one request per text. Credentials come from the AWS chain, as for the Bedrock model client; without
`region`, the region is `AWS_REGION` or `AWS_DEFAULT_REGION`.

=== "Cohere"

    ```python
    import skye

    embedder = skye.provider("cohere", model="embed-english-v3.0")  # COHERE_API_KEY; provider_type="embedding" is implied
    ```

    Models with a known dimension: `embed-english-v3.0` (1024), `embed-english-light-v3.0` (384), `embed-multilingual-v3.0` (1024).
    The texts are sent with `input_type="search_document"`.

=== "Google"

    ```python
    import skye

    embedder = skye.provider(
        "google", model="text-embedding-004", project_id="my-project", location="us-central1", provider_type="embedding"
    )
    ```

    Models with a known dimension: `text-embedding-004` and `text-multilingual-embedding-002` (768). Credentials come from the
    Google chain, as for the Gemini client. The multimodal model is `"google-multimodal"` (below).

## Encode texts

Every embedding client has the same five methods:

| Method | Returns |
|---|---|
| `encode(text)` | one vector, a `list[float]` |
| `encode_batch(texts)` | one vector per text, in order |
| `aencode(text)`, `aencode_batch(texts)` | the same, from async code |
| `get_vector_dimension()` | the length of the vectors; `ValueError` for a model whose dimension Skye does not know |

This example encodes three texts, compares them with the cosine similarity, then encodes one text in plain and in async code:

```python
--8<-- "examples/providers/embeddings_example.py:9:40"
```

Without `OPENAI_API_KEY`, `get_embedder` returns a scripted embedder that makes a small vector from the letters of the text, so the
example runs offline and similar texts still come out close.

## Texts and images: Google multimodal

`GoogleMultimodalEmbeddingProvider` (model `multimodalembedding@001`, 1408 dimensions) puts texts and images in the same vector
space, so a text can find an image. Pass texts and images to the same `encode_batch`: an item that ends with an image extension
(`.jpg`, `.png`, `.webp`, ...), a URL that contains one, or a `data:image/...` URL is encoded as an image; anything else as text.

```python
import skye

embedder = skye.provider("google-multimodal", project_id="my-project", location="us-central1", provider_type="embedding")
vectors = embedder.encode_batch(["a red bicycle", "photos/bike.jpg"])
```

## An embedding provider of your own

To use a service Skye does not cover, add a class with the decorator `@plugins.provider("name")`. It is the same decorator as for a model
provider: Skye tells the kind from the methods, here `aencode`. The class writes two `async` methods and the size of a vector (the
`VectorEncoderInterface` Port); `encode` and `encode_batch` are derived from them, so you never write the sync forms:

```python
--8<-- "examples/plugins/embedding_provider.py:22:47"
```

`skye.provider("hash-embed", provider_type="embedding")` builds it, as it builds the built-in embedding providers. When the provider has a
key variable, an endpoint, or models with their own vector sizes, pass `profile=` to the decorator (the size of a model is
`info={"vector_dimension": 1536}` in its `ModelProfile`).

## Use the vectors

Skye has no vector database of its own. Keep the vectors where your application searches them (PostgreSQL with pgvector, OpenSearch,
a managed vector store), and use the same model to encode the documents and the queries: vectors of two models cannot be compared.

## See also

- [Call a provider](call-a-provider.md): credentials of each provider.
- [`skye.models` API reference](../../reference/api/models.md): the embedding provider classes.
- [Custom provider](../extend/custom-provider.md): the decorator `@plugins.provider`, profiles and packages.
- Examples: [`providers/embeddings_example.py`](https://github.com/ggiallo28/skye/blob/main/examples/providers/embeddings_example.py),
  [`plugins/embedding_provider.py`](https://github.com/ggiallo28/skye/blob/main/examples/plugins/embedding_provider.py).
