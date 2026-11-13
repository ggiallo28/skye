"""Stdlib AWS Signature Version 4 signer (hashlib / hmac / datetime only)."""

from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
from urllib.parse import quote, unquote, urlsplit

ALGORITHM = "AWS4-HMAC-SHA256"


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _canonical_query(query: str) -> str:
    pairs = []
    for part in query.split("&") if query else []:
        k, _, v = part.partition("=")
        pairs.append((quote(unquote(k), safe="-_.~"), quote(unquote(v), safe="-_.~")))
    return "&".join(f"{k}={v}" for k, v in sorted(pairs))


def sign_request(
    method: str,
    url: str,
    *,
    region: str,
    service: str,
    access_key: str,
    secret_key: str,
    session_token: str | None = None,
    headers: dict[str, str] | None = None,
    payload: bytes = b"",
    now: _dt.datetime | None = None,
) -> dict[str, str]:
    """Return headers (input headers + ``x-amz-date``, ``Authorization`` ...).

    ``host`` is derived from the URL. ``now`` is injectable for testing.
    """
    now = now or _dt.datetime.now(_dt.UTC)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = amz_date[:8]

    parts = urlsplit(url)
    signed: dict[str, str] = {k.lower(): " ".join(v.split()) for k, v in (headers or {}).items()}
    signed["host"] = parts.netloc
    signed["x-amz-date"] = amz_date
    if session_token:
        signed["x-amz-security-token"] = session_token

    names = sorted(signed)
    canonical_headers = "".join(f"{n}:{signed[n]}\n" for n in names)
    signed_headers = ";".join(names)
    canonical_request = "\n".join(
        [
            method.upper(),
            quote(parts.path or "/", safe="/-_.~%"),
            _canonical_query(parts.query),
            canonical_headers,
            signed_headers,
            _sha256_hex(payload),
        ]
    )

    scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(
        [ALGORITHM, amz_date, scope, _sha256_hex(canonical_request.encode("utf-8"))]
    )

    key = _hmac(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    for part in (region, service, "aws4_request"):
        key = _hmac(key, part)
    signature = hmac.new(key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    out = dict(headers or {})
    out["x-amz-date"] = amz_date
    out["Host"] = parts.netloc
    if session_token:
        out["x-amz-security-token"] = session_token
    out["Authorization"] = (
        f"{ALGORITHM} Credential={access_key}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return out
