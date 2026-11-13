# Requirement 11.2
"""The 401-refresh-and-retry-once helper shared by the HTTP callers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TypeVar

from skye.base.exceptions import ProviderError
from skye.base.interfaces.authentication import AuthenticationInterface

T = TypeVar("T")


def send_with_refresh(
    send: Callable[[dict[str, str]], T],
    authenticator: AuthenticationInterface,
    method: str,
    url: str,
    headers: Mapping[str, str] | None = None,
    body: bytes = b"",
) -> T:
    """Send an authenticated request; on a 401 refresh the credential and send it once more.

    A second 401 (or any other error) is raised as it is: there is no loop. An authenticator
    with no ``refresh()`` method cannot refresh, so its 401 is raised at once.

    Args:
        send: Sends a request with the given authenticated headers and returns its result; it raises
            ``ProviderError`` (with ``status_code``) on an HTTP error.
        authenticator: The authenticator; its ``refresh()`` method, if any, drops the cached token.
        method: The HTTP method.
        url: The URL.
        headers: The headers before authentication.
        body: The request body (SigV4 signs it).
    """
    base = dict(headers or {})
    try:
        return send(authenticator.apply(method, url, base, body))
    except ProviderError as error:
        refresh = getattr(authenticator, "refresh", None)
        if error.details.get("status_code") != 401 or refresh is None:
            raise
        refresh()
        return send(authenticator.apply(method, url, base, body))
