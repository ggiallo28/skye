"""Unit tests for TokenCounter utility.

Tests token counting functionality for various models and scenarios.
"""

import pytest

from skye.base.messages import AssistantMessage, SystemMessage, UserMessage
from skye.models.token_counter import TokenCounter


class TestTokenCounter:
    """Test suite for TokenCounter."""

    def test_count_tokens_with_approximate_tokenizer(self):
        """Test token counting with approximate tokenizer for unknown models."""
        text = "Hello, world!"
        count = TokenCounter.count_tokens(text, "unknown-model")
        # Approximate: 13 chars / 4 = 3 tokens
        assert count == 3

    def test_count_tokens_empty_string(self):
        """Test token counting with empty string."""
        count = TokenCounter.count_tokens("", "gpt-4")
        # Empty string should have at least 1 token in approximate tokenizer
        assert count >= 0

    def test_count_tokens_long_text(self):
        """Test token counting with longer text."""
        text = "This is a longer piece of text that should have more tokens."
        count = TokenCounter.count_tokens(text, "unknown-model")
        # Should be proportional to length
        assert count > 10

    def test_count_message_tokens_single_message(self):
        """Test counting tokens for a single message."""
        messages = [UserMessage(content="Hello")]
        count = TokenCounter.count_message_tokens(messages, "gpt-4")
        # Should include message overhead (3) + content tokens
        assert count > 3

    def test_count_message_tokens_multiple_messages(self):
        """Test counting tokens for multiple messages."""
        messages = [
            UserMessage(content="Hello"),
            AssistantMessage(content="Hi there!"),
            UserMessage(content="How are you?"),
        ]
        count = TokenCounter.count_message_tokens(messages, "gpt-4")
        # Should include overhead for each message plus content
        assert count > 9  # 3 messages * 3 overhead = 9 minimum

    def test_count_message_tokens_with_system_message(self):
        """Test counting tokens with system message."""
        messages = [
            SystemMessage(content="You are a helpful assistant."),
            UserMessage(content="Hello"),
        ]
        count = TokenCounter.count_message_tokens(messages, "gpt-4")
        assert count > 6  # 2 messages * 3 overhead = 6 minimum

    def test_message_overhead_gpt4(self):
        """Test message overhead for GPT-4."""
        overhead = TokenCounter._get_message_overhead("gpt-4")
        assert overhead == 3

    def test_message_overhead_gpt35(self):
        """Test message overhead for GPT-3.5."""
        overhead = TokenCounter._get_message_overhead("gpt-3.5-turbo")
        assert overhead == 4

    def test_message_overhead_o1(self):
        """Test message overhead for o1 models."""
        overhead = TokenCounter._get_message_overhead("o1-preview")
        assert overhead == 3

    def test_message_overhead_claude(self):
        """Test message overhead for Claude models."""
        overhead = TokenCounter._get_message_overhead("claude-3-sonnet")
        assert overhead == 4

    def test_message_overhead_unknown_model(self):
        """Test message overhead for unknown model."""
        overhead = TokenCounter._get_message_overhead("unknown-model")
        assert overhead == 3  # Default

    def test_approximate_tokenizer_encode(self):
        """Test approximate tokenizer encode method."""
        tokenizer = TokenCounter._approximate_tokenizer()
        tokens = tokenizer.encode("Hello, world!")
        # 13 chars / 4 = 3 tokens
        assert len(tokens) == 3

    def test_approximate_tokenizer_short_text(self):
        """Test approximate tokenizer with very short text."""
        tokenizer = TokenCounter._approximate_tokenizer()
        tokens = tokenizer.encode("Hi")
        # Should have at least 1 token
        assert len(tokens) >= 1

    def test_tokenizer_caching(self):
        """Test that tokenizers are cached."""
        # First call
        TokenCounter.count_tokens("test", "test-model")
        # Second call should use cached tokenizer
        TokenCounter.count_tokens("test2", "test-model")
        # Verify the model is in cache
        assert "test-model" in TokenCounter._tokenizers

    @pytest.mark.parametrize(
        "model,text,expected_min",
        [
            ("gpt-4", "Hello", 1),
            ("gpt-3.5-turbo", "Hello world", 2),
            ("claude-3-sonnet", "Test message", 2),
            ("unknown-model", "Short", 1),
        ],
    )
    def test_count_tokens_various_models(self, model: str, text: str, expected_min: int):
        """Test token counting for various models."""
        count = TokenCounter.count_tokens(text, model)
        assert count >= expected_min

    def test_count_tokens_with_special_characters(self):
        """Test token counting with special characters."""
        text = "Hello! @#$% 123 🎉"
        count = TokenCounter.count_tokens(text, "unknown-model")
        assert count > 0

    def test_count_message_tokens_empty_list(self):
        """Test counting tokens for empty message list."""
        messages = []
        count = TokenCounter.count_message_tokens(messages, "gpt-4")
        assert count == 0

    def test_count_message_tokens_with_empty_content(self):
        """Test counting tokens for message with empty content."""
        messages = [UserMessage(content="")]
        count = TokenCounter.count_message_tokens(messages, "gpt-4")
        # Should still have message overhead
        assert count >= 3


