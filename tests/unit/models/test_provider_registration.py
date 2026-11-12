"""Tests for automatic provider registration on import."""



class TestProviderAutoRegistration:
    """Test suite for automatic provider registration."""

    def test_providers_auto_registered_on_import(self):
        """Test that providers are auto-registered when skye.models is imported."""
        # Import the providers module to trigger auto-registration
        from skye.models import ProviderRegistry

        # Verify model providers are registered
        model_providers = ProviderRegistry.list_model_providers()
        assert "openai" in model_providers
        assert "anthropic" in model_providers
        assert "bedrock" in model_providers
        assert "azure" in model_providers
        assert "google" in model_providers

    def test_embedding_providers_auto_registered_on_import(self):
        """Test that embedding providers are auto-registered when skye.models is imported."""
        from skye.models import ProviderRegistry

        # Verify embedding providers are registered
        embedding_providers = ProviderRegistry.list_embedding_providers()
        assert "openai" in embedding_providers
        assert "bedrock" in embedding_providers
        assert "cohere" in embedding_providers
        assert "google" in embedding_providers
        assert "google-multimodal" in embedding_providers

    def test_openai_provider_registered(self):
        """Test that OpenAI provider is properly registered."""
        from skye.models import ProviderRegistry

        # Verify OpenAI provider can be retrieved
        assert "openai" in ProviderRegistry.list_model_providers()

    def test_anthropic_provider_registered(self):
        """Test that Anthropic provider is properly registered."""
        from skye.models import ProviderRegistry

        # Verify Anthropic provider can be retrieved
        assert "anthropic" in ProviderRegistry.list_model_providers()

    def test_bedrock_provider_registered(self):
        """Test that Bedrock provider is properly registered."""
        from skye.models import ProviderRegistry

        # Verify Bedrock provider can be retrieved
        assert "bedrock" in ProviderRegistry.list_model_providers()

    def test_azure_provider_registered(self):
        """Test that Azure OpenAI provider is properly registered."""
        from skye.models import ProviderRegistry

        # Verify Azure provider can be retrieved
        assert "azure" in ProviderRegistry.list_model_providers()

    def test_google_provider_registered(self):
        """Test that Google provider is properly registered."""
        from skye.models import ProviderRegistry

        # Verify Google provider can be retrieved
        assert "google" in ProviderRegistry.list_model_providers()

    def test_openai_embedding_provider_registered(self):
        """Test that OpenAI embedding provider is properly registered."""
        from skye.models import ProviderRegistry

        # Verify OpenAI embedding provider can be retrieved
        assert "openai" in ProviderRegistry.list_embedding_providers()

    def test_bedrock_embedding_provider_registered(self):
        """Test that Bedrock embedding provider is properly registered."""
        from skye.models import ProviderRegistry

        # Verify Bedrock embedding provider can be retrieved
        assert "bedrock" in ProviderRegistry.list_embedding_providers()

    def test_cohere_embedding_provider_registered(self):
        """Test that Cohere embedding provider is properly registered."""
        from skye.models import ProviderRegistry

        # Verify Cohere embedding provider can be retrieved
        assert "cohere" in ProviderRegistry.list_embedding_providers()

    def test_google_embedding_provider_registered(self):
        """Test that Google embedding provider is properly registered."""
        from skye.models import ProviderRegistry

        # Verify Google embedding provider can be retrieved
        assert "google" in ProviderRegistry.list_embedding_providers()

    def test_google_multimodal_embedding_provider_registered(self):
        """Test that Google multimodal embedding provider is properly registered."""
        from skye.models import ProviderRegistry

        # Verify Google multimodal embedding provider can be retrieved
        assert "google-multimodal" in ProviderRegistry.list_embedding_providers()

    def test_all_model_providers_count(self):
        """Test that all expected model providers are registered."""
        from skye.models import ProviderRegistry

        model_providers = ProviderRegistry.list_model_providers()
        # Should have 5 model providers: openai, anthropic, bedrock, azure, google
        assert len(model_providers) == 5

    def test_all_embedding_providers_count(self):
        """Test that all expected embedding providers are registered."""
        from skye.models import ProviderRegistry

        embedding_providers = ProviderRegistry.list_embedding_providers()
        # Should have 5 embedding providers: openai, bedrock, cohere, google, google-multimodal
        assert len(embedding_providers) == 5

    def test_provider_classes_are_registered(self):
        """Test that provider classes are properly registered."""
        from skye.models import (
            AnthropicProvider,
            AzureOpenAIProvider,
            BedrockProvider,
            GoogleProvider,
            OpenAIProvider,
        )
        from skye.base.plugins import get_registrar

        # Verify that the registered classes match the expected classes
        assert get_registrar().get("provider", "openai", "model") == OpenAIProvider
        assert get_registrar().get("provider", "anthropic", "model") == AnthropicProvider
        assert get_registrar().get("provider", "bedrock", "model") == BedrockProvider
        assert get_registrar().get("provider", "azure", "model") == AzureOpenAIProvider
        assert get_registrar().get("provider", "google", "model") == GoogleProvider

    def test_embedding_provider_classes_are_registered(self):
        """Test that embedding provider classes are properly registered."""
        from skye.models import (
            BedrockEmbeddingProvider,
            CohereEmbeddingProvider,
            GoogleEmbeddingProvider,
            GoogleMultimodalEmbeddingProvider,
            OpenAIEmbeddingProvider,
        )
        from skye.base.plugins import get_registrar

        # Verify that the registered classes match the expected classes
        assert get_registrar().get("provider", "openai", "embedding") == OpenAIEmbeddingProvider
        assert get_registrar().get("provider", "bedrock", "embedding") == BedrockEmbeddingProvider
        assert get_registrar().get("provider", "cohere", "embedding") == CohereEmbeddingProvider
        assert get_registrar().get("provider", "google", "embedding") == GoogleEmbeddingProvider
        assert (
            get_registrar().get("provider", "google-multimodal", "embedding")
            == GoogleMultimodalEmbeddingProvider
        )

    def test_registry_lists_all_providers(self):
        """Test that registry lists all registered providers."""
        from skye.models import ProviderRegistry

        model_providers = ProviderRegistry.list_model_providers()
        embedding_providers = ProviderRegistry.list_embedding_providers()

        # Verify both lists are non-empty
        assert len(model_providers) > 0
        assert len(embedding_providers) > 0

        # Verify they contain expected providers
        expected_models = {"openai", "anthropic", "bedrock", "azure", "google"}
        expected_embeddings = {"openai", "bedrock", "cohere", "google", "google-multimodal"}

        assert set(model_providers) == expected_models
        assert set(embedding_providers) == expected_embeddings
