# Requirement 58.4, D98, D111
"""``check_template_filter``: the conformance function of the kind ``prompts`` owns.

It runs offline, returns the names of the checks it passed and raises an ``AssertionError`` that
names the first that fails
(``skye.store.check_backend`` is the model). It is a coroutine function, so one runner awaits every
kind alike. The filter is also rendered by the
engine of the templates, in a template of one line, so it is checked the way a template uses it.

Example:
    >>> import asyncio
    >>> from skye.prompts.conformance import check_template_filter
    >>> asyncio.run(check_template_filter(lambda value: str(value)[::-1]))
    ['callable', 'accepts_a_value', 'renders', 'repeatable']

Raises: ``AssertionError`` naming the first failed check.
Missing: a filter that needs more arguments than the value is checked with a ``value`` it accepts
and no arguments; its arguments are not checked.
Concurrency: nothing is shared; the template is rendered in the call.
"""

from __future__ import annotations

from typing import Any

from skye.base.conformance import Check, require, run_checks
from skye.prompts.engine import render_template


async def check_template_filter(function: Any, value: Any = "hello world") -> list[str]:
    """Check a template filter: a callable that takes a value, answers the same way twice and
    renders in a template as ``{{ v | f }}``."""

    def accepts() -> None:
        function(value)

    def renders() -> None:
        shown = render_template("{{ v | f }}", {"v": value}, {"f": function})
        require(
            shown == str(function(value)),
            f"the template gave {shown!r}, the call gave {function(value)!r}",
        )

    def repeatable() -> None:
        require(
            repr(function(value)) == repr(function(value)),
            "the filter must give the same answer for the same value",
        )

    checks: list[Check] = [
        ("callable", lambda: require(callable(function), "a filter must be callable")),
        ("accepts_a_value", accepts),
        ("renders", renders),
        ("repeatable", repeatable),
    ]
    return await run_checks("template filter", function, checks)


__all__ = ["check_template_filter"]