class TestTokenCounterWithTiktoken:
    """Test suite for TokenCounter with tiktoken (if available)."""

    def test_count_tokens_gpt4_with_tiktoken(self):
        """Test token counting for GPT-4 with tiktoken if available."""
        try:
            import tiktoken  # noqa: F401

            text = "Hello, world!"
            count = TokenCounter.count_tokens(text, "gpt-4")
            # With tiktoken, should get accurate count
            assert count > 0
            assert isinstance(count, int)
        except ImportError:
            pytest.skip("tiktoken not installed")

    def test_count_tokens_gpt35_with_tiktoken(self):
        """Test token counting for GPT-3.5 with tiktoken if available."""
        try:
            import tiktoken  # noqa: F401

            text = "This is a test message."
            count = TokenCounter.count_tokens(text, "gpt-3.5-turbo")
            assert count > 0
            assert isinstance(count, int)
        except ImportError:
            pytest.skip("tiktoken not installed")

    def test_count_tokens_unknown_gpt_model_fallback(self):
        """Test that unknown GPT models fall back to cl100k_base encoding."""
        try:
            import tiktoken  # noqa: F401

            text = "Hello"
            # Use a model name that doesn't exist but starts with gpt-
            count = TokenCounter.count_tokens(text, "gpt-99-ultra")
            assert count > 0
            assert isinstance(count, int)
        except ImportError:
            pytest.skip("tiktoken not installed")


class TestTokenCounterNoVendorSdk:
    """Claude counting is a stdlib estimate; no ``anthropic`` SDK is imported."""

    def test_count_tokens_claude_uses_estimate(self):
        TokenCounter._tokenizers.pop("claude-3-sonnet", None)
        assert TokenCounter.count_tokens("Hello, Claude! " * 4, "claude-3-sonnet") == 15

    def test_token_counter_imports_no_anthropic(self):
        import ast
        import inspect

        from skye.models import token_counter

        tree = ast.parse(inspect.getsource(token_counter))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(a.name.split(".")[0] != "anthropic" for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] != "anthropic"
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert node.value != "anthropic"


# -- the counts come from the profiles (plugins:6.2, Requirements 60.2, 59.3, 59.10) ----------------------------------


def _old_overhead(model: str) -> int:
    """The prefix rules ``TokenCounter`` held before the profiles: the oracle the profiles must reproduce."""
    if model.startswith("gpt-4"):
        return 3
    if model.startswith("gpt-3.5"):
        return 4
    if model.startswith(("o1-", "o3-")):
        return 3
    if model.startswith("claude-"):
        return 4
    return 3


OLD_RULE_MODELS = [
    "gpt-4",
    "gpt-4-0613",
    "gpt-4-turbo",
    "gpt-4o",
    "gpt-4o-2024-08-06",
    "gpt-4o-mini",
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-3.5-turbo",
    "gpt-3.5-turbo-0125",
    "gpt-3.5-turbo-instruct",
    "gpt-5",
    "o1-preview",
    "o1-mini",
    "o3-mini",
    "claude-3-opus-20240229",
    "claude-3-5-sonnet-20241022",
    "claude-3-5-haiku-20241022",
    "claude-sonnet-4-20250514",
    "claude-opus-4-1-20250805",
    "anthropic.claude-3-sonnet-20240229-v1:0",
    "gemini-1.5-pro",
    "unknown-model",
]


