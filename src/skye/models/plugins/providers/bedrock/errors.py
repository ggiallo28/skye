# D104
"""AWS Bedrock: a failed call turned into the ``ProviderError`` it calls for; the profile names
``map_error`` by text."""

from skye.base.exceptions import ProviderError
from skye.models.utilities.error_mapping import build_error


def map_error(error: Exception, provider: str = "bedrock") -> ProviderError:
    """The ``ProviderError`` subclass for a Bedrock error (a botocore ``ClientError`` shape
    included)."""
    error_code = None
    status_code = None
    response = getattr(error, "response", None)
    if isinstance(response, dict):
        error_code = response.get("Error", {}).get("Code")
        status_code = response.get("ResponseMetadata", {}).get("HTTPStatusCode")

    code = error_code.lower() if error_code else ""
    name, text = type(error).__name__.lower(), str(error).lower()
    if "throttling" in code:
        kind = "rate_limit"
    elif "ratelimit" in name or "rate_limit" in name or "rate_limit" in text:
        kind = "rate_limit"
    elif "timeout" in name or "timeout" in text:
        kind = "timeout"
    elif "connection" in name or "connection" in text:
        kind = "connection_error"
    elif "accessdenied" in code or "access_denied" in code:
        kind = "authentication_error"
    elif "serviceunavailable" in code or "service_unavailable" in code:
        kind = "service_unavailable"
    else:
        kind = "unknown_error"
    return build_error(
        "Bedrock API error", error, provider, kind, status_code, error_code=error_code
    )
