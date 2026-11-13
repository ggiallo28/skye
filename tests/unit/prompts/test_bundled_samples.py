"""Every bundled prompt has a data file of sample variables in ``examples/prompts/bundled`` (task
24.9).

A file holds one object (the variables of one render) or a list of them. The example
``examples/prompts/bundled_templates.py`` renders them all, so a new bundled prompt needs a sample.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skye.prompts import BasePromptBuilder
from skye.prompts.loaders import bundled_names

SAMPLES = Path(__file__).resolve().parents[3] / "examples" / "prompts" / "bundled"


def _renders(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else [data]


def test_every_bundled_prompt_has_a_sample_and_every_sample_a_prompt():
    names = set(bundled_names())
    samples = {path.stem for path in SAMPLES.glob("*.json")}
    assert names - samples == set(), f"no sample for: {sorted(names - samples)}"
    assert samples - names == set(), f"a sample with no bundled prompt: {sorted(samples - names)}"


@pytest.mark.parametrize("path", sorted(SAMPLES.glob("*.json")), ids=lambda p: p.stem)
def test_a_sample_renders_without_error(path: Path):
    builder = BasePromptBuilder()
    renders = _renders(path)
    assert renders and all(isinstance(variables, dict) for variables in renders)
    for variables in renders:
        assert builder.render(path.stem, variables)
