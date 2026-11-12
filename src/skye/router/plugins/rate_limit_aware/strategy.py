"""The ``rate_limit_aware`` routing strategy: the target with the most rate limit capacity left.

A strategy of the router: it reads the state of the router through the selector it is built with (``RouterStrategy``).

Raises: nothing of its own; the selector rejects an empty list of models before it calls a strategy.
Missing: a model with no metric counts as the default of the metric.
Concurrency: the selector builds a strategy for each call and the strategies keep no state (the round-robin index lives in the router).
"""

from __future__ import annotations


from skye.router.routing_strategies import RouterStrategy, StrategyContext


class RateLimitAwareStrategy(RouterStrategy):
    """The target with the most rate limit capacity left."""

    def select(self, context: StrategyContext) -> str:
        available_models = context.models

        def capacity_score(model_id: str) -> float:
            """0.0 is full, 1.0 is empty."""
            tracker = self.selector.rate_limits[model_id]
            if tracker.rpm_limit is None and tracker.tpm_limit is None:
                return 1.0
            rpm_capacity = 1.0
            if tracker.rpm_limit:
                used = self.selector.metric(model_id, "rpm_used", 0)
                rpm_capacity = 1.0 - (used / tracker.rpm_limit)
            tpm_capacity = 1.0
            if tracker.tpm_limit:
                used = self.selector.metric(model_id, "tpm_used", 0)
                tpm_capacity = 1.0 - (used / tracker.tpm_limit)
            return min(rpm_capacity, tpm_capacity)

        return max(available_models, key=capacity_score)
