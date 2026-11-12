"""Cost calculation utilities for model API usage.

This module provides utilities for estimating API costs based on token usage
and model pricing. It includes pricing data for major models and supports
custom pricing configurations.

Example:
    >>> from skye.models.cost import CostCalculator
    >>> from skye.base.completion import TokenUsage
    >>>
    >>> usage = TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150)
    >>> cost = CostCalculator.calculate_cost("gpt-4", usage)
    >>> print(f"${cost:.4f}")
    $0.0060
"""

from typing import Any

from skye.base.completion import TokenUsage
from skye.base.exceptions import ValidationError
from skye.base.interfaces.cost_calculator import CostCalculatorInterface
from skye.base.plugins import get_registrar
from skye.base.profile import ModelProfile, ProviderProfile, find_model_profile


def usage_of(prompt: Any, completion: Any, total: Any = None) -> TokenUsage | None:
    """The tokens a provider reported, or ``None`` when it reported none.

    A missing, ``None`` or negative number counts as 0; both counts at 0 mean the provider said nothing.
    ``total`` defaults to the sum of the two.

    Example:
        >>> usage_of(10, 5)
        TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        >>> usage_of(None, 0) is None
        True
    """

    def count(value: Any) -> int:
        return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0

    prompt_tokens, completion_tokens = count(prompt), count(completion)
    if prompt_tokens == 0 and completion_tokens == 0:
        return None
    return TokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=count(total) or prompt_tokens + completion_tokens,
    )


def check_pricing(pricing: object) -> dict[str, float] | None:
    """Return ``pricing`` when it is ``None`` or ``{"prompt": p, "completion": c}`` (USD per 1M tokens, 0 or more).

    Raises:
        ValidationError: The prices are not those two non-negative numbers.

    Example:
        >>> check_pricing({"prompt": 1, "completion": 2.5})
        {'prompt': 1.0, 'completion': 2.5}
    """
    if pricing is None:
        return None
    if not isinstance(pricing, dict) or set(pricing) != {"prompt", "completion"}:
        raise ValidationError(
            'pricing must be {"prompt": price, "completion": price} in USD per 1M tokens',
            "pricing",
            pricing,
        )
    prices: dict[str, float] = {}
    for key, value in pricing.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ValidationError(
                f"pricing[{key!r}] must be a number of 0 or more", "pricing", pricing
            )
        prices[key] = float(value)
    return prices


def _price_of(entry: ModelProfile) -> dict[str, float] | None:
    """``{"prompt": p, "completion": c}`` of a model profile, or ``None`` when either price is unknown."""
    if entry.prompt_price is None or entry.completion_price is None:
        return None
    return {"prompt": entry.prompt_price, "completion": entry.completion_price}


def _profiles() -> list[ProviderProfile]:
    """The provider profiles in force: every one registered with the default registrar (the built-in ones included), by provider name."""
    registrar = get_registrar()
    found: dict[str, ProviderProfile] = {}
    for name in registrar.names("provider"):
        profile = registrar.get_profile(name)
        if profile is not None:
            found.setdefault(name, profile)
    return list(found.values())


