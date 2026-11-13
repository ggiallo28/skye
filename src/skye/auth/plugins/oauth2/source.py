"""OAuth2 flows over ``base/http.py``: client credentials and token exchange (RFC 8693).

Both yield a bearer token, cached until shortly before it expires; the secrets (client secret,
subject token) never appear in a ``repr`` or an error message.
"""

from __future__ import annotations

import json
import urllib.parse
from collections.abc import Callable, Mapping

from skye.auth.cache import CachedBearerAuth, TokenCache
from skye.base import http
from skye.base.exceptions import ConfigurationError, ProviderError

DEFAULT_TTL = 3600.0
TOKEN_EXCHANGE_GRANT = "urn:ietf:params:oauth:grant-type:token-exchange"


def token_request(
    url: str,
    form: Mapping[str, str],
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float = 10.0,
    provider: str = "oauth2",
) -> tuple[str, float]:
    """POST a form to a token endpoint and return ``(access_token, seconds_valid)``.

    Args:
        url: The token endpoint.
        form: The form fields (``grant_type`` and the rest).
        headers: Extra headers.
        timeout: Seconds before the request gives up.
        provider: The provider named in an error.

    Raises:
        ProviderError: On an HTTP error or a response without an access token. The message does not
            repeat the request body.
    """
    data = urllib.parse.urlencode(dict(form)).encode("utf-8")
    hdrs = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        **(headers or {}),
    }
    raw = http.send_bytes(url, data, headers=hdrs, timeout=timeout, provider=provider)
    try:
        payload = json.loads(raw.decode("utf-8"))
        return str(payload["access_token"]), float(payload.get("expires_in", DEFAULT_TTL))
    except (ValueError, KeyError, TypeError) as error:
        raise ProviderError(
            f"The token endpoint {url} returned an unexpected response", provider=provider
        ) from error


class ClientCredentialsAuth(CachedBearerAuth):
    """Bearer token from the OAuth2 client-credentials flow.

    Args:
        token_url: The token endpoint.
        client_id: The client id.
        client_secret: The client secret.
        scope: Space-separated scopes.
        audience: The ``audience`` parameter some servers ask for.
        extra: Further form fields.
        cache: A cache to share.
    """

    def __init__(
        self,
        token_url: str,
        client_id: str,
        client_secret: str,
        *,
        scope: str | None = None,
        audience: str | None = None,
        extra: Mapping[str, str] | None = None,
        cache: TokenCache | None = None,
    ) -> None:
        if not (token_url and client_id and client_secret):
            raise ConfigurationError(
                "Client credentials need token_url, client_id and client_secret"
            )
        form = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        }
        if scope:
            form["scope"] = scope
        if audience:
            form["audience"] = audience
        form.update(extra or {})
        super().__init__(
            f"oauth2:cc:{token_url}:{client_id}:{scope or ''}",
            lambda: token_request(token_url, form),
            cache=cache,
        )


class TokenExchangeAuth(CachedBearerAuth):
    """Bearer token from a token exchange: a subject token (file or callable) for an access token.

    Args:
        token_url: The token endpoint of the security token service.
        subject_token: The subject token, or a callable returning it (read again on each exchange).
        subject_token_type: The token type URN of the subject token.
        audience: The audience of the exchange.
        scope: Space-separated scopes.
        extra: Further form fields.
        cache: A cache to share.
    """

    def __init__(
        self,
        token_url: str,
        subject_token: str | Callable[[], str],
        *,
        subject_token_type: str = "urn:ietf:params:oauth:token-type:jwt",
        audience: str | None = None,
        scope: str | None = None,
        extra: Mapping[str, str] | None = None,
        cache: TokenCache | None = None,
    ) -> None:
        def fetch() -> tuple[str, float]:
            token = subject_token() if callable(subject_token) else subject_token
            form = {
                "grant_type": TOKEN_EXCHANGE_GRANT,
                "subject_token": token,
                "subject_token_type": subject_token_type,
                "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
            }
            if audience:
                form["audience"] = audience
            if scope:
                form["scope"] = scope
            form.update(extra or {})
            return token_request(token_url, form)

        super().__init__(
            f"oauth2:tx:{token_url}:{audience or ''}:{scope or ''}", fetch, cache=cache
        )


def file_token(path: str) -> Callable[[], str]:
    """A callable that reads a token file (federated or web-identity token) on each call."""

    def read() -> str:
        try:
            with open(path, encoding="utf-8") as handle:
                return handle.read().strip()
        except OSError as error:
            raise ConfigurationError(
                f"Cannot read the token file {path}", details={"path": path}
            ) from error

    return read
