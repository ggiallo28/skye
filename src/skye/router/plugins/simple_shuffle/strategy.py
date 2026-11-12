"""The ``simple_shuffle`` routing strategy: a random target.

A strategy of the router: it reads the state of the router through the selector it is built with (``RouterStrategy``).

Raises: nothing of its own; the selector rejects an empty list of models before it calls a strategy.
Missing: a model with no metric counts as the default of the metric.
Concurrency: the selector builds a strategy for each call and the strategies keep no state (the round-robin index lives in the router).
"""

from __future__ import annotations

import random

from skye.router.routing_strategies import RouterStrategy, StrategyContext


class SimpleShuffleStrategy(RouterStrategy):
    """A random target."""

    def select(self, context: StrategyContext) -> str:
        available_models = context.models
        return random.choice(available_models)
