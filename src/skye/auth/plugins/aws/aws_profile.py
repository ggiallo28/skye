"""AWS profiles in ``~/.aws/config``: assume-role, web identity and IAM Identity Center (SSO).

SSO needs an earlier ``aws sso login``: ``auth`` reads the token that command left in
``~/.aws/sso/cache`` and, when it is missing or expired, raises ``LoginRequiredError`` saying to log
in again. It never launches a login (Requirement 11.3).
"""

from __future__ import annotations

import configparser
import datetime as _dt
import hashlib
import json
import urllib.parse
from collections.abc import Mapping
from pathlib import Path

from skye.auth.errors import LoginRequiredError
from skye.base import http
from skye.base.exceptions import ConfigurationError


def config_path(env: Mapping[str, str]) -> Path:
    """The AWS config file: ``AWS_CONFIG_FILE`` or ``~/.aws/config``."""
    return Path(env.get("AWS_CONFIG_FILE") or Path.home() / ".aws" / "config")


def read_profile(name: str, env: Mapping[str, str]) -> dict[str, str]:
    """The settings of a profile (and its ``sso-session``), or ``{}`` when it is not in the file."""
    parser = configparser.ConfigParser()
    try:
        parser.read(config_path(env))
    except (OSError, configparser.Error):
        return {}
    for section in (name if name == "default" else f"profile {name}", name):
        if parser.has_section(section):
            settings = dict(parser[section])
            session = settings.get("sso_session")
            if session and parser.has_section(f"sso-session {session}"):
                settings = {**dict(parser[f"sso-session {session}"]), **settings}
            return settings
    return {}


def sso_cache_file(settings: Mapping[str, str], env: Mapping[str, str]) -> Path:
    """The file ``aws sso login`` writes: the SHA-1 of the session name (or the start URL)."""
    key = settings.get("sso_session") or settings.get("sso_start_url", "")
    base = Path(env.get("AWS_SSO_CACHE_DIR") or Path.home() / ".aws" / "sso" / "cache")
    return (
        base / f"{hashlib.sha1(key.encode('utf-8')).hexdigest()}.json"
    )  # noqa: S324 - the file name AWS uses


def sso_credentials(
    profile: str,
    settings: Mapping[str, str],
    env: Mapping[str, str],
    *,
    endpoint: str | None = None,
    now: _dt.datetime | None = None,
) -> tuple[str, str, str, _dt.datetime]:
    """Role credentials for an SSO profile, from the cached login token.

    Returns:
        ``(access key, secret key, session token, expiry)``.

    Raises:
        LoginRequiredError: The login cache is missing or expired: run ``aws sso login`` again.
        ConfigurationError: The profile lacks an ``sso_*`` setting.
    """
    command = f"aws sso login --profile {profile}"
    missing = [k for k in ("sso_account_id", "sso_role_name", "sso_region") if not settings.get(k)]
    if missing or not (settings.get("sso_session") or settings.get("sso_start_url")):
        raise ConfigurationError(
            f"The SSO profile {profile!r} needs sso_account_id, sso_role_name, sso_region and "
            "sso_session or sso_start_url",
            details={"profile": profile, "missing": missing},
        )
    path = sso_cache_file(settings, env)
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        token = cached["accessToken"]
        expires = _dt.datetime.fromisoformat(str(cached["expiresAt"]).replace("Z", "+00:00"))
    except (OSError, ValueError, KeyError):
        raise LoginRequiredError("aws", command, "missing") from None
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=_dt.timezone.utc)
    if expires <= (now or _dt.datetime.now(_dt.timezone.utc)):
        raise LoginRequiredError("aws", command, "expired")
    base = endpoint or f"https://portal.sso.{settings['sso_region']}.amazonaws.com"
    query = urllib.parse.urlencode(
        {"account_id": settings["sso_account_id"], "role_name": settings["sso_role_name"]}
    )
    raw = http.send_bytes(
        f"{base}/federation/credentials?{query}",
        None,
        headers={"x-amz-sso_bearer_token": token},
        method="GET",
        timeout=10.0,
        provider="aws",
    )
    try:
        role = json.loads(raw.decode("utf-8"))["roleCredentials"]
        expiry = _dt.datetime.fromtimestamp(int(role["expiration"]) / 1000, _dt.timezone.utc)
        return role["accessKeyId"], role["secretAccessKey"], role["sessionToken"], expiry
    except (ValueError, KeyError, TypeError):
        raise ConfigurationError(
            "The SSO portal returned no role credentials", details={"profile": profile}
        ) from None
