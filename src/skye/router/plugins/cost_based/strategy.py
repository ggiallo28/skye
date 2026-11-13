"""The ``cost_based`` routing strategy: the target with the lowest estimated cost.

A strategy of the router: it reads the state of the router through the selector it is built with
(``RouterStrategy``).

Raises: nothing of its own; the selector rejects an empty list of models before it calls a strategy.
Missing: a model with no metric counts as the default of the metric.
Concurrency: the selector builds a strategy for each call and the strategies keep no state (the
round-robin index lives in the router).
"""

from __future__ import annotations

from skye.router.routing_strategies import RouterStrategy, StrategyContext, estimated_cost


class CostBasedStrategy(RouterStrategy):
    """The target with the lowest estimated cost."""

    def select(self, context: StrategyContext) -> str:
        """Targets without a cost come after every target with one; ties keep the configured
        order."""
        available_models = context.models
        token_estimate = context.token_estimate

        def key(model_id: str) -> tuple[int, float]:
            target = self.selector.model_targets.get(model_id)
            cost = None if target is None else estimated_cost(target, token_estimate)
            return (1, 0.0) if cost is None else (0, cost)

        return min(available_models, key=key)
