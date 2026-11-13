# D104
"""Google: a failed call turned into the ``ProviderError`` it calls for; the profile names
``map_error`` by text."""

from skye.base.exceptions import ProviderError
from skye.models.utilities.error_mapping import build_error


def map_error(error: Exception, provider: str = "google") -> ProviderError:
    """The ``ProviderError`` subclass for an error of a Google client."""
    code = getattr(error, "code", None)
    status_code = code if isinstance(code, int) else None
    name, text = type(error).__name__.lower(), str(error).lower()
    if "resourceexhausted" in name or "rate_limit" in text:
        kind = "rate_limit"
    elif "deadlineexceeded" in name or "timeout" in text:
        kind = "timeout"
    elif "unavailable" in name or "unavailable" in text:
        kind = "service_unavailable"
    elif "unauthenticated" in name or "auth" in text:
        kind = "authentication_error"
    elif "permissiondenied" in name:
        kind = "permission_error"
    else:
        kind = "unknown_error"
    return build_error("Google API error", error, provider, kind, status_code)
