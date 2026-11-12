"""Unit tests for provider-specific error handling.

Tests cover:
- OpenAI error wrapping
- Anthropic error wrapping
- Bedrock error wrapping
- Azure error wrapping
- Google error wrapping
- Error context preservation
- Error classification
"""

from unittest.mock import MagicMock

from skye.base.exceptions import ProviderError
from skye.models.utilities.error_mapping import ErrorHandler


class TestOpenAIErrorHandling:
    """Test OpenAI error handling."""

    def test_handle_rate_limit_error(self) -> None:
        """Test handling of rate limit error."""
        error = MagicMock()
        error.__class__.__name__ = "RateLimitError"
        error.retry_after = 60
        error.status_code = 429
        error.__str__ = lambda self: "Rate limit exceeded"

        result = ErrorHandler.handle_openai_error(error)

        assert isinstance(result, ProviderError)
        assert result.details["provider"] == "openai"
        assert result.details["error_type"] == "rate_limit"
        assert result.details["retry_after"] == 60
        assert result.details["status_code"] == 429

    def test_handle_api_error(self) -> None:
        """Test handling of generic API error."""
        error = MagicMock()
        error.__class__.__name__ = "APIError"
        error.status_code = 500
        error.__str__ = lambda self: "Internal server error"

        result = ErrorHandler.handle_openai_error(error)

        assert isinstance(result, ProviderError)
        assert result.details["provider"] == "openai"
        assert result.details["error_type"] == "api_error"
        assert result.details["status_code"] == 500

    def test_handle_authentication_error(self) -> None:
        """Test handling of authentication error."""
        error = MagicMock()
        error.__class__.__name__ = "AuthenticationError"
        error.status_code = 401
        error.__str__ = lambda self: "Invalid API key"

        result = ErrorHandler.handle_openai_error(error)

        assert isinstance(result, ProviderError)
        assert result.details["provider"] == "openai"
        assert result.details["error_type"] == "authentication_error"

    def test_handle_timeout_error(self) -> None:
        """Test handling of timeout error."""
        error = MagicMock()
        error.__class__.__name__ = "Timeout"
        error.__str__ = lambda self: "Request timeout"

        result = ErrorHandler.handle_openai_error(error)

        assert isinstance(result, ProviderError)
        assert result.details["provider"] == "openai"
        assert result.details["error_type"] == "timeout"


class TestAnthropicErrorHandling:
    """Test Anthropic error handling."""

    def test_handle_rate_limit_error(self) -> None:
        """Test handling of rate limit error."""
        error = MagicMock()
        error.__class__.__name__ = "RateLimitError"
        error.status_code = 429
        error.__str__ = lambda self: "Rate limit exceeded"

        result = ErrorHandler.handle_anthropic_error(error)

        assert isinstance(result, ProviderError)
        assert result.details["provider"] == "anthropic"
        assert result.details["error_type"] == "rate_limit"
        assert result.details["status_code"] == 429

    def test_handle_api_error(self) -> None:
        """Test handling of generic API error."""
        error = MagicMock()
        error.__class__.__name__ = "APIError"
        error.status_code = 500
        error.__str__ = lambda self: "Internal server error"

        result = ErrorHandler.handle_anthropic_error(error)

        assert isinstance(result, ProviderError)
        assert result.details["provider"] == "anthropic"
        assert result.details["error_type"] == "api_error"

    def test_handle_connection_error(self) -> None:
        """Test handling of connection error."""
        error = MagicMock()
        error.__class__.__name__ = "ConnectionError"
        error.__str__ = lambda self: "Connection refused"

        result = ErrorHandler.handle_anthropic_error(error)

        assert isinstance(result, ProviderError)
        assert result.details["provider"] == "anthropic"
        assert result.details["error_type"] == "connection_error"


