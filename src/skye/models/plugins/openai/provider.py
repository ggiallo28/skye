"""OpenAI itself: the OpenAI endpoint, its organization header and its response fingerprint.

The wire format is shared with every compatible endpoint (the package ``openai_compatible``); this
module holds only what is specific to OpenAI.

Example:
    >>> from skye.models.plugins.openai.provider import OpenAIProvider
    >>> provider = OpenAIProvider(api_key="sk-...")  # or set OPENAI_API_KEY and pass nothing
    >>> response = provider.complete(request)  # doctest: +SKIP
"""

from typing import Any

from skye.models.utilities.openai_compatible import OpenAICompatibleProvider


class OpenAIProvider(OpenAICompatibleProvider):
    """OpenAI: default endpoint, ``OpenAI-Organization`` header and ``system_fingerprint``.

    Args:
        api_key: OpenAI API key; the variable of the profile of ``openai`` when omitted
        api_base: Optional custom API base URL
        organization: Optional organization ID
        **kwargs: Additional configuration parameters
    """

    provider_name = "openai"
    metadata_prefix = "openai_"
    reports_fingerprint = True
    streams_usage = True
    default_api_base = "https://api.openai.com/v1"

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        organization: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(api_key=api_key, api_base=api_base, organization=organization, **kwargs)
        self.organization = organization

    def _auth_headers(self) -> dict[str, str]:
        headers = super()._auth_headers()
        if self.organization:
            headers["OpenAI-Organization"] = self.organization
        return headers


__all__ = ["OpenAIProvider"]
