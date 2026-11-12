"""Unit tests for the Google multimodal embedding provider (REST, no SDK)."""

import ast
from pathlib import Path
from unittest.mock import patch

import pytest

import skye.models.plugins.google.multimodal_embeddings as mod
from skye.auth.plugins.google.source import GoogleBearerAuth
from skye.models.plugins.google.multimodal_embeddings import GoogleMultimodalEmbeddingProvider
from skye.models.utilities.rest import JsonObject

URL = (
    "https://us-central1-aiplatform.googleapis.com/v1/projects/p/locations/us-central1"
    "/publishers/google/models/multimodalembedding@001:predict"
)


def make() -> GoogleMultimodalEmbeddingProvider:
    return GoogleMultimodalEmbeddingProvider(project_id="p", location="us-central1", credentials=GoogleBearerAuth("t"))


def test_init_and_no_sdk() -> None:
    e = GoogleMultimodalEmbeddingProvider(project_id="p", location="l", credentials_path="/x")
    assert e.model == "multimodalembedding@001" and e.config["credentials_path"] == "/x"
    assert e.client is None
    tree = ast.parse(Path(mod.__file__).read_text())
    names = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    names += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    assert not [n for n in names if n.startswith(("google.cloud", "vertexai"))]


@pytest.mark.parametrize(
    "item,expected",
    [("a.jpg", True), ("A.PNG", True), ("https://x.com/i.jpeg", True), ("data:image/png;base64,AA", True), ("hello", False)],
)
def test_is_image_input(item: str, expected: bool) -> None:
    assert make()._is_image_input(item) is expected


def test_encode_text() -> None:
    with patch("skye.models.utilities.rest.post_json", return_value=JsonObject({"predictions": [{"textEmbedding": [0.1, 0.2]}]})) as post:
        assert make().encode("hi") == [0.1, 0.2]
    assert post.call_args[0] == (URL, {"instances": [{"text": "hi"}]})


def test_encode_data_url_image() -> None:
    with patch("skye.models.utilities.rest.post_json", return_value=JsonObject({"predictions": [{"imageEmbedding": [1.0]}]})) as post:
        assert make().encode("data:image/png;base64,QUJD") == [1.0]
    assert post.call_args[0][1] == {"instances": [{"image": {"bytesBase64Encoded": "QUJD"}}]}


def test_encode_gcs_image() -> None:
    with patch("skye.models.utilities.rest.post_json", return_value=JsonObject({"predictions": [{"imageEmbedding": [1.0]}]})) as post:
        make()._encode_image("gs://b/i.png")
    assert post.call_args[0][1] == {"instances": [{"image": {"gcsUri": "gs://b/i.png"}}]}


def test_encode_local_file_image(tmp_path: Path) -> None:
    f = tmp_path / "i.png"
    f.write_bytes(b"ABC")
    with patch("skye.models.utilities.rest.post_json", return_value=JsonObject({"predictions": [{"imageEmbedding": [2.0]}]})) as post:
        assert make().encode(str(f)) == [2.0]
    assert post.call_args[0][1]["instances"][0]["image"]["bytesBase64Encoded"] == "QUJD"


def test_encode_http_image_downloads() -> None:
    with patch("skye.base.http.send_bytes", return_value=b"ABC") as dl, patch(
        "skye.models.utilities.rest.post_json", return_value=JsonObject({"predictions": [{"imageEmbedding": [3.0]}]})
    ) as post:
        assert make()._encode_image("https://x.com/i.png") == [3.0]
    assert dl.call_args[0][0] == "https://x.com/i.png"
    assert post.call_args[0][1]["instances"][0]["image"]["bytesBase64Encoded"] == "QUJD"


def test_batch_mixed_and_dimension() -> None:
    resp = [JsonObject({"predictions": [{"textEmbedding": [1.0]}]}), JsonObject({"predictions": [{"imageEmbedding": [2.0]}]})]
    with patch("skye.models.utilities.rest.post_json", side_effect=resp):
        assert make().encode_batch(["text", "gs://b/i.png"]) == [[1.0], [2.0]]
    assert make().get_vector_dimension() == 1408
