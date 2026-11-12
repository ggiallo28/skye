"""Images travel inside a ``UserMessage`` and reach each provider in its own shape (task 5.2)."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

import skye
from skye.base.exceptions import ProviderError, UnsupportedModalityError, ValidationError
from skye.base.messages import UserMessage
from skye.models.utilities.retry import is_retryable
from tests.examples.fake_network import fake_urlopen

PIXEL = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
B64 = base64.b64encode(PIXEL).decode()


def _sent(provider: str, model: str, message: UserMessage, **options: Any) -> dict[str, Any]:
    """Run one completion over the fake network and return the JSON body that was sent."""
    bodies: list[dict[str, Any]] = []

    def capture(req: Any, *args: Any, **kwargs: Any) -> Any:
        if req.data:
            bodies.append(json.loads(req.data))
        return fake_urlopen(req, *args, **kwargs)

    client = skye.provider(provider, **options)
    with patch("urllib.request.urlopen", capture):
        client.complete(messages=[message], model=model)
    return bodies[-1]


def test_user_message_keeps_images_and_serializes_them():
    msg = UserMessage(content="look", images=["https://x/y.png", PIXEL])
    assert msg.images[0] == "https://x/y.png"
    dumped = msg.to_dict()
    assert dumped["images"][1] == "data:image/png;base64," + B64
    json.dumps(dumped)


def test_user_message_without_images_is_unchanged():
    assert UserMessage(content="hi").to_dict() == {"role": "user", "content": "hi"}


def test_openai_gets_text_then_image_url_parts(tmp_path: Path):
    path = tmp_path / "p.png"
    path.write_bytes(PIXEL)
    body = _sent("openai", "gpt-4", UserMessage(content="what?", images=["https://x/y.png", path]), api_key="k")
    parts = body["messages"][0]["content"]
    assert parts[0] == {"type": "text", "text": "what?"}
    assert parts[1] == {"type": "image_url", "image_url": {"url": "https://x/y.png"}}
    assert parts[2]["image_url"]["url"] == "data:image/png;base64," + B64


def test_anthropic_gets_image_blocks_before_the_text():
    body = _sent("anthropic", "claude-3-opus-20240229", UserMessage(content="what?", images=[PIXEL, "https://x/y.png"]), api_key="k")
    blocks = body["messages"][0]["content"]
    assert blocks[0] == {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": B64}}
    assert blocks[1] == {"type": "image", "source": {"type": "url", "url": "https://x/y.png"}}
    assert blocks[2] == {"type": "text", "text": "what?"}


def test_bedrock_sends_image_bytes_as_base64():
    body = _sent("bedrock", "anthropic.claude-3-sonnet", UserMessage(content="what?", images=[PIXEL]), region_name="us-east-1", aws_access_key_id="a", aws_secret_access_key="b")
    content = body["messages"][0]["content"]
    assert content[0] == {"image": {"format": "png", "source": {"bytes": B64}}}
    assert content[1] == {"text": "what?"}


def test_bedrock_rejects_an_image_url():
    """Requirement 26.3: a ProviderError that names the modality; the input is left unchanged; nothing is retried."""
    message = UserMessage(content="x", images=["https://x/y.png"])
    with pytest.raises(UnsupportedModalityError) as caught:
        _sent("bedrock", "anthropic.claude-3-sonnet", message, region_name="us-east-1", aws_access_key_id="a", aws_secret_access_key="b")
    error = caught.value
    assert isinstance(error, ProviderError) and not isinstance(error, ValidationError)
    assert error.modality == "image" and error.provider == "bedrock" and error.status_code is None
    assert "image" in str(error)
    assert message.images == ["https://x/y.png"] and message.content == "x"
    assert not is_retryable(error)


def test_google_gets_inline_data_and_file_uri_parts():
    body = _sent("google", "gemini-1.5-pro", UserMessage(content="what?", images=[PIXEL, "https://x/y.png"]), project_id="p", location="us-central1", credentials="token")
    parts = body["contents"][0]["parts"]
    assert parts[0] == {"inlineData": {"mimeType": "image/png", "data": B64}}
    assert parts[1] == {"fileData": {"fileUri": "https://x/y.png"}}
    assert parts[2] == {"text": "what?"}


def test_a_provider_error_keeps_the_http_status(monkeypatch):
    """The status the transport saw reaches the caller (it tells a rate limit from a bad key)."""
    import io
    import urllib.error

    monkeypatch.setattr("skye.models.utilities.retry.time.sleep", lambda seconds: None)

    def urlopen(req: Any, *a: Any, **k: Any) -> Any:
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, io.BytesIO(b"{}"))  # type: ignore[arg-type]

    from skye.base.exceptions import ProviderError

    client = skye.provider("openai", api_key="k")
    with patch("urllib.request.urlopen", urlopen), pytest.raises(ProviderError) as caught:
        client.complete(messages=[UserMessage(content="x")], model="gpt-4")
    assert caught.value.details["status_code"] == 429
