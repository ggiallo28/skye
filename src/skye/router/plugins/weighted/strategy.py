"""The ``weighted`` routing strategy: a random target, weighted by its configured weight or its success rate.

A strategy of the router: it reads the state of the router through the selector it is built with (``RouterStrategy``).

Raises: nothing of its own; the selector rejects an empty list of models before it calls a strategy.
Missing: a model with no metric counts as the default of the metric.
Concurrency: the selector builds a strategy for each call and the strategies keep no state (the round-robin index lives in the router).
"""

from __future__ import annotations

import random

from skye.router.routing_strategies import RouterStrategy, StrategyContext


class WeightedStrategy(RouterStrategy):
    """A random target, weighted by its configured weight or its success rate."""

    def select(self, context: StrategyContext) -> str:
        available_models = context.models
        weights = []
        for model_id in available_models:
            if model_id in self.selector.model_targets:
                weights.append(self.selector.model_targets[model_id].weight)
            else:
                weights.append(self.selector.metric(model_id, "success_rate", 1.0))
        if sum(weights) <= 0:
            # random.choices rejects all-zero weights; with no signal at all, pick uniformly.
            return random.choice(available_models)
        return random.choices(available_models, weights=weights)[0]
