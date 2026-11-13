"""Tests for the stdlib eventstream decoder."""

import io
import json
import struct
import zlib
from unittest.mock import patch

import pytest

from skye.base.exceptions import ProviderError
from skye.models.utilities import eventstream


def _hdr(name: str, value: str) -> bytes:
    n, v = name.encode(), value.encode()
    return bytes([len(n)]) + n + b"\x07" + struct.pack(">H", len(v)) + v


def frame(event_type: str, payload: dict, message_type: str = "event") -> bytes:
    key = ":exception-type" if message_type == "exception" else ":event-type"
    headers = _hdr(":message-type", message_type) + _hdr(key, event_type) + _hdr(":content-type", "application/json")
    body = json.dumps(payload).encode()
    total = 16 + len(headers) + len(body)
    prelude = struct.pack(">II", total, len(headers))
    prelude += struct.pack(">I", zlib.crc32(prelude) & 0xFFFFFFFF)
    msg = prelude + headers + body
    return msg + struct.pack(">I", zlib.crc32(msg) & 0xFFFFFFFF)


def test_decode_events():
    data = frame("contentBlockDelta", {"delta": {"text": "Hi"}}) + frame("messageStop", {"stopReason": "end_turn"})
    events = list(eventstream.decode_events(io.BytesIO(data)))
    assert events == [
        {"contentBlockDelta": {"delta": {"text": "Hi"}}},
        {"messageStop": {"stopReason": "end_turn"}},
    ]


def test_headers_parsed():
    (headers, payload), = eventstream.decode_messages(io.BytesIO(frame("x", {"a": 1})))
    assert headers[":event-type"] == "x"
    assert json.loads(payload) == {"a": 1}


def test_crc_mismatch():
    data = bytearray(frame("x", {"a": 1}))
    data[-1] ^= 0xFF
    with pytest.raises(ValueError, match="CRC"):
        list(eventstream.decode_messages(io.BytesIO(bytes(data))))


def test_truncated():
    with pytest.raises(ValueError, match="truncated"):
        list(eventstream.decode_messages(io.BytesIO(frame("x", {})[:-3])))


def test_exception_frame_raises():
    data = frame("throttlingException", {"message": "slow down"}, "exception")
    with pytest.raises(ProviderError, match="slow down"):
        list(eventstream.decode_events(io.BytesIO(data)))


def test_post_eventstream_json_signs_and_streams():
    data = frame("messageStop", {"stopReason": "end_turn"})

    class Resp(io.BytesIO):
        pass

    class Auth:
        def apply(self, method, url, headers, body=b""):
            return {**headers, "Authorization": "signed"}

    with patch("skye.base.http.open_stream", return_value=Resp(data)) as op:
        out = list(eventstream.post_eventstream_json("https://h/x", {"a": 1}, authenticator=Auth()))
    assert out == [{"messageStop": {"stopReason": "end_turn"}}]
    assert op.call_args.args[1] == b'{"a":1}'
    assert op.call_args.kwargs["headers"]["Authorization"] == "signed"
