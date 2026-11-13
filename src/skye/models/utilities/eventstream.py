"""Stdlib decoder for the ``application/vnd.amazon.eventstream`` binary framing (Bedrock streams)."""

from __future__ import annotations

import json
import struct
import zlib
from collections.abc import Iterator, Mapping
from typing import Any

from skye.base import http
from skye.base.exceptions import ProviderError
from skye.base.interfaces.authentication import AuthenticationInterface
from skye.models.utilities.rest import prepare

_FIXED = {0: 0, 1: 0, 2: 1, 3: 2, 4: 4, 5: 8, 8: 8, 9: 16}


def _read_exact(resp: Any, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = resp.read(n - len(buf))
        if not chunk:
            break
        buf += chunk
    return buf


def _parse_headers(data: bytes) -> dict[str, Any]:
    headers: dict[str, Any] = {}
    i = 0
    while i < len(data):
        nlen = data[i]
        name = data[i + 1 : i + 1 + nlen].decode("utf-8")
        i += 1 + nlen
        vtype = data[i]
        i += 1
        if vtype in (6, 7):
            (vlen,) = struct.unpack_from(">H", data, i)
            raw = data[i + 2 : i + 2 + vlen]
            headers[name] = raw.decode("utf-8") if vtype == 7 else raw
            i += 2 + vlen
        elif vtype in _FIXED:
            size = _FIXED[vtype]
            headers[name] = True if vtype == 0 else False if vtype == 1 else data[i : i + size]
            i += size
        else:
            raise ValueError(f"unknown eventstream header type {vtype}")
    return headers


def decode_messages(resp: Any) -> Iterator[tuple[dict[str, Any], bytes]]:
    """Yield ``(headers, payload)`` for each frame read from ``resp.read(n)``; verifies CRCs."""
    while True:
        prelude = _read_exact(resp, 12)
        if not prelude:
            return
        if len(prelude) < 12:
            raise ValueError("truncated eventstream prelude")
        total, hlen, pcrc = struct.unpack(">III", prelude)
        if zlib.crc32(prelude[:8]) & 0xFFFFFFFF != pcrc:
            raise ValueError("eventstream prelude CRC mismatch")
        rest = _read_exact(resp, total - 12)
        if len(rest) != total - 12:
            raise ValueError("truncated eventstream message")
        if zlib.crc32(rest[:-4], zlib.crc32(prelude)) & 0xFFFFFFFF != struct.unpack(">I", rest[-4:])[0]:
            raise ValueError("eventstream message CRC mismatch")
        yield _parse_headers(rest[:hlen]), rest[hlen:-4]


def decode_events(resp: Any, provider: str = "bedrock") -> Iterator[dict[str, Any]]:
    """Yield ``{event_type: payload_json}`` for event frames; raise ProviderError on exceptions."""
    for headers, payload in decode_messages(resp):
        body = json.loads(payload.decode("utf-8")) if payload else {}
        kind = headers.get(":message-type", "event")
        if kind == "exception" or kind == "error":
            name = headers.get(":exception-type") or headers.get(":error-code") or "error"
            raise ProviderError(f"{name}: {body.get('message', body)}", provider=provider)
        yield {headers.get(":event-type", "event"): body}


def post_eventstream_json(
    url: str,
    payload: Any,
    *,
    headers: Mapping[str, str] | None = None,
    authenticator: AuthenticationInterface | None = None,
    timeout: float = 60.0,
    provider: str = "http",
) -> Iterator[dict[str, Any]]:
    """POST a JSON body and yield decoded eventstream events as ``{event_type: payload}``."""
    body, hdrs = prepare("POST", url, payload, headers, authenticator)
    resp = http.open_stream(url, body, headers=hdrs, method="POST", timeout=timeout, provider=provider)
    with resp:
        yield from decode_events(resp, provider)


__all__ = ["decode_messages", "decode_events", "post_eventstream_json"]