class TestBedrockErrorHandling:
    """Test Bedrock error handling."""

    def test_handle_throttling_error(self) -> None:
        """Test handling of throttling error."""
        error = MagicMock()
        error.__class__.__name__ = "ClientError"
        error.response = {
            "Error": {"Code": "ThrottlingException"},
            "ResponseMetadata": {"HTTPStatusCode": 429},
        }
        error.__str__ = lambda self: "Throttling error"

        result = ErrorHandler.handle_bedrock_error(error)

        assert isinstance(result, ProviderError)
        assert result.details["provider"] == "bedrock"
        assert result.details["error_type"] == "rate_limit"
        assert result.details["status_code"] == 429

    def test_handle_access_denied_error(self) -> None:
        """Test handling of access denied error."""
        error = MagicMock()
        error.__class__.__name__ = "ClientError"
        error.response = {
            "Error": {"Code": "AccessDeniedException"},
            "ResponseMetadata": {"HTTPStatusCode": 403},
        }
        error.__str__ = lambda self: "Access denied"

        result = ErrorHandler.handle_bedrock_error(error)

        assert isinstance(result, ProviderError)
        assert result.details["provider"] == "bedrock"
        assert result.details["error_type"] == "authentication_error"

    def test_handle_service_unavailable_error(self) -> None:
        """Test handling of service unavailable error."""
        error = MagicMock()
        error.__class__.__name__ = "ClientError"
        error.response = {
            "Error": {"Code": "ServiceUnavailableException"},
            "ResponseMetadata": {"HTTPStatusCode": 503},
        }
        error.__str__ = lambda self: "Service unavailable"

        result = ErrorHandler.handle_bedrock_error(error)

        assert isinstance(result, ProviderError)
        assert result.details["provider"] == "bedrock"
        assert result.details["error_type"] == "service_unavailable"

    def test_handle_error_without_response(self) -> None:
        """Test handling of error without response metadata."""
        error = MagicMock()
        error.__class__.__name__ = "ClientError"
        error.response = None
        error.__str__ = lambda self: "Generic error"

        result = ErrorHandler.handle_bedrock_error(error)

        assert isinstance(result, ProviderError)
        assert result.details["provider"] == "bedrock"
        assert result.details["error_type"] == "unknown_error"


class TestAzureErrorHandling:
    """Test Azure OpenAI error handling."""

    def test_handle_rate_limit_error(self) -> None:
        """Test handling of rate limit error."""
        error = MagicMock()
        error.__class__.__name__ = "RateLimitError"
        error.status_code = 429
        error.__str__ = lambda self: "Rate limit exceeded"

        result = ErrorHandler.handle_azure_error(error)

        assert isinstance(result, ProviderError)
        assert result.details["provider"] == "azure"
        assert result.details["error_type"] == "rate_limit"

    def test_handle_authentication_error(self) -> None:
        """Test handling of authentication error."""
        error = MagicMock()
        error.__class__.__name__ = "AuthenticationError"
        error.status_code = 401
        error.__str__ = lambda self: "Invalid credentials"

        result = ErrorHandler.handle_azure_error(error)

        assert isinstance(result, ProviderError)
        assert result.details["provider"] == "azure"
        assert result.details["error_type"] == "authentication_error"


class TestGoogleErrorHandling:
    """Test Google error handling."""

    def test_handle_rate_limit_error(self) -> None:
        """Test handling of rate limit error."""
        error = MagicMock()
        error.__class__.__name__ = "ResourceExhausted"
        error.code = 8
        error.__str__ = lambda self: "Rate limit exceeded"

        result = ErrorHandler.handle_google_error(error)

        assert isinstance(result, ProviderError)
        assert result.details["provider"] == "google"
        assert result.details["error_type"] == "rate_limit"

    def test_handle_deadline_exceeded_error(self) -> None:
        """Test handling of deadline exceeded error."""
        error = MagicMock()
        error.__class__.__name__ = "DeadlineExceeded"
        error.code = 4
        error.__str__ = lambda self: "Deadline exceeded"

        result = ErrorHandler.handle_google_error(error)

        assert isinstance(result, ProviderError)
        assert result.details["provider"] == "google"
        assert result.details["error_type"] == "timeout"

    def test_handle_unavailable_error(self) -> None:
        """Test handling of unavailable error."""
        error = MagicMock()
        error.__class__.__name__ = "Unavailable"
        error.code = 14
        error.__str__ = lambda self: "Service unavailable"

        result = ErrorHandler.handle_google_error(error)

        assert isinstance(result, ProviderError)
        assert result.details["provider"] == "google"
        assert result.details["error_type"] == "service_unavailable"

    def test_handle_permission_denied_error(self) -> None:
        """Test handling of permission denied error."""
        error = MagicMock()
        error.__class__.__name__ = "PermissionDenied"
        error.code = 7
        error.__str__ = lambda self: "Permission denied"

        result = ErrorHandler.handle_google_error(error)

        assert isinstance(result, ProviderError)
        assert result.details["provider"] == "google"
        assert result.details["error_type"] == "permission_error"


