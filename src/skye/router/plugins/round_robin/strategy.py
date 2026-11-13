"""The ``round_robin`` routing strategy: each target in turn.

A strategy of the router: it reads the state of the router through the selector it is built with
(``RouterStrategy``).

Raises: nothing of its own; the selector rejects an empty list of models before it calls a strategy.
Missing: a model with no metric counts as the default of the metric.
Concurrency: the selector builds a strategy for each call and the strategies keep no state (the
round-robin index lives in the router).
"""

from __future__ import annotations

from skye.router.routing_strategies import RouterStrategy, StrategyContext


class RoundRobinStrategy(RouterStrategy):
    """Each target in turn."""

    def select(self, context: StrategyContext) -> str:
        available_models = context.models
        alias = context.alias
        key = alias if alias else "_default"
        index = self.selector.round_robin_index.get(key, 0)
        model_id = available_models[index % len(available_models)]
        self.selector.round_robin_index[key] = index + 1
        return model_id