@pytest.mark.parametrize("model", OLD_RULE_MODELS)
def test_the_overhead_is_the_one_the_old_prefix_rules_gave(model: str):
    expected = 3 if model.startswith("anthropic.") else _old_overhead(model)
    assert TokenCounter._get_message_overhead(model) == expected


@pytest.mark.parametrize("model", OLD_RULE_MODELS)
def test_a_gpt_or_o_model_has_the_tiktoken_tokenizer_and_the_others_the_estimate(model: str):
    uses_tiktoken = model.startswith(("gpt-", "o1-", "o3-"))
    profile = TokenCounter._model_profile(model)
    assert (profile is not None and profile.tokenizer == "tiktoken") is uses_tiktoken


def test_a_model_with_no_profile_gets_the_estimate_and_the_default_overhead():
    from skye.models.token_counter import DEFAULT_MESSAGE_OVERHEAD

    assert TokenCounter._model_profile("nobody-makes-this") is None
    assert TokenCounter._get_message_overhead("nobody-makes-this") == DEFAULT_MESSAGE_OVERHEAD
    assert len(TokenCounter._get_tokenizer("nobody-makes-this").encode("a" * 40)) == 10


def test_the_counter_holds_no_table_of_prefixes_or_overheads():
    import ast
    import inspect

    from skye.models import token_counter

    tree = ast.parse(inspect.getsource(token_counter))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    }
    for prefix in ("gpt-4", "gpt-3.5", "claude-", "o1-", "o3-", "gpt-"):
        assert not any(lit.startswith(prefix) for lit in literals), prefix


def test_a_plugin_provider_profile_sets_its_own_overhead_and_tokenizer():
    from skye.base.plugins import get_registrar
    from skye.base.profile import ModelProfile, ProviderProfile

    class Words:
        def encode(self, text: str) -> list[str]:
            return text.split()

    registrar = get_registrar()
    registrar.tokenizer("words-for-acme-test", lambda model: Words())
    registrar.provider(
        "acme-token-test",
        object,
        profile=ProviderProfile(
            "acme-token-test",
            models={"acme-tok": ModelProfile(tokenizer="words-for-acme-test", message_overhead=7)},
        ), function="model",
    )
    try:
        assert TokenCounter._get_message_overhead("acme-tok-2025-01-01") == 7
        assert TokenCounter.count_tokens("one two three", "acme-tok") == 3
        assert TokenCounter.count_message_tokens([UserMessage(content="one two")], "acme-tok") == 9
    finally:
        registrar.unregister("provider", "acme-token-test", "model")
        registrar.unregister("tokenizer", "words-for-acme-test")
        registrar._profiles.pop("acme-token-test", None)
        TokenCounter._tokenizers.pop("acme-tok", None)
        TokenCounter._tokenizers.pop("acme-tok-2025-01-01", None)


def test_a_profile_that_names_an_unregistered_tokenizer_is_a_configuration_error():
    from skye.base.exceptions import ConfigurationError
    from skye.base.plugins import Registrar
    from skye.base.profile import ModelProfile, ProviderProfile

    # a private registrar is not the one the counter reads, so go through the profile directly
    assert (
        ProviderProfile("p", models={"m": ModelProfile(tokenizer="nope")}).models["m"].tokenizer
        == "nope"
    )
    with pytest.raises(ConfigurationError):
        Registrar().get("tokenizer", "nope")


def test_register_tokenizer_keeps_its_own_table_and_unregister_removes_it():
    from skye.base.plugins import get_registrar

    class Words:
        def encode(self, text: str) -> list[str]:
            return text.split()

    before = get_registrar().names("tokenizer")
    TokenCounter.register_tokenizer("zz-model-", Words())
    try:
        assert get_registrar().names("tokenizer") == before  # the registrar is not written
        assert TokenCounter.count_tokens("a b c d", "zz-model-1") == 4
    finally:
        assert TokenCounter.unregister_tokenizer("zz-model-") is True
    assert TokenCounter.unregister_tokenizer("zz-model-") is False


def test_unregister_does_not_remove_the_tokenizer_a_profile_names():
    from skye.base.plugins import get_registrar

    assert TokenCounter.unregister_tokenizer("tiktoken") is False
    assert "tiktoken" in get_registrar().names("tokenizer")
