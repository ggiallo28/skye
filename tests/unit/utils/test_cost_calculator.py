"""Unit tests for CostCalculator utility.

Tests cost calculation functionality for various models and scenarios.
"""

import pytest

from skye.base.completion import TokenUsage
from skye.models.cost import CostCalculator


class TestCostCalculator:
    """Test suite for CostCalculator."""

    def test_calculate_cost_gpt4(self):
        """Test cost calculation for GPT-4."""
        usage = TokenUsage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
        cost = CostCalculator.calculate_cost("gpt-4", usage)
        # (1000/1M * 30) + (500/1M * 60) = 0.03 + 0.03 = 0.06
        assert cost == pytest.approx(0.06, rel=1e-6)

    def test_calculate_cost_gpt4_turbo(self):
        """Test cost calculation for GPT-4 Turbo."""
        usage = TokenUsage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
        cost = CostCalculator.calculate_cost("gpt-4-turbo", usage)
        # (1000/1M * 10) + (500/1M * 30) = 0.01 + 0.015 = 0.025
        assert cost == pytest.approx(0.025, rel=1e-6)

    def test_calculate_cost_gpt35_turbo(self):
        """Test cost calculation for GPT-3.5 Turbo."""
        usage = TokenUsage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
        cost = CostCalculator.calculate_cost("gpt-3.5-turbo", usage)
        # (1000/1M * 0.5) + (500/1M * 1.5) = 0.0005 + 0.00075 = 0.00125
        assert cost == pytest.approx(0.00125, rel=1e-6)

    def test_calculate_cost_claude_opus(self):
        """Test cost calculation for Claude 3 Opus."""
        usage = TokenUsage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
        cost = CostCalculator.calculate_cost("claude-3-opus", usage)
        # (1000/1M * 15) + (500/1M * 75) = 0.015 + 0.0375 = 0.0525
        assert cost == pytest.approx(0.0525, rel=1e-6)

    def test_calculate_cost_claude_sonnet(self):
        """Test cost calculation for Claude 3 Sonnet."""
        usage = TokenUsage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
        cost = CostCalculator.calculate_cost("claude-3-sonnet", usage)
        # (1000/1M * 3) + (500/1M * 15) = 0.003 + 0.0075 = 0.0105
        assert cost == pytest.approx(0.0105, rel=1e-6)

    def test_calculate_cost_claude_haiku(self):
        """Test cost calculation for Claude 3 Haiku."""
        usage = TokenUsage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
        cost = CostCalculator.calculate_cost("claude-3-haiku", usage)
        # (1000/1M * 0.25) + (500/1M * 1.25) = 0.00025 + 0.000625 = 0.000875
        assert cost == pytest.approx(0.000875, rel=1e-6)

    def test_calculate_cost_unknown_model(self):
        """Test cost calculation for unknown model returns 0.0."""
        usage = TokenUsage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
        cost = CostCalculator.calculate_cost("unknown-model", usage)
        assert cost == 0.0

    def test_calculate_cost_with_custom_pricing(self):
        """Test cost calculation with custom pricing."""
        usage = TokenUsage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
        custom_pricing = {"prompt": 5.0, "completion": 10.0}
        cost = CostCalculator.calculate_cost("custom-model", usage, custom_pricing)
        # (1000/1M * 5) + (500/1M * 10) = 0.005 + 0.005 = 0.01
        assert cost == pytest.approx(0.01, rel=1e-6)

    def test_calculate_cost_zero_tokens(self):
        """Test cost calculation with zero tokens."""
        usage = TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
        cost = CostCalculator.calculate_cost("gpt-4", usage)
        assert cost == 0.0

    def test_calculate_cost_only_prompt_tokens(self):
        """Test cost calculation with only prompt tokens."""
        usage = TokenUsage(prompt_tokens=1000, completion_tokens=0, total_tokens=1000)
        cost = CostCalculator.calculate_cost("gpt-4", usage)
        # (1000/1M * 30) + (0/1M * 60) = 0.03
        assert cost == pytest.approx(0.03, rel=1e-6)

    def test_calculate_cost_only_completion_tokens(self):
        """Test cost calculation with only completion tokens."""
        usage = TokenUsage(prompt_tokens=0, completion_tokens=500, total_tokens=500)
        cost = CostCalculator.calculate_cost("gpt-4", usage)
        # (0/1M * 30) + (500/1M * 60) = 0.03
        assert cost == pytest.approx(0.03, rel=1e-6)

    def test_calculate_cost_large_token_count(self):
        """Test cost calculation with large token counts."""
        usage = TokenUsage(prompt_tokens=100_000, completion_tokens=50_000, total_tokens=150_000)
        cost = CostCalculator.calculate_cost("gpt-4", usage)
        # (100000/1M * 30) + (50000/1M * 60) = 3.0 + 3.0 = 6.0
        assert cost == pytest.approx(6.0, rel=1e-6)

    def test_add_custom_pricing(self):
        """Test adding custom pricing for a model."""
        CostCalculator.add_custom_pricing("my-custom-model", 5.0, 10.0)
        assert "my-custom-model" in CostCalculator.list_models()
        assert CostCalculator.get_pricing("my-custom-model") == {"prompt": 5.0, "completion": 10.0}

    def test_add_custom_pricing_and_calculate(self):
        """Test adding custom pricing and calculating cost."""
        CostCalculator.add_custom_pricing("test-model", 2.0, 4.0)
        usage = TokenUsage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
        cost = CostCalculator.calculate_cost("test-model", usage)
        # (1000/1M * 2) + (500/1M * 4) = 0.002 + 0.002 = 0.004
        assert cost == pytest.approx(0.004, rel=1e-6)

    def test_get_pricing_known_model(self):
        """Test getting pricing for a known model."""
        pricing = CostCalculator.get_pricing("gpt-4")
        assert pricing is not None
        assert "prompt" in pricing
        assert "completion" in pricing
        assert pricing["prompt"] == 30.0
        assert pricing["completion"] == 60.0

    def test_get_pricing_unknown_model(self):
        """Test getting pricing for an unknown model."""
        pricing = CostCalculator.get_pricing("unknown-model-xyz")
        assert pricing is None

    def test_list_models(self):
        """Test listing all models with pricing."""
        models = CostCalculator.list_models()
        assert isinstance(models, list)
        assert len(models) > 0
        assert "gpt-4" in models
        assert "claude-3-sonnet" in models

    @pytest.mark.parametrize(
        "model,prompt_tokens,completion_tokens,expected_cost",
        [
            ("gpt-4", 1000, 500, 0.06),
            ("gpt-4-turbo", 1000, 500, 0.025),
            ("gpt-3.5-turbo", 1000, 500, 0.00125),
            ("claude-3-opus", 1000, 500, 0.0525),
            ("claude-3-sonnet", 1000, 500, 0.0105),
            ("claude-3-haiku", 1000, 500, 0.000875),
        ],
    )
    def test_calculate_cost_various_models(
        self, model: str, prompt_tokens: int, completion_tokens: int, expected_cost: float
    ):
        """Test cost calculation for various models."""
        usage = TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        )
        cost = CostCalculator.calculate_cost(model, usage)
        assert cost == pytest.approx(expected_cost, rel=1e-6)

    def test_calculate_cost_o1_preview(self):
        """Test cost calculation for o1-preview."""
        usage = TokenUsage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
        cost = CostCalculator.calculate_cost("o1-preview", usage)
        # (1000/1M * 15) + (500/1M * 60) = 0.015 + 0.03 = 0.045
        assert cost == pytest.approx(0.045, rel=1e-6)

    def test_calculate_cost_o1_mini(self):
        """Test cost calculation for o1-mini."""
        usage = TokenUsage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
        cost = CostCalculator.calculate_cost("o1-mini", usage)
        # (1000/1M * 3) + (500/1M * 12) = 0.003 + 0.006 = 0.009
        assert cost == pytest.approx(0.009, rel=1e-6)

    def test_calculate_cost_bedrock_model(self):
        """Test cost calculation for Bedrock model."""
        usage = TokenUsage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
        cost = CostCalculator.calculate_cost("anthropic.claude-3-sonnet-20240229-v1:0", usage)
        # Should use same pricing as claude-3-sonnet
        assert cost == pytest.approx(0.0105, rel=1e-6)

    def test_calculate_cost_gemini_pro(self):
        """Test cost calculation for Gemini Pro."""
        usage = TokenUsage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
        cost = CostCalculator.calculate_cost("gemini-pro", usage)
        # (1000/1M * 0.5) + (500/1M * 1.5) = 0.0005 + 0.00075 = 0.00125
        assert cost == pytest.approx(0.00125, rel=1e-6)

    def test_custom_pricing_overrides_default(self):
        """Test that custom pricing overrides default pricing."""
        usage = TokenUsage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
        # First calculate with default pricing
        default_cost = CostCalculator.calculate_cost("gpt-4", usage)
        # Now calculate with custom pricing
        custom_pricing = {"prompt": 1.0, "completion": 2.0}
        custom_cost = CostCalculator.calculate_cost("gpt-4", usage, custom_pricing)
        # Custom cost should be different from default
        assert custom_cost != default_cost
        # Custom cost should be (1000/1M * 1) + (500/1M * 2) = 0.001 + 0.001 = 0.002
        assert custom_cost == pytest.approx(0.002, rel=1e-6)
