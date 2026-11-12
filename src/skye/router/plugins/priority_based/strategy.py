"""The ``priority_based`` routing strategy: the target with the highest success rate.

A strategy of the router: it reads the state of the router through the selector it is built with (``RouterStrategy``).

Raises: nothing of its own; the selector rejects an empty list of models before it calls a strategy.
Missing: a model with no metric counts as the default of the metric.
Concurrency: the selector builds a strategy for each call and the strategies keep no state (the round-robin index lives in the router).
"""

from __future__ import annotations


from skye.router.routing_strategies import RouterStrategy, StrategyContext


class PriorityBasedStrategy(RouterStrategy):
    """The target with the highest success rate."""

    def select(self, context: StrategyContext) -> str:
        available_models = context.models
        return max(available_models, key=lambda m: self.selector.metric(m, "success_rate", 1.0))
