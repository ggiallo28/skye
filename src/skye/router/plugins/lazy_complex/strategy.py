# D113, O76
"""The ``lazy_complex`` routing strategy: a deliberately naive choice of the model by how hard the
request looks.

The models of a route are ordered from the cheap one (the first) to the strong one (the last). The
strategy gives the request a level from 0 to 2 and
takes the model at that level:

* +1 when the prompt is long: the estimate of its tokens is above ``LONG_PROMPT_TOKENS``;
* +1 when the request asks for tools (``capabilities``) or for a structured answer
  (``response_schema``).

The index is ``level / 2 * (number of models - 1)`` rounded half up: with two models level 0 is the
cheap one and levels 1 and 2 the strong one; with
three models the levels give the first, the middle and the last; one model is always chosen. A
request with no estimate and no request is level 0.

This is the first version and it is meant to be improved: it reads two signals, the length and the
two flags, and nothing about the content,
the history or the metrics.

Raises: nothing of its own; the selector rejects an empty list of models before it calls a strategy.
Missing: no estimate and no request give level 0, the cheap model.
Concurrency: the selector builds a strategy for each call; it keeps no state and does no I/O.
"""

from __future__ import annotations

from skye.router.routing_strategies import RouterStrategy, StrategyContext

# : A prompt with more estimated tokens than this is long. The estimate is about four characters per
# token.
LONG_PROMPT_TOKENS = 800


class LazyComplexStrategy(RouterStrategy):
    """The cheap model for an easy request, the strong one for a hard one; the first model is the
    cheap one and the last the strong one."""

    def select(self, context: StrategyContext) -> str:
        models = context.models
        level = 0
        if context.token_estimate is not None and context.token_estimate[0] > LONG_PROMPT_TOKENS:
            level += 1
        request = context.request
        if request is not None and (request.capabilities or request.response_schema):
            level += 1
        return models[int(level / 2 * (len(models) - 1) + 0.5)]
