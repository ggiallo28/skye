# D12
"""RS256 assertions with the pure-Python ``rsa`` (: not ``google-auth``, not ``cryptography``).

``rsa`` is the one third-party library of ``auth`` and is imported only when a token is minted,
through ``missing_extra`` (so ``MissingExtraError`` names the extra ``auth`` when it is absent).
A service-account key in PKCS#8 form (the ``BEGIN PRIVATE KEY`` of a Google JSON key file) is
unwrapped here with a small DER reader, because ``rsa`` itself reads only PKCS#1.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import time
from collections.abc import Callable, Mapping
from typing import Any

from skye.base.exceptions import ConfigurationError
from skye.base.lazy_import import missing_extra

_PEM = re.compile(r"-----BEGIN ([A-Z0-9 ]+)-----(.+?)-----END \1-----", re.S)


def b64url(data: bytes) -> str:
    """Base64url without padding, as JWTs use."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _der(data: bytes, pos: int = 0) -> tuple[int, bytes, int]:
    """One DER element at ``pos``: ``(tag, content, position after it)``."""
    tag = data[pos]
    first = data[pos + 1]
    if first < 0x80:
        length, start = first, pos + 2
    else:
        count = first & 0x7F
        length, start = int.from_bytes(data[pos + 2 : pos + 2 + count], "big"), pos + 2 + count
    end = start + length
    if end > len(data):
        raise ValueError("truncated DER")
    return tag, data[start:end], end


def pem_blocks(text: str) -> list[tuple[str, bytes]]:
    """The ``(label, DER bytes)`` of every PEM block in ``text``."""
    blocks = []
    for label, body in _PEM.findall(text):
        try:
            blocks.append((label, base64.b64decode("".join(body.split()), validate=True)))
        except (binascii.Error, ValueError):
            raise ConfigurationError(
                f"A PEM block labelled {label!r} is not valid base64"
            ) from None
    return blocks


def _pkcs1_der(pem: str) -> tuple[bytes, str]:
    """The PKCS#1 ``RSAPrivateKey`` DER inside a PEM key (PKCS#1 as it is, PKCS#8 unwrapped)."""
    for label, der in pem_blocks(pem):
        if label == "RSA PRIVATE KEY":
            return der, label
        if label == "PRIVATE KEY":
            try:
                _, sequence, _ = _der(der)
                _, _version, pos = _der(sequence)
                _, _algorithm, pos = _der(sequence, pos)
                tag, inner, _ = _der(sequence, pos)
            except (ValueError, IndexError):
                raise ConfigurationError("The PKCS#8 private key is malformed") from None
            if tag != 0x04:
                raise ConfigurationError("The PKCS#8 private key is malformed")
            return inner, label
        if label == "ENCRYPTED PRIVATE KEY":
            raise ConfigurationError("An encrypted private key is not supported: decrypt it first")
    raise ConfigurationError(
        "No RSA private key found: expected a PEM 'PRIVATE KEY' or 'RSA PRIVATE KEY' block"
    )


def load_private_key(pem: str) -> Any:
    """Read an RSA private key (PKCS#1 or PKCS#8 PEM) as an ``rsa.PrivateKey``.

    Raises:
        MissingExtraError: When ``rsa`` is not installed (extra ``auth``).
        ConfigurationError: When the PEM holds no usable RSA key. The key is never in the message.
    """
    rsa = missing_extra("rsa", extra="auth")
    der, _ = _pkcs1_der(pem)
    try:
        return rsa.PrivateKey.load_pkcs1(der, format="DER")
    except Exception:
        raise ConfigurationError("The RSA private key could not be read") from None


def sign_rs256_jwt(
    claims: Mapping[str, Any], private_key_pem: str, *, headers: Mapping[str, Any] | None = None
) -> str:
    """A JWT signed with RS256.

    Args:
        claims: The payload.
        private_key_pem: The RSA private key (PKCS#1 or PKCS#8 PEM).
        headers: Extra header fields (``kid``, ``x5t#S256``).

    Raises:
        MissingExtraError: When ``rsa`` is not installed (extra ``auth``).
    """
    rsa = missing_extra("rsa", extra="auth")
    key = load_private_key(private_key_pem)
    header = {"alg": "RS256", "typ": "JWT", **(headers or {})}
    signing_input = (
        b64url(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + b64url(json.dumps(dict(claims), separators=(",", ":")).encode())
    )
    signature = rsa.sign(signing_input.encode("ascii"), key, "SHA-256")
    return f"{signing_input}.{b64url(signature)}"


def certificate_thumbprint(certificate_pem: str) -> str:
    """The base64url SHA-256 thumbprint of an X.509 certificate (the ``x5t#S256`` header)."""
    for label, der in pem_blocks(certificate_pem):
        if label == "CERTIFICATE":
            return b64url(hashlib.sha256(der).digest())
    raise ConfigurationError("No certificate found: expected a PEM 'CERTIFICATE' block")


def service_account_assertion(
    info: Mapping[str, Any],
    scope: str,
    *,
    audience: str | None = None,
    lifetime: int = 3600,
    clock: Callable[[], float] = time.time,
) -> str:
    """The signed JWT a Google service account sends to the token endpoint (the jwt-bearer grant).

    Args:
        info: The parsed key file (``client_email``, ``private_key``, ``token_uri``).
        scope: Space-separated scopes.
        audience: The token endpoint; the file's ``token_uri`` by default.
        lifetime: Seconds the assertion is valid.
        clock: Seconds since the epoch.
    """
    try:
        email, key = info["client_email"], info["private_key"]
    except KeyError as error:
        raise ConfigurationError(
            f"The service-account file has no {error.args[0]!r} field",
            details={"field": error.args[0]},
        ) from None
    now = int(clock())
    claims = {
        "iss": email,
        "scope": scope,
        "aud": audience or info.get("token_uri") or "https://oauth2.googleapis.com/token",
        "iat": now,
        "exp": now + lifetime,
    }
    headers = {"kid": info["private_key_id"]} if info.get("private_key_id") else None
    return sign_rs256_jwt(claims, key, headers=headers)


def entra_client_assertion(
    tenant_id: str,
    client_id: str,
    private_key_pem: str,
    certificate_pem: str,
    *,
    audience: str | None = None,
    lifetime: int = 600,
    clock: Callable[[], float] = time.time,
) -> str:
    """The signed client assertion Microsoft Entra ID accepts for a certificate credential.

    Args:
        tenant_id: The directory (tenant) id.
        client_id: The application (client) id.
        private_key_pem: The certificate's RSA private key.
        certificate_pem: The certificate (its thumbprint goes in the header).
        audience: The token endpoint; Entra's v2.0 endpoint of the tenant by default.
        lifetime: Seconds the assertion is valid.
        clock: Seconds since the epoch.
    """
    now = int(clock())
    claims = {
        "iss": client_id,
        "sub": client_id,
        "aud": audience or f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
        "jti": b64url(hashlib.sha256(f"{client_id}{now}".encode()).digest()),
        "nbf": now,
        "exp": now + lifetime,
    }
    return sign_rs256_jwt(
        claims, private_key_pem, headers={"x5t#S256": certificate_thumbprint(certificate_pem)}
    )
