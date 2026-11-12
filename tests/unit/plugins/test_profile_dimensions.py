"""The vector dimensions and the default endpoints of the embedding providers are profile data, not constants in the adapters (D110)."""

from __future__ import annotations

import pytest

from skye.base.plugins import Registrar, get_registrar
from skye.base.profile import ModelProfile, ProviderProfile
from skye.models.base import BaseEmbeddingProvider
from skye.models.plugins.bedrock import BedrockEmbeddingProvider
from skye.models.plugins.cohere import CohereEmbeddingProvider
from skye.models.plugins.google import GoogleEmbeddingProvider, GoogleMultimodalEmbeddingProvider
from skye.models.plugins.openai import OpenAIEmbeddingProvider

# The values the adapters held as constants before this change: a frozen copy, so that the move cannot drift.
OLD_DIMENSIONS = {
    OpenAIEmbeddingProvider: {
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
        "text-embedding-ada-002": 1536,
    },
    BedrockEmbeddingProvider: {
        "amazon.titan-embed-text-v1": 1536,
        "amazon.titan-embed-text-v2:0": 1024,
    },
    CohereEmbeddingProvider: {
        "embed-english-v3.0": 1024,
        "embed-english-light-v3.0": 384,
        "embed-multilingual-v3.0": 1024,
    },
    GoogleEmbeddingProvider: {"text-embedding-004": 768, "text-multilingual-embedding-002": 768},
}


def _make(cls, model):
    """An instance without calling the constructor: the dimension needs no key, no region and no network."""
    instance = cls.__new__(cls)
    instance.model = model
    return instance


@pytest.mark.parametrize(
    "cls,model,dimension",
    [(c, m, d) for c, table in OLD_DIMENSIONS.items() for m, d in table.items()],
)
def test_each_dimension_equals_the_old_constant(cls, model, dimension):
    assert _make(cls, model).get_vector_dimension() == dimension


def test_the_multimodal_dimension_is_1408():
    assert (
        _make(GoogleMultimodalEmbeddingProvider, "multimodalembedding@001").get_vector_dimension()
        == 1408
    )


@pytest.mark.parametrize("cls", list(OLD_DIMENSIONS))
def test_an_unknown_model_is_a_value_error_as_before(cls):
    with pytest.raises(ValueError, match="Unknown model"):
        _make(cls, "no-such-embedding-model").get_vector_dimension()


def test_the_adapters_hold_no_dimension_table_any_more():
    for cls in (*OLD_DIMENSIONS, GoogleMultimodalEmbeddingProvider):
        assert not hasattr(cls, "MODEL_DIMENSIONS") and not hasattr(cls, "VECTOR_DIMENSION"), (
            cls.__name__
        )


def test_a_plugin_profile_gives_its_own_embedding_model_a_dimension():
    """A third-party embedding provider declares its dimension in its profile, with no table in its class."""
    registrar = Registrar()
    registrar.provider(
        "acme-embed",
        "skye.models.plugins.openai:OpenAIEmbeddingProvider",
        profile=ProviderProfile(
            "acme-embed", models={"acme-1": ModelProfile(info={"vector_dimension": 64})}
        ), function="embedding",
    )

    class Acme(BaseEmbeddingProvider):
        def _initialize_client(self):
            return None

        def _encode_batch_impl(self, texts):
            return [[0.0] * 64 for _ in texts]

        async def _aencode_batch_impl(self, texts):
            return self._encode_batch_impl(texts)

        def get_vector_dimension(self) -> int:
            return self._profile_dimension("acme-embed")

    import skye.base.plugins as plugins_module

    original = plugins_module._default
    plugins_module._default = registrar
    try:
        assert _make(Acme, "acme-1").get_vector_dimension() == 64
        assert (
            _make(Acme, "acme-1-2026-01-01").get_vector_dimension() == 64
        )  # a dated name finds its family (Requirement 59.4)
    finally:
        plugins_module._default = original


def test_the_default_endpoints_come_from_the_profiles():
    assert BaseEmbeddingProvider._profile_api_base("openai") == "https://api.openai.com/v1"
    assert BaseEmbeddingProvider._profile_api_base("cohere") == "https://api.cohere.com"
    assert get_registrar().get_profile("openai").default_api_base == "https://api.openai.com/v1"


def test_a_provider_without_an_endpoint_in_its_profile_says_so():
    from skye.base.exceptions import ConfigurationError

    with pytest.raises(ConfigurationError, match="default endpoint"):
        BaseEmbeddingProvider._profile_api_base(
            "bedrock"
        )  # a region-based provider has no base URL
