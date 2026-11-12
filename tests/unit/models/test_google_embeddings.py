"""Unit tests for the Google embedding provider (REST, no SDK)."""

import ast
from pathlib import Path
from unittest.mock import patch

import pytest

import skye.models.plugins.google.embeddings as mod
from skye.auth.plugins.google.source import GoogleBearerAuth
from skye.models.plugins.google.embeddings import GoogleEmbeddingProvider
from skye.models.utilities.rest import JsonObject


def make(**kw: object) -> GoogleEmbeddingProvider:
    return GoogleEmbeddingProvider(
        model="text-embedding-004", project_id="p", location="us-central1",
        credentials=GoogleBearerAuth("tok"), **kw,
    )


def test_init() -> None:
    e = GoogleEmbeddingProvider(model="m", project_id="p", location="l", credentials_path="/x")
    assert (e.model, e.project_id, e.location) == ("m", "p", "l")
    assert e.config["credentials_path"] == "/x"


def test_client_is_none_and_no_sdk() -> None:
    assert make().client is None
    tree = ast.parse(Path(mod.__file__).read_text())
    names = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    names += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    assert not [n for n in names if n.startswith(("google.cloud", "vertexai"))]


def test_encode_batch_rest_call() -> None:
    resp = JsonObject({"predictions": [{"embeddings": {"values": [0.1, 0.2]}}, {"embeddings": {"values": [0.3, 0.4]}}]})
    with patch("skye.models.utilities.rest.post_json", return_value=resp) as post:
        out = make().encode_batch(["a", "b"])
    assert out == [[0.1, 0.2], [0.3, 0.4]]
    url, body = post.call_args[0]
    assert url == (
        "https://us-central1-aiplatform.googleapis.com/v1/projects/p/locations/us-central1"
        "/publishers/google/models/text-embedding-004:predict"
    )
    assert body == {"instances": [{"content": "a"}, {"content": "b"}]}
    assert isinstance(post.call_args.kwargs["authenticator"], GoogleBearerAuth)


def test_encode_single() -> None:
    resp = JsonObject({"predictions": [{"embeddings": {"values": [1.0]}}]})
    with patch("skye.models.utilities.rest.post_json", return_value=resp):
        assert make().encode("x") == [1.0]


def test_chunks_over_250() -> None:
    resp = JsonObject({"predictions": [{"embeddings": {"values": [0.0]}}] * 250})
    with patch("skye.models.utilities.rest.post_json", return_value=resp) as post:
        out = make()._encode_batch_impl(["t"] * 250 + ["u"])
    assert post.call_count == 2 and len(out) == 500


def test_dimensions() -> None:
    assert make().get_vector_dimension() == 768
    with pytest.raises(ValueError):
        GoogleEmbeddingProvider(model="zzz", project_id="p", location="l").get_vector_dimension()
