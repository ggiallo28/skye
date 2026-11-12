"""models/utilities/rest.py: JsonObject view, authenticated body signing, SSE JSON stream."""

import io
from unittest.mock import patch

import pytest

from skye.models.utilities import rest


def test_json_object_attribute_and_item_access():
    o = rest.wrap({"a": {"b": [1, {"c": 2}]}, "n": None})
    assert o.a.b[1].c == 2 and o["a"].b[0] == 1 and o.n is None
    assert o.get("missing", 7) == 7 and "a" in o
    assert not hasattr(o, "missing")
    with pytest.raises(AttributeError):
        o.x = 1


class _Auth:
    def apply(self, method, url, headers, body=b""):
        return {**headers, "X-Signed": str(len(body))}


def test_post_json_signs_the_exact_body_sent():
    seen = {}

    def fake_send(url, data, *, headers, method, timeout, provider):
        seen.update(data=data, headers=headers)
        return b'{"ok": true}'

    with patch("skye.base.http.send_bytes", fake_send):
        out = rest.post_json("https://x/y", {"k": "v"}, authenticator=_Auth(), provider="t")
    assert out.ok is True
    assert seen["data"] == b'{"k":"v"}' and seen["headers"]["X-Signed"] == "9"


def test_stream_sse_json_stops_at_done():
    stream = io.BytesIO(b'data: {"i": 1}\n\ndata: {"i": 2}\n\ndata: [DONE]\n\ndata: {"i": 3}\n\n')
    with patch("skye.base.http.open_stream", lambda *a, **k: stream):
        got = [e.i for e in rest.stream_sse_json("https://x", {"s": 1})]
    assert got == [1, 2]
