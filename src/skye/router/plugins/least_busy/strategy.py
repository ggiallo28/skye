"""The ``least_busy`` routing strategy: the target with the fewest active requests.

A strategy of the router: it reads the state of the router through the selector it is built with
(``RouterStrategy``).

Raises: nothing of its own; the selector rejects an empty list of models before it calls a strategy.
Missing: a model with no metric counts as the default of the metric.
Concurrency: the selector builds a strategy for each call and the strategies keep no state (the
round-robin index lives in the router).
"""

from __future__ import annotations

from skye.router.routing_strategies import RouterStrategy, StrategyContext


class LeastBusyStrategy(RouterStrategy):
    """The target with the fewest active requests."""

    def select(self, context: StrategyContext) -> str:
        available_models = context.models
        return min(available_models, key=lambda m: self.selector.metric(m, "active_requests", 0))