class TestWrapProviderError:
    """Test generic provider error wrapping."""

    def test_wrap_already_provider_error(self) -> None:
        """Test that ProviderError is returned as-is."""
        original_error = ProviderError("test error", provider="openai")

        result = ErrorHandler.wrap_provider_error(original_error, "openai")

        assert result is original_error

    def test_wrap_openai_error(self) -> None:
        """Test wrapping OpenAI error."""
        error = MagicMock()
        error.__class__.__name__ = "APIError"
        error.status_code = 500
        error.__str__ = lambda self: "Server error"

        result = ErrorHandler.wrap_provider_error(error, "openai")

        assert isinstance(result, ProviderError)
        assert result.details["provider"] == "openai"

    def test_wrap_anthropic_error(self) -> None:
        """Test wrapping Anthropic error."""
        error = MagicMock()
        error.__class__.__name__ = "APIError"
        error.status_code = 500
        error.__str__ = lambda self: "Server error"

        result = ErrorHandler.wrap_provider_error(error, "anthropic")

        assert isinstance(result, ProviderError)
        assert result.details["provider"] == "anthropic"

    def test_wrap_bedrock_error(self) -> None:
        """Test wrapping Bedrock error."""
        error = MagicMock()
        error.__class__.__name__ = "ClientError"
        error.response = None
        error.__str__ = lambda self: "Error"

        result = ErrorHandler.wrap_provider_error(error, "bedrock")

        assert isinstance(result, ProviderError)
        assert result.details["provider"] == "bedrock"

    def test_wrap_azure_error(self) -> None:
        """Test wrapping Azure error."""
        error = MagicMock()
        error.__class__.__name__ = "APIError"
        error.status_code = 500
        error.__str__ = lambda self: "Server error"

        result = ErrorHandler.wrap_provider_error(error, "azure")

        assert isinstance(result, ProviderError)
        assert result.details["provider"] == "azure"

    def test_wrap_google_error(self) -> None:
        """Test wrapping Google error."""
        error = MagicMock()
        error.__class__.__name__ = "GoogleAPIError"
        error.code = 14
        error.__str__ = lambda self: "Unavailable"

        result = ErrorHandler.wrap_provider_error(error, "google")

        assert isinstance(result, ProviderError)
        assert result.details["provider"] == "google"

    def test_wrap_unknown_provider_error(self) -> None:
        """Test wrapping error from unknown provider."""
        error = MagicMock()
        error.__class__.__name__ = "SomeError"
        error.__str__ = lambda self: "Some error"

        result = ErrorHandler.wrap_provider_error(error, "unknown_provider")

        assert isinstance(result, ProviderError)
        assert result.details["provider"] == "unknown_provider"
        assert result.details["error_type"] == "unknown_error"


class TestErrorContextPreservation:
    """Test that error context is preserved."""

    def test_error_message_preserved(self) -> None:
        """Test that original error message is preserved."""
        error = MagicMock()
        error.__class__.__name__ = "APIError"
        error.status_code = 500
        error.__str__ = lambda self: "Original error message"

        result = ErrorHandler.handle_openai_error(error)

        assert "Original error message" in result.message

    def test_error_type_preserved(self) -> None:
        """Test that original error type is preserved."""
        error = MagicMock()
        error.__class__.__name__ = "CustomError"
        error.__str__ = lambda self: "Error"

        result = ErrorHandler.handle_openai_error(error)

        assert result.details["original_error_type"] == "CustomError"

    def test_status_code_preserved(self) -> None:
        """Test that status code is preserved."""
        error = MagicMock()
        error.__class__.__name__ = "APIError"
        error.status_code = 503
        error.__str__ = lambda self: "Service unavailable"

        result = ErrorHandler.handle_openai_error(error)

        assert result.details["status_code"] == 503

    def test_retry_after_preserved(self) -> None:
        """Test that retry_after is preserved."""
        error = MagicMock()
        error.__class__.__name__ = "RateLimitError"
        error.retry_after = 120
        error.status_code = 429
        error.__str__ = lambda self: "Rate limit"

        result = ErrorHandler.handle_openai_error(error)

        assert result.details["retry_after"] == 120
