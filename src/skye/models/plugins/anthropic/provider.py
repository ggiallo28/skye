"""Anthropic itself: the Anthropic endpoint and its provider label.

The wire format is shared with every compatible endpoint (the package ``anthropic_compatible``);
this
module holds only what is specific to Anthropic.

Example:
    >>> from skye.models.plugins.anthropic.provider import AnthropicProvider
    >>> provider = AnthropicProvider(api_key="sk-ant-...")  # or set ANTHROPIC_API_KEY
    >>> response = provider.complete(request)  # doctest: +SKIP
"""

from skye.models.utilities.anthropic_compatible import AnthropicCompatibleProvider


class AnthropicProvider(AnthropicCompatibleProvider):
    """Anthropic: default endpoint ``api.anthropic.com`` and the label ``anthropic``.

    Args:
        api_key: Anthropic API key; the variable of the profile of ``anthropic`` when omitted
        api_base: Optional custom API base URL
        timeout: Seconds before a call fails (default 60)
    """

    provider_name = "anthropic"
    default_api_base = "https://api.anthropic.com"


__all__ = ["AnthropicProvider"]
