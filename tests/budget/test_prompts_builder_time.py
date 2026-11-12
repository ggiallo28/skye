"""The time to build a `BasePromptBuilder` (task 24.8, open decision O78).

A builder registers the bundled `.skye` templates and compiles each at its first use, so building one costs milliseconds and not the 130 ms
that compiling all 40 cost. The test builds one in a fresh interpreter, the first of the process (so the process cache of compiled templates is
empty), and takes the best of several runs. The limit is `[prompts] max_builder_ms` in budgets.toml. The first use of a template, and the load of
the registrar for the filters at the first render, are not in this number.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile

from tests.budget.measure import load_budgets, report

FRESH_BUILD = """
import time
import skye.prompts
from skye.prompts import BasePromptBuilder
start = time.perf_counter()
BasePromptBuilder()
print((time.perf_counter() - start) * 1000)
"""

COMPILES_AT_USE = """
import skye.prompts.messages as messages
calls = []
real = messages._compile_skye
messages._compile_skye = lambda *args: (calls.append(args[0]), real(*args))[1]
from skye.prompts import BasePromptBuilder
builder = BasePromptBuilder()
before = len(calls)
builder.get_template_variables("chat")
print(before, len(calls))
"""


def test_building_a_prompt_builder_stays_below_the_limit() -> None:
    budget = load_budgets()["prompts"]
    times = [
        float(
            subprocess.check_output(
                [sys.executable, "-c", FRESH_BUILD], text=True, cwd=tempfile.gettempdir()
            )
        )
        for _ in range(budget["runs"])
    ]
    best = min(times)
    report(
        f"| BasePromptBuilder() in a fresh interpreter | best of {budget['runs']}: {best:.1f} ms | max {budget['max_builder_ms']} ms | |"
    )
    assert best <= budget["max_builder_ms"], (
        f"BasePromptBuilder() takes {best:.1f} ms (best of {budget['runs']}), over the limit of {budget['max_builder_ms']} ms. "
        "A bundled template must not be compiled when the builder is built: compile it at its first use."
    )


def test_a_fresh_builder_compiles_no_bundled_template_until_one_is_used() -> None:
    out = subprocess.check_output(
        [sys.executable, "-c", COMPILES_AT_USE], text=True, cwd=tempfile.gettempdir()
    )
    built, used = (int(x) for x in out.split())
    assert (built, used) == (0, 1)
