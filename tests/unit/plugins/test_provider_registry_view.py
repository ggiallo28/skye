"""``ProviderRegistry`` is a view of the default registrar: every call of today works as before, and a plugin's providers are found (plugins:5.2, Requirement 56.7)."""

from __future__ import annotations

from typing import Any

import pytest

import skye
from skye.base.exceptions import ConfigurationError
from skye.base.interfaces.model import ModelInterface
from skye.base.interfaces.registry import ProviderRegistryInterface, get_provider_registry
from skye.base.interfaces.vector_encoder import VectorEncoderInterface
from skye.base.plugins import get_registrar
from skye.base.profile import ModelProfile, ProviderProfile
from skye.models import OpenAIProvider
from skye.models.registry import ProviderRegistry
from tests.unit.plugins.registrar_state import restored_default_registrar


class FakeModel(ModelInterface):
    def __init__(self, **config: Any) -> None:
        self.config = config

    def complete(self, request: Any) -> Any: ...
    def stream(self, request: Any) -> Any: ...
    async def acomplete(self, request: Any) -> Any: ...
    async def astream(self, request: Any) -> Any: ...
    def get_capabilities(self) -> dict[str, Any]:
        return {}

    def get_model_info(self) -> dict[str, Any]:
        return {}


class FakeEncoder(VectorEncoderInterface):
    def __init__(self, **config: Any) -> None:
        self.config = config

    def encode(self, text: str) -> list[float]:
        return [0.0]

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] for _ in texts]

    async def aencode(self, text: str) -> list[float]:
        return [0.0]

    async def aencode_batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] for _ in texts]

    def get_vector_dimension(self) -> int:
        return 1


@pytest.fixture(autouse=True)
def default_registrar_put_back():
    with restored_default_registrar() as registrar:
        yield registrar


# -- no table of its own ------------------------------------------------------------------------------------------


def test_the_registry_keeps_no_table_of_its_own():
    assert not hasattr(ProviderRegistry, "_model_providers")
    assert not hasattr(ProviderRegistry, "_embedding_providers")


def test_the_registry_is_still_the_port_implementation():
    assert issubclass(ProviderRegistry, ProviderRegistryInterface)
    assert get_provider_registry() is ProviderRegistry


# -- one case per public call --------------------------------------------------------------------------------------


def test_register_model_provider_writes_the_default_registrar():
    ProviderRegistry.register_model_provider("fake", FakeModel)
    assert get_registrar().get("provider", "fake", "model") is FakeModel


def test_register_embedding_provider_writes_the_default_registrar():
    ProviderRegistry.register_embedding_provider("fake", FakeEncoder)
    assert get_registrar().get("provider", "fake", "embedding") is FakeEncoder


def test_registering_a_name_again_replaces_it_as_it_always_did():
    """The registry has no ``replace`` flag: a second registration overrides, a built-in name included."""
    ProviderRegistry.register_model_provider("fake", FakeModel)
    ProviderRegistry.register_model_provider("fake", FakeModel)
    ProviderRegistry.register_model_provider("openai", FakeModel)
    assert isinstance(ProviderRegistry.get_model_provider("openai"), FakeModel)


def test_get_model_provider_builds_with_the_config():
    ProviderRegistry.register_model_provider("fake", FakeModel)
    assert ProviderRegistry.get_model_provider("fake", api_key="k").config == {"api_key": "k"}


def test_get_embedding_provider_builds_with_the_config():
    ProviderRegistry.register_embedding_provider("fake", FakeEncoder)
    assert ProviderRegistry.get_embedding_provider("fake", model="m").config == {"model": "m"}


def test_a_failing_constructor_is_a_configuration_error_that_keeps_the_cause():
    class Broken(FakeModel):
        def __init__(self, **config: Any) -> None:
            raise RuntimeError("boom")

    ProviderRegistry.register_model_provider("broken", Broken)
    with pytest.raises(
        ConfigurationError, match="Failed to instantiate provider 'broken': boom"
    ) as caught:
        ProviderRegistry.get_model_provider("broken")
    assert isinstance(caught.value.__cause__, RuntimeError)


def test_the_built_ins_are_listed_and_a_plugin_provider_with_them():
    assert {"openai", "anthropic", "bedrock", "azure", "google"} <= set(
        ProviderRegistry.list_model_providers()
    )
    assert {"openai", "bedrock", "cohere", "google", "google-multimodal"} <= set(
        ProviderRegistry.list_embedding_providers()
    )
    ProviderRegistry.register_model_provider("fake", FakeModel)
    assert "fake" in ProviderRegistry.list_model_providers()