class CostCalculator(CostCalculatorInterface):
    """Calculate API costs based on token usage.

    This class provides methods to estimate costs for API calls based on
    token usage and model pricing. Pricing is per 1M tokens.

    It holds no price list. The prices of a provider are in its ``ProviderProfile``, registered with the provider
    (Requirement 59 of steering); ``add_custom_pricing`` adds a user layer that wins over every profile. The built-in
    prices are the list prices of November 2024 and are not kept up to date: newer models are missing and prices change.
    For a real bill, pass your own prices (``add_custom_pricing``) or read the provider's current price list.

    Example:
        >>> usage = TokenUsage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
        >>> cost = CostCalculator.calculate_cost("gpt-4", usage)
        >>> cost > 0
        True
    """

    # The user layer of ``add_custom_pricing``: model name -> {"prompt": ..., "completion": ...} (USD per 1M tokens).
    _custom: dict[str, dict[str, float]] = {}

    @classmethod
    def calculate_cost(
        cls, model: str, usage: TokenUsage, custom_pricing: dict[str, float] | None = None
    ) -> float:
        """Calculate cost for a completion.

        Args:
            model: Model identifier (e.g., 'gpt-4', 'claude-3-sonnet').
            usage: Token usage information from the completion.
            custom_pricing: Optional custom pricing override with 'prompt' and
                'completion' keys (per 1M tokens).

        Returns:
            Estimated cost in USD.

        Example:
            >>> usage = TokenUsage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
            >>> cost = CostCalculator.calculate_cost("gpt-4", usage)
            >>> cost > 0
            True
            >>>
            >>> # With custom pricing
            >>> custom = {"prompt": 5.0, "completion": 10.0}
            >>> cost = CostCalculator.calculate_cost("custom-model", usage, custom)
            >>> cost > 0
            True
        """
        pricing = custom_pricing or cls.get_pricing(model)

        if not pricing:
            return 0.0  # Unknown model, can't estimate

        prompt_cost = (usage.prompt_tokens / 1_000_000) * pricing["prompt"]
        completion_cost = (usage.completion_tokens / 1_000_000) * pricing["completion"]

        return prompt_cost + completion_cost

    @classmethod
    def add_custom_pricing(cls, model: str, prompt_price: float, completion_price: float) -> None:
        """Add custom pricing for a model.

        This allows you to add pricing for custom or fine-tuned models that
        aren't in the default pricing table.

        Args:
            model: Model identifier.
            prompt_price: Price per 1M prompt tokens in USD.
            completion_price: Price per 1M completion tokens in USD.

        Example:
            >>> CostCalculator.add_custom_pricing("my-custom-model", 5.0, 10.0)
            >>> CostCalculator.get_pricing("my-custom-model")
            {'prompt': 5.0, 'completion': 10.0}
        """
        cls._custom[model] = {"prompt": prompt_price, "completion": completion_price}

    @classmethod
    def get_pricing(cls, model: str) -> dict[str, float] | None:
        """Get pricing information for a model.

        Args:
            model: Model identifier.

        Returns:
            Dictionary with 'prompt' and 'completion' prices per 1M tokens,
            or None if model pricing is not available.

        Example:
            >>> pricing = CostCalculator.get_pricing("gpt-4")
            >>> pricing is not None
            True
            >>> "prompt" in pricing and "completion" in pricing
            True
        """
        custom = cls._custom.get(model)
        if custom is not None:
            return dict(custom)
        for profile in _profiles():
            entry = profile.models.get(model)
            if entry is not None:
                return _price_of(entry)
        return None

    @classmethod
    def pricing_for(cls, model: str) -> dict[str, float] | None:
        """Pricing of ``model``, allowing a dated or versioned name: ``claude-3-opus-20240229`` finds ``claude-3-opus``.

        The exact name wins. Otherwise the longest known name counts only when what follows it is a date or a version
        (``-2024-08-06``, ``-20240229``, ``-0613``, ``@001``, ``:0``). Another model that merely starts with a known
        name (``gpt-4o`` for ``gpt-4``) is not priced at the price of the shorter one: it has no price here.

        Example:
            >>> CostCalculator.pricing_for("gpt-4-0613") == CostCalculator.get_pricing("gpt-4")
            True
            >>> CostCalculator.pricing_for("claude-3-opus-20240229") == CostCalculator.get_pricing("claude-3-opus")
            True
            >>> CostCalculator.pricing_for("no-such-model") is None
            True
        """
        exact = cls.get_pricing(model)
        if exact is not None:
            return exact
        # The user layer is searched as one more profile, so that its dated names are found by the same rule as the others.
        layers = [
            ProviderProfile(
                "custom",
                models={
                    n: ModelProfile(p["prompt"], p["completion"]) for n, p in cls._custom.items()
                },
            )
        ]
        best: tuple[int, ModelProfile] | None = None
        for profile in [*layers, *_profiles()]:
            entry = find_model_profile(profile, model)
            if entry is None or _price_of(entry) is None:
                continue
            length = max(len(name) for name, value in profile.models.items() if value is entry)
            if (
                best is None or length > best[0]
            ):  # the first layer wins a tie: the user layer comes first
                best = (length, entry)
        return _price_of(best[1]) if best else None

    @classmethod
    def breakdown(
        cls,
        model: str,
        usage: TokenUsage,
        custom_pricing: dict[str, float] | None = None,
        *,
        exact: bool = True,
    ) -> dict[str, Any] | None:
        """The cost of ``usage`` split into the prompt and the completion, or ``None`` when the model has no price.

        Unlike :meth:`calculate_cost`, an unknown model is not 0.0: it is ``None``, so "free" is never guessed.

        Args:
            model: Model identifier (a dated name is accepted, see :meth:`pricing_for`).
            usage: The tokens to price.
            custom_pricing: Prices that win over the table (``prompt`` and ``completion``, USD per 1M tokens).
            exact: ``True`` when the tokens are the provider's count, ``False`` when they were estimated.

        Returns:
            ``{"prompt": usd, "completion": usd, "total": usd, "currency": "USD", "exact": bool}``.

        Example:
            >>> usage = TokenUsage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
            >>> cost = CostCalculator.breakdown("gpt-4", usage)
            >>> round(cost["prompt"], 4), round(cost["completion"], 4), round(cost["total"], 4)
            (0.03, 0.03, 0.06)
            >>> CostCalculator.breakdown("no-such-model", usage) is None
            True
        """
        pricing = custom_pricing or cls.pricing_for(model)
        if not pricing:
            return None
        prompt = (usage.prompt_tokens / 1_000_000) * pricing["prompt"]
        completion = (usage.completion_tokens / 1_000_000) * pricing["completion"]
        return {
            "prompt": prompt,
            "completion": completion,
            "total": prompt + completion,
            "currency": "USD",
            "exact": exact,
        }

    @classmethod
    def list_models(cls) -> list[str]:
        """List all models with known pricing.

        Returns:
            List of model identifiers with pricing data.

        Example:
            >>> models = CostCalculator.list_models()
            >>> "gpt-4" in models
            True
        """
        names: dict[str, None] = {}
        for profile in _profiles():
            for name, entry in profile.models.items():
                if _price_of(entry) is not None:
                    names.setdefault(name)
        names.update(dict.fromkeys(cls._custom))
        return list(names)
