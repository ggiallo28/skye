# decision D104
"""Minimal stdlib HTTP helper (``urllib.request`` + ``json``), shared by ``models`` and ``tools``.

Pure standard library: no third-party import. ``models.utilities.rest`` builds on the
JSON helpers; ``tools.remote_api`` uses :func:`request`.

A failure is raised as the :class:`ProviderError` subclass the response calls for:
429 is :class:`RateLimitError`, 5xx :class:`ServerError`, 401 and 403 :class:`AuthenticationError`,
any other 4xx :class:`BadRequestError` (:class:`ContentPolicyError` when the body names a content
policy), a timeout or a dropped connection :class:`ProviderTimeoutError`. The server's
``Retry-After`` (or ``retry-after-ms``) header becomes ``retry_after`` in seconds.
"""

from __future__ import annotations

import base64
import email.utils
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from skye.base.exceptions import (
    AuthenticationError,
    BadRequestError,
    ContentPolicyError,
    ProviderError,
    ProviderTimeoutError,
    RateLimitError,
    ServerError,
)

#: Text in an error body that marks a content-policy refusal (OpenAI, Azure OpenAI), lowercase.
CONTENT_POLICY_MARKERS = (
    "content_policy",
    "content_filter",
    "content policy",
    "content management policy",
)


def _build(
    url: str, payload: Any, headers: dict[str, str] | None, method: str
) -> urllib.request.Request:
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    return urllib.request.Request(url, data=body, headers=hdrs, method=method)


def retry_after_seconds(headers: Any) -> float | None:
    """The wait a response asks for, in seconds, from ``retry-after-ms`` or ``Retry-After``.

    ``Retry-After`` is a number of seconds or an HTTP date (a date in the past gives ``0.0``).

    Args:
        headers: The response headers (anything with ``get``), or ``None``.

    Returns:
        The seconds to wait, or ``None`` when the headers say nothing readable.
    """
    if headers is None:
        return None
    millis = headers.get("retry-after-ms")
    if millis:
        try:
            return max(float(millis) / 1000.0, 0.0)
        except ValueError:
            pass
    value = headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(float(value), 0.0)
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return float(max(when.timestamp() - time.time(), 0.0))


def _status_class(status: int, body: str) -> type[ProviderError]:
    if status == 429:
        return RateLimitError
    if status >= 500:
        return ServerError
    if status in (401, 403):
        return AuthenticationError
    if 400 <= status < 500:
        lowered = body.lower()
        if any(marker in lowered for marker in CONTENT_POLICY_MARKERS):
            return ContentPolicyError
        return BadRequestError
    return ProviderError


def _is_timeout(e: BaseException) -> bool:
    reason = e.reason if isinstance(e, urllib.error.URLError) else e
    if isinstance(reason, TimeoutError):  # socket.timeout is TimeoutError
        return True
    return isinstance(reason, ConnectionError) and not isinstance(reason, ConnectionRefusedError)


def _wrap(e: Exception, provider: str) -> ProviderError:
    err: ProviderError
    if isinstance(e, urllib.error.HTTPError):
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")
        except Exception:  # pragma: no cover - best effort
            pass
        cls = _status_class(e.code, detail)
        err = cls(
            f"HTTP {e.code}: {detail or e.reason}",
            provider=provider,
            status_code=e.code,
            retry_after=retry_after_seconds(e.headers),
        )
    elif _is_timeout(e):
        err = ProviderTimeoutError(f"Timeout or dropped connection: {e}", provider=provider)
    else:
        err = ProviderError(f"Transport error: {e}", provider=provider)
    err.__cause__ = e
    return err


def request_json(
    url: str,
    payload: Any = None,
    *,
    headers: dict[str, str] | None = None,
    method: str = "POST",
    timeout: float = 60.0,
    provider: str = "http",
) -> Any:
    """Send a JSON request and return the decoded JSON response."""
    req = _build(url, payload, headers, method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            raw = resp.read()
    except (urllib.error.URLError, OSError) as e:
        raise _wrap(e, provider) from e
    return json.loads(raw.decode("utf-8")) if raw else None


def stream_lines(
    url: str,
    payload: Any = None,
    *,
    headers: dict[str, str] | None = None,
    method: str = "POST",
    timeout: float = 60.0,
    provider: str = "http",
) -> Iterator[bytes]:
    """Send a request and yield raw response lines (feed to ``parse_sse``)."""
    req = _build(url, payload, headers, method)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)  # noqa: S310
    except (urllib.error.URLError, OSError) as e:
        raise _wrap(e, provider) from e
    with resp:
        yield from resp


def send_bytes(
    url: str,
    data: bytes | None = None,
    *,
    headers: dict[str, str] | None = None,
    method: str = "POST",
    timeout: float = 60.0,
    provider: str = "http",
) -> bytes:
    """Send a request whose body is already serialised (so it can be signed) and return the raw body."""
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.read()  # type: ignore[no-any-return]
    except (urllib.error.URLError, OSError) as e:
        raise _wrap(e, provider) from e


def open_stream(
    url: str,
    data: bytes | None = None,
    *,
    headers: dict[str, str] | None = None,
    method: str = "POST",
    timeout: float = 60.0,
    provider: str = "http",
) -> Any:
    """Open a request with a pre-serialised body and return the response object (a context manager).

    The caller iterates it (lines) or calls ``read(n)`` (binary framing) and closes it.
    """
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310
    except (urllib.error.URLError, OSError) as e:
        raise _wrap(e, provider) from e


@dataclass(frozen=True)
class HttpResponse:
    """Status code and decoded body of a completed request."""

    status_code: int
    text: str

    def json(self) -> Any:
        """Decode the body as JSON (raises ``ValueError`` when it is not JSON)."""
        return json.loads(self.text)


def request(
    url: str,
    method: str = "GET",
    *,
    params: dict[str, Any] | None = None,
    json_body: Any = None,
    headers: dict[str, str] | None = None,
    auth: tuple[str, str] | None = None,
    timeout: float = 30.0,
    provider: str = "http",
) -> HttpResponse:
    """Send a request (query ``params`` and/or a JSON body) and return the raw response.

    Raises the :class:`ProviderError` subclass of the status (with ``status_code``) on an HTTP
    error status, :class:`ProviderTimeoutError` on a timeout, a plain ``ProviderError`` on another
    transport failure.
    """
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    hdrs = dict(headers or {})
    data = None
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    if auth:
        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode("ascii")
        hdrs.setdefault("Authorization", f"Basic {token}")
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            status = getattr(resp, "status", 200)
            text = resp.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as e:
        raise _wrap(e, provider) from e
    return HttpResponse(status_code=status, text=text)