def test_a_removed_provider_is_no_longer_listed_or_found():
    ProviderRegistry.register_model_provider("fake", FakeModel)
    assert get_registrar().unregister("provider", "fake", "model") is True
    assert "fake" not in ProviderRegistry.list_model_providers()
    with pytest.raises(ConfigurationError):
        ProviderRegistry.get_model_provider("fake")


# -- the error messages the tests assert --------------------------------------------------------------------------


def test_an_unknown_model_provider_lists_the_registered_ones():
    with pytest.raises(
        ConfigurationError,
        match=r"Model provider 'nope' not found\. Available model providers: .*openai",
    ):
        ProviderRegistry.get_model_provider("nope")


def test_an_embedding_only_name_asked_as_a_model_hints_at_provider_type():
    with pytest.raises(
        ConfigurationError,
        match=r"'cohere' is an embedding provider: pass provider_type=\"embedding\"\.",
    ):
        ProviderRegistry.get_model_provider("cohere")


def test_an_unknown_embedding_provider_lists_the_registered_ones():
    with pytest.raises(
        ConfigurationError,
        match=r"Embedding provider 'nope' not found\. Available embedding providers: .*cohere",
    ):
        ProviderRegistry.get_embedding_provider("nope")


# -- skye.provider ------------------------------------------------------------------------------------------------


def test_provider_builds_a_built_in_model_client():
    assert isinstance(skye.provider("openai", api_key="k"), OpenAIProvider)


def test_provider_type_embedding_builds_the_embedding_client():
    assert (
        type(
            skye.provider(
                "openai", api_key="k", model="text-embedding-3-small", provider_type="embedding"
            )
        ).__name__
        == "OpenAIEmbeddingProvider"
    )


def test_a_name_registered_only_for_embeddings_gives_its_embedding_client():
    assert (
        type(skye.provider("cohere", api_key="k", model="embed-english-v3.0")).__name__
        == "CohereEmbeddingProvider"
    )


def test_region_is_an_alias_of_the_parameter_the_class_takes():
    class Aws(FakeModel):
        def __init__(self, region_name: str | None = None, **config: Any) -> None:
            super().__init__(region_name=region_name, **config)

    class Gcp(FakeModel):
        def __init__(self, location: str | None = None, **config: Any) -> None:
            super().__init__(location=location, **config)

    ProviderRegistry.register_model_provider("aws-like", Aws)
    ProviderRegistry.register_model_provider("gcp-like", Gcp)
    assert skye.provider("aws-like", region="eu-west-1").config["region_name"] == "eu-west-1"
    assert skye.provider("gcp-like", region="europe-west1").config["location"] == "europe-west1"


def test_a_third_party_provider_on_the_registrar_is_returned_by_skye_provider():
    get_registrar().provider(
        "acme", FakeModel, profile=ProviderProfile("acme", ("ACME_API_KEY",)), function="model"
    )
    get_registrar().provider(
        "acme", FakeEncoder, profile=ProviderProfile("acme", ("ACME_API_KEY",)), function="embedding"
    )
    assert isinstance(skye.provider("acme", api_key="k"), FakeModel)
    assert isinstance(skye.provider("acme", model="m", provider_type="embedding"), FakeEncoder)
    assert get_registrar().get_profile("acme").api_key_variables == ("ACME_API_KEY",)


def test_a_provider_registered_by_text_is_imported_when_it_is_first_used():
    get_registrar().provider("lazy-fake", f"{__name__}:FakeModel", function="model")
    assert isinstance(skye.provider("lazy-fake"), FakeModel)


def test_a_text_that_does_not_import_is_a_configuration_error_naming_the_provider():
    get_registrar().provider("ghost", "no_such_module_for_providers:Thing", function="model")
    with pytest.raises(ConfigurationError, match="ghost"):
        skye.provider("ghost")


def test_a_registrar_profile_of_a_provider_with_models_is_kept_next_to_the_class():
    profile = ProviderProfile(
        "acme2", models={"acme-1": ModelProfile(prompt_price=1.0, completion_price=2.0)}
    )
    get_registrar().provider("acme2", FakeModel, profile=profile, function="model")
    assert skye.provider("acme2") is not None
    assert get_registrar().get_profile("acme2") is profile
