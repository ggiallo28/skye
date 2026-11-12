"""The OpenAI wire format, for any endpoint that speaks it (D110): the shared base of the ``openai`` and ``azure`` providers and of any plugin.

``OpenAICompatibleProvider`` serves every OpenAI wire-compatible endpoint (vLLM, Ollama, LM Studio, Together, ...), keyed by ``api_base`` and
``api_key``. The code is separated by responsibility, with the same file names as every provider folder: ``provider.py`` (the class),
``request.py`` (building the request), ``response.py`` (reading a response and a stream chunk) and ``capabilities.py`` (capabilities out and back).

Example:
    >>> from skye.models.utilities.openai_compatible import OpenAICompatibleProvider
    >>> provider = OpenAICompatibleProvider(api_key="sk-...", api_base="http://localhost:8000/v1")
"""

from skye.models.utilities.openai_compatible.provider import OpenAICompatibleProvider

__all__ = ["OpenAICompatibleProvider"]
