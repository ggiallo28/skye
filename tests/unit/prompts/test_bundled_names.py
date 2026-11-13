"""The set of bundled prompts is pinned (D118, Requirement 30.14).

The library bundles six templates and three shared partials; a template or a partial that is added,
removed or renamed must change this test and the decision with it.
"""

from __future__ import annotations

from skye.prompts import loaders

BUNDLED = {
    "agent_react",
    "extraction_generic",
    "generation_code",
    "text_explanation",
    "text_question_answering",
    "text_summarization",
}

PARTIALS = {"common/memories.skye", "common/system_prompt.skye", "common/tools.skye"}


def test_the_bundled_templates_are_exactly_the_six_of_the_decision():
    assert set(loaders.bundled_names()) == BUNDLED
    assert len(loaders.bundled_names()) == len(BUNDLED)


def test_the_bundled_partials_are_exactly_the_three_shared_ones():
    assert set(loaders.bundled_partials()) == PARTIALS
    assert len(loaders.bundled_partials()) == len(PARTIALS)
